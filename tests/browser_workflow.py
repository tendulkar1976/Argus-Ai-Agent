"""Browser integration test with a test-only provider. Run after the production UI build."""

import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

import httpx
import uvicorn
from playwright.sync_api import sync_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as state:
        os.environ["ARGUS_STATE_DIR"] = state
        os.environ["DATABASE_URL"] = "sqlite:///" + state + "/browser.db"
        from alembic.config import Config
        from alembic import command

        command.upgrade(Config("alembic.ini"), "head")
        from argus import gateway
        from argus.db import create_workspace
        from argus.api import app

        provider_calls = []

        def fixture(req):
            if req.url.path.endswith("models"):
                return httpx.Response(200, json={"data": [{"id": "browser-fixture"}]})
            body = json.loads(req.content)
            provider_calls.append(body)
            return httpx.Response(
                200,
                json={
                    "model": "browser-fixture",
                    "choices": [{"message": {"content": "7", "role": "assistant"}}],
                    "usage": {
                        "prompt_tokens": len(json.dumps(body["messages"])),
                        "completion_tokens": 1,
                    },
                },
            )

        gateway.transport = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(fixture)
        )
        token = create_workspace("Browser test")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            port = sock.getsockname()[1]
            server = uvicorn.Server(
                uvicorn.Config(app, access_log=False, log_level="error")
            )
            thread = threading.Thread(
                target=server.run, kwargs={"sockets": [sock]}, daemon=True
            )
            thread.start()
            try:
                for _ in range(100):
                    if server.started:
                        break
                    time.sleep(0.05)
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(
                        executable_path=os.environ.get("CHROMIUM_PATH"),
                        args=["--no-sandbox"],
                    )
                    p = browser.new_page(viewport={"width": 1366, "height": 900})
                    errors = []
                    p.on("pageerror", lambda e: errors.append(str(e)))
                    p.goto(f"http://127.0.0.1:{port}")
                    p.get_by_label("Workspace key", exact=True).fill(token)
                    p.get_by_role("button", name="Open Studio").click()
                    p.get_by_role("button", name="Configure provider").click()
                    p.get_by_label("Provider API key").fill("browser-test-secret")
                    p.get_by_role("button", name="Test connection").click()
                    p.get_by_label("Maximum input tokens").fill("4000")
                    p.get_by_label("Maximum output tokens").fill("500")
                    p.get_by_role("button", name="Save model version").click()
                    p.get_by_role("button", name="Overview", exact=True).click()
                    p.get_by_role("button", name="Run first request").click()
                    p.get_by_label("Task or question").fill("Discovery task")

                    def evidence():
                        for ref in ["A", "B"]:
                            p.get_by_role("button", name="Add passage").click()
                            p.get_by_label("Source ID", exact=True).last.fill(ref)
                            p.get_by_label("Passage", exact=True).last.fill(
                                "Seven samples were collected at the testing site."
                            )

                    evidence()
                    p.get_by_role("button", name="Run 1 provider call").click()
                    expect(
                        p.get_by_role("heading", name="Context composition")
                    ).to_be_visible()
                    p.get_by_role("button", name="Investigate trace").click()
                    p.get_by_label("Held-out task", exact=True).fill(
                        "Held-out benchmark task"
                    )
                    p.get_by_label("Expected answer or fields").fill("7")
                    evidence()

                    # Lose the first HTTP response after the server has finished the pair.
                    # Retrying the approval in Studio must return that same experiment.
                    p.evaluate("""() => {
                        const original = window.fetch;
                        window.fetch = async (...args) => {
                            const response = await original(...args);
                            if (args[0] === "/api/experiments" && args[1]?.method === "POST") {
                                window.fetch = original;
                                await response.text();
                                throw new TypeError("Test connection interrupted");
                            }
                            return response;
                        };
                    }""")
                    submit = p.get_by_role("button", name="Approve and run 2 calls")
                    submit.click()
                    expect(
                        p.get_by_text("Test connection interrupted", exact=True)
                    ).to_be_visible()
                    assert len(provider_calls) == 3
                    submit.click()
                    expect(
                        p.get_by_role("heading", name="Experiment results")
                    ).to_be_visible()
                    assert len(provider_calls) == 3
                    p.get_by_role("button", name="Replay pair").click()
                    expect(
                        p.get_by_role("heading", name="Candidate", exact=True)
                    ).to_be_visible()
                    p.get_by_role("button", name="Approve policy version").click()
                    p.get_by_role("button", name="Roll back", exact=True).click()
                    expect(p.get_by_text("Rolled back", exact=True)).to_be_visible()
                    p.set_viewport_size({"width": 390, "height": 844})
                    p.get_by_label("Toggle navigation").click()
                    p.get_by_role("button", name="Overview", exact=True).click()
                    expect(
                        p.get_by_role("heading", name="Overview", exact=True)
                    ).to_be_visible()
                    p.get_by_label("Switch color theme").click()
                    assert p.evaluate(
                        "document.documentElement.scrollWidth<=window.innerWidth"
                    )
                    assert not errors, errors
                    browser.close()
                    print(
                        "Browser journey passed: provider setup, execution, investigation, paired replay, approval, rollback and mobile navigation."
                    )
            finally:
                server.should_exit = True
                thread.join(5)


if __name__ == "__main__":
    main()
