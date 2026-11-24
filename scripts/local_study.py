import json, os, pathlib, sys, time, socket, threading, secrets, tempfile, subprocess
from contextlib import contextmanager
import httpx, uvicorn

sys.path.insert(0, os.getcwd())
import argparse
import hashlib
import importlib.metadata
import platform

parser = argparse.ArgumentParser(
    description="Run a genuine model study locally using GGUF and a temporary HTTPS endpoint."
)
parser.add_argument("--gguf", required=True, type=pathlib.Path)
parser.add_argument("--dataset", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--repeats", type=int, default=1)
parser.add_argument("--max-tokens", type=int, default=64)
parser.add_argument("--approve-calls", type=int, required=True)
parser.add_argument(
    "--verify-policy",
    action="store_true",
    help="Approve eligible results in the temporary workspace, monitor one extra local call, then roll back",
)
args = parser.parse_args()
temp = tempfile.TemporaryDirectory(prefix="argus-local-study-")
root = pathlib.Path(temp.name)
gguf = args.gguf.resolve()
dataset = json.loads(pathlib.Path(args.dataset).read_text())
planned = 1 + 2 * args.repeats * len(dataset["cases"])
if args.approve_calls != planned + int(args.verify_policy):
    raise SystemExit(f"Expected --approve-calls {planned + int(args.verify_policy)}")
if pathlib.Path(args.output).exists():
    raise SystemExit("Choose a new report path to preserve the previous result.")


@contextmanager
def serve(app, tls=False):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        config = uvicorn.Config(
            app,
            log_level="error",
            access_log=False,
            **(
                {
                    "ssl_keyfile": str(root / "tls.key"),
                    "ssl_certfile": str(root / "tls.pem"),
                }
                if tls
                else {}
            ),
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(
            target=server.run, kwargs={"sockets": [sock]}, daemon=True
        )
        thread.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.05)
            yield ("https" if tls else "http") + "://127.0.0.1:" + str(port)
        finally:
            server.should_exit = True
            thread.join(10)


subprocess.run(
    [
        "openssl",
        "req",
        "-new",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "2",
        "-keyout",
        str(root / "tls.key"),
        "-out",
        str(root / "tls.pem"),
        "-subj",
        "/CN=localhost",
        "-addext",
        "subjectAltName=IP:127.0.0.1",
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    check=True,
)
os.environ.update(
    ARGUS_LOCAL_MODEL_ID=gguf.stem,
    ARGUS_LOCAL_GGUF=str(gguf),
    ARGUS_LOCAL_PROVIDER_KEY=secrets.token_urlsafe(30),
    ARGUS_STATE_DIR=str(root / "state"),
    ARGUS_PROVIDER_CA=str(root / "tls.pem"),
)
from scripts.local_provider import app as inference

with serve(inference, True) as inference_url:
    os.environ["ARGUS_PROVIDERS"] = json.dumps({"Local GGUF": inference_url + "/v1"})
    from alembic.config import Config
    from alembic import command

    command.upgrade(Config("alembic.ini"), "head")
    from argus.db import create_workspace
    from argus.api import app
    from scripts.benchmark import run

    with serve(app) as url:
        token = create_workspace("Local inference study")
        with httpx.Client(
            base_url=url, headers={"Authorization": "Bearer " + token}, trust_env=False
        ) as c:
            c.put(
                "/api/settings",
                json={
                    "day_calls": args.approve_calls,
                    "day_micros": None,
                    "retention_days": 1,
                },
            ).raise_for_status()
            conn = c.post(
                "/api/connections",
                json={
                    "provider": "Local GGUF",
                    "secret": os.environ["ARGUS_LOCAL_PROVIDER_KEY"],
                },
            )
            conn.raise_for_status()
            mid = c.post(
                "/api/models",
                json={
                    "name": os.environ["ARGUS_LOCAL_MODEL_ID"],
                    "connection": conn.json()["id"],
                    "input_limit": 1792,
                    "output_limit": 256,
                },
            ).json()["id"]
        r = run(
            url,
            token,
            mid,
            args.dataset,
            args.repeats,
            planned,
            args.output,
            args.max_tokens,
        )
        with gguf.open("rb") as model_file:
            checksum = hashlib.file_digest(model_file, "sha256").hexdigest()
        r["runtime"] = {
            "model_file": gguf.name,
            "model_sha256": checksum,
            "llama_cpp_python": importlib.metadata.version("llama-cpp-python"),
            "python": platform.python_version(),
            "threads": 3,
            "context_window": 2048,
            "seed": 19,
            "temperature": 0,
            "max_output_tokens": args.max_tokens,
            "tls": "verified loopback",
        }
        if args.verify_policy and r["status"] == "eligible":
            with httpx.Client(
                base_url=url,
                headers={"Authorization": "Bearer " + token},
                trust_env=False,
            ) as c:
                policy = c.post("/api/experiments/" + r["id"] + "/approve")
                policy.raise_for_status()
                pid = policy.json()["id"]
                original = r["config"]["cases"][0]["request"]
                response = c.post(
                    "/v1/chat/completions", json={**original, "policy_id": pid}
                )
                response.raise_for_status()
                measured = c.get(
                    "/api/traces/" + response.headers["X-Argus-Trace"]
                ).json()
                rolled = c.post("/api/policies/" + pid + "/rollback")
                rolled.raise_for_status()
                after = c.post(
                    "/v1/chat/completions", json={**original, "policy_id": pid}
                )
                assert after.status_code == 409
                r["policy_demo"] = {
                    "policy": pid,
                    "trace": measured["id"],
                    "check": measured["monitor"],
                    "rolled_back": not rolled.json()["active"],
                    "post_rollback_status": after.status_code,
                }
        pathlib.Path(args.output).write_text(
            json.dumps(r, indent=2, ensure_ascii=False) + "\n"
        )
        print(
            json.dumps(
                {
                    k: r.get(k)
                    for k in ["status", "baseline", "candidate", "conditions", "error"]
                },
                indent=2,
            )
        )
