import os
import tempfile
import httpx
import pytest
from fastapi.testclient import TestClient

os.environ["ARGUS_STATE_DIR"] = tempfile.mkdtemp(prefix="argus-tests-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.environ["ARGUS_STATE_DIR"] + "/test.db"
from argus.api import app
from argus.db import create_workspace, engine
from argus.schema_v1 import metadata
from argus import gateway


@pytest.fixture
def api(monkeypatch):
    from argus.cache import entries
    from argus.workflows import spans
    from argus.judges import judges

    judges.drop(engine, checkfirst=True)
    spans.drop(engine, checkfirst=True)
    entries.drop(engine, checkfirst=True)
    metadata.drop_all(engine)
    metadata.create_all(engine)
    entries.create(engine)
    spans.create(engine)
    judges.create(engine)
    calls = []

    def stub(req):
        import json

        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "fixture-model"}]})
        data = json.loads(req.content)
        calls.append(data)
        if data["messages"][0]["content"] == "FAIL":
            return httpx.Response(503)
        usage = {
            "prompt_tokens": len(json.dumps(data["messages"])),
            "completion_tokens": 1,
            "prompt_tokens_details": {"cached_tokens": 0},
        }
        if data.get("stream"):
            chunks = [
                {
                    "choices": [{"delta": {"content": "7"}}],
                    "model": "fixture-model",
                    "id": "fixture-stream",
                },
                {"choices": [], "usage": usage},
            ]
            return httpx.Response(
                200,
                text="".join("data: " + json.dumps(c) + "\n\n" for c in chunks)
                + "data: [DONE]\n\n",
            )
        output = "7"
        if data["messages"][0]["content"].startswith("Evaluate a submitted answer"):
            submitted = json.loads(data["messages"][1]["content"])["answer"]
            output = json.dumps(
                {
                    "verdict": "pass" if submitted == "7" else "fail",
                    "evidence": "Compared to the calibration reference",
                }
            )
        return httpx.Response(
            200,
            json={
                "id": "fixture-call",
                "model": "fixture-model",
                "choices": [{"message": {"role": "assistant", "content": output}}],
                "usage": usage,
            },
        )

    monkeypatch.setattr(
        gateway,
        "transport",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(stub)),
    )
    with TestClient(app) as client:
        token = create_workspace("Test")
        client.headers["Authorization"] = "Bearer " + token
        c = client.post(
            "/api/connections", json={"provider": "OpenAI", "secret": "fixture-secret"}
        ).json()
        m = client.post(
            "/api/models",
            json={
                "connection": c["id"],
                "name": "fixture-model",
                "input_limit": 4000,
                "output_limit": 500,
                "input_rate": 2,
                "output_rate": 4,
                "stream_usage": True,
            },
        ).json()["id"]
        yield client, m, calls
