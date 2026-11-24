import asyncio
import json
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from starlette.staticfiles import StaticFiles
from pathlib import Path
from argus.config import PROVIDERS, seal, unseal
from argus.contracts import Chat, Connection, ModelSpec, Settings, KeySpec, Experiment
from argus.db import audit, engine, rows, scoped, uid, digest, issue
from argus.schema_v1 import (
    workspaces,
    keys,
    connections,
    models,
    traces,
    policies,
    experiments,
    events,
)
from argus.gateway import discover, execute, lookup
from argus.research import (
    investigation,
    experiment,
    approve,
    apply_policy,
    monitor,
    prune,
    percentile,
)
from argus.intelligence import inspect
from argus.tokens import installed, adapter
from argus.workflows import timeline
from argus.judges import judges, calibrate, Calibration


@asynccontextmanager
async def lifespan(app):
    async def cleanup():
        while True:
            await asyncio.to_thread(prune)
            await asyncio.sleep(3600)

    task = asyncio.create_task(cleanup())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Argus Engine", version="0.1.0", lifespan=lifespan)


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            return await self.app(scope, receive, send)
        size = 0
        chunks = []
        while True:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return
            size += len(msg.get("body", b""))
            if size > 512000:
                return await JSONResponse({"detail": "Request exceeds 512 KB"}, 413)(
                    scope, receive, send
                )
            chunks.append(msg.get("body", b""))
            if not msg.get("more_body"):
                break
        supplied = False

        async def replay():
            nonlocal supplied
            if supplied:
                return await receive()
            supplied = True
            return {
                "type": "http.request",
                "body": b"".join(chunks),
                "more_body": False,
            }

        return await self.app(scope, replay, send)


app.add_middleware(BodyLimit)


@app.exception_handler(RequestValidationError)
async def safe_validation(request, err):
    # Validation errors otherwise echo inputs, including rejected credential fields.
    return JSONResponse(
        {"detail": [{"loc": e["loc"], "msg": e["msg"]} for e in err.errors()]}, 422
    )


bearer = HTTPBearer(auto_error=False)


def identity(auth: HTTPAuthorizationCredentials | None = Depends(bearer)):
    with engine.connect() as db:
        info = (
            db.execute(
                select(keys).where(
                    keys.c.id == digest(auth.credentials if auth else "")
                )
            )
            .mappings()
            .first()
        )
        if not info:
            raise HTTPException(
                401,
                "Enter a valid workspace key",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return dict(info)


def runner(i=Depends(identity)):
    if i["role"] == "reader":
        raise HTTPException(403, "Runner or owner role required")
    return i


def owner(i=Depends(identity)):
    if i["role"] != "owner":
        raise HTTPException(403, "Owner role required")
    return i


@app.post("/api/judges")
async def register_judge(spec: Calibration, i=Depends(owner)):
    return await calibrate(i["workspace"], spec)


@app.get("/api/judges")
def judge_versions(i=Depends(identity)):
    with engine.connect() as db:
        return rows(
            db,
            scoped(judges, i["workspace"]).with_only_columns(
                judges.c.id, judges.c.created, judges.c.qualified
            ),
        )


@app.get("/api/judges/{id}")
def judge_report(id: str, i=Depends(identity)):
    with engine.connect() as db:
        row = lookup(db, judges, i["workspace"], id)
        return {"id": id, **unseal(row["payload"])}


@app.get("/health")
def health():
    with engine.connect() as db:
        db.execute(select(workspaces.c.id).limit(1))
    return {"status": "ok"}


@app.get("/api/workspace")
def workspace(i=Depends(identity)):
    with engine.connect() as db:
        ws = i["workspace"]
        w = dict(
            db.execute(select(workspaces).where(workspaces.c.id == ws)).mappings().one()
        )
        conns = rows(
            db,
            scoped(connections, ws).with_only_columns(
                connections.c.id, connections.c.provider, connections.c.models
            ),
        )
        for c in conns:
            c["models"] = json.loads(c["models"])
        ms = rows(db, scoped(models, ws).order_by(models.c.created.desc()))
        for m in ms:
            m["config"] = json.loads(m["config"])
        return {
            **w,
            "role": i["role"],
            "catalog": list(PROVIDERS),
            "tokenizers": installed(),
            "connections": conns,
            "models": ms,
        }


@app.post("/api/connections")
async def connect(data: Connection, i=Depends(owner)):
    found = await discover(data.provider, data.secret.get_secret_value())
    with engine.begin() as db:
        id = uid()
        db.execute(
            connections.insert().values(
                id=id,
                workspace=i["workspace"],
                provider=data.provider,
                secret=seal(data.secret.get_secret_value()),
                models=json.dumps(found),
            )
        )
        audit(db, i["workspace"], "provider.verified", id)
    return {"id": id, "models": found}


@app.post("/api/models")
def configure(data: ModelSpec, i=Depends(owner)):
    with engine.begin() as db:
        c = lookup(db, connections, i["workspace"], data.connection)
        if data.tokenizer_sha256:
            try:
                adapter(data.tokenizer_sha256)
            except (OSError, ValueError):
                raise HTTPException(
                    422, "Install and verify the tokenizer on the server first"
                )
        if data.name not in json.loads(c["models"]):
            raise HTTPException(422, "Select a model returned by provider discovery")
        id = uid()
        db.execute(
            models.insert().values(
                id=id,
                workspace=i["workspace"],
                connection=c["id"],
                name=data.name,
                created=time.time(),
                config=data.model_dump_json(exclude={"name", "connection"}),
            )
        )
        audit(db, i["workspace"], "model.version_created", id)
    return {"id": id}


@app.put("/api/settings")
def settings(data: Settings, i=Depends(owner)):
    with engine.begin() as db:
        db.execute(
            workspaces.update()
            .where(workspaces.c.id == i["workspace"])
            .values(**data.model_dump())
        )
        audit(db, i["workspace"], "settings.updated", i["workspace"])
    return {"saved": True}


@app.post("/api/keys")
def make_key(data: KeySpec, i=Depends(owner)):
    with engine.begin() as db:
        return {"key": issue(db, i["workspace"], data.role, data.label)}


@app.get("/api/keys")
def list_keys(i=Depends(owner)):
    with engine.connect() as db:
        return rows(db, scoped(keys, i["workspace"]).where(keys.c.role != "owner"))


@app.delete("/api/keys/{id}")
def revoke(id: str, i=Depends(owner)):
    with engine.begin() as db:
        k = lookup(db, keys, i["workspace"], id)
        if k["role"] == "owner":
            raise HTTPException(409, "Keep workspace owner access")
        db.execute(keys.delete().where(keys.c.id == id))
        audit(db, i["workspace"], "key.revoked", id)
    return {"revoked": True}


@app.get("/v1/models")
def listed(i=Depends(identity)):
    ms = workspace(i)["models"]
    return {
        "object": "list",
        "data": [
            {
                "id": m["id"],
                "object": "model",
                "created": int(m["created"]),
                "owned_by": "workspace",
                "provider_model": m["name"],
            }
            for m in ms
        ],
    }


@app.post("/v1/chat/completions")
async def completion(chat: Chat, i=Depends(runner)):
    ws = i["workspace"]
    original = chat
    if chat.policy_id:
        chat, rule = apply_policy(ws, chat)
    result = await execute(ws, chat, policy=original.policy_id)
    if chat.stream:
        return result
    obj, trace, _ = result
    if original.policy_id:
        monitor(
            ws,
            trace,
            original.policy_id,
            original,
            rule,
            obj["choices"][0]["message"]["content"],
        )
    return JSONResponse(
        obj, headers={"X-Argus-Trace": trace, "Cache-Control": "no-store"}
    )


@app.get("/api/traces")
def trace_list(i=Depends(identity)):
    with engine.connect() as db:
        return rows(
            db,
            scoped(traces, i["workspace"])
            .with_only_columns(
                *[
                    c
                    for c in traces.c
                    if c.name not in {"payload", "workspace", "reserved"}
                ]
            )
            .order_by(traces.c.created.desc())
            .limit(200),
        )


@app.get("/api/traces/{id}")
def trace(id: str, i=Depends(identity)):
    with engine.connect() as db:
        row = lookup(db, traces, i["workspace"], id)
        data = unseal(row.pop("payload"))
        cfg = json.loads(lookup(db, models, i["workspace"], row["model_id"])["config"])
        return {
            **row,
            **data,
            "workflow": timeline(i["workspace"], id),
            "analysis": inspect(
                Chat.model_validate(data["request"]), cfg.get("tokenizer_sha256")
            ),
        }


@app.post("/api/investigations/{id}")
def investigate(id: str, i=Depends(runner)):
    result = investigation(i["workspace"], id)
    with engine.begin() as db:
        for action in result["activity"]:
            audit(db, i["workspace"], action["tool"], id)
    return result


@app.post("/api/experiments")
async def start(
    spec: Experiment,
    i=Depends(runner),
    idempotency_key: str | None = Header(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"
    ),
):
    return await experiment(i["workspace"], spec, idempotency_key)


@app.get("/api/experiments")
def studies(i=Depends(identity)):
    with engine.connect() as db:
        return rows(
            db,
            scoped(experiments, i["workspace"])
            .with_only_columns(
                experiments.c.id,
                experiments.c.trace,
                experiments.c.status,
                experiments.c.created,
            )
            .order_by(experiments.c.created.desc()),
        )


@app.get("/api/experiments/{id}")
def study(id: str, i=Depends(identity)):
    with engine.connect() as db:
        r = lookup(db, experiments, i["workspace"], id)
        return {"id": id, "status": r["status"], **unseal(r["payload"])}


@app.post("/api/experiments/{id}/approve")
def approval(id: str, i=Depends(owner)):
    return approve(i["workspace"], id)


@app.get("/api/policies")
def versions(i=Depends(identity)):
    with engine.connect() as db:
        return rows(
            db,
            scoped(policies, i["workspace"])
            .with_only_columns(*[c for c in policies.c if c.name != "payload"])
            .order_by(policies.c.created.desc()),
        )


@app.post("/api/policies/{id}/rollback")
def rollback(id: str, i=Depends(owner)):
    with engine.begin() as db:
        lookup(db, policies, i["workspace"], id)
        db.execute(policies.update().where(policies.c.id == id).values(active=False))
        audit(db, i["workspace"], "policy.rolled_back", id)
    return {"active": False}


@app.get("/api/audit")
def activity(i=Depends(owner)):
    with engine.connect() as db:
        return rows(
            db,
            scoped(events, i["workspace"]).order_by(events.c.created.desc()).limit(100),
        )


@app.get("/api/overview")
def overview(i=Depends(identity)):
    with engine.connect() as db:
        rs = rows(
            db,
            scoped(traces, i["workspace"]).with_only_columns(
                traces.c.status,
                traces.c.elapsed_ms,
                traces.c.input_tokens,
                traces.c.output_tokens,
                traces.c.cost,
                traces.c.usage_source,
                traces.c.model_id,
            ),
        )
    durations = [r["elapsed_ms"] for r in rs if r["status"] == "ok"]
    from collections import Counter

    return {
        "requests": len(rs),
        "successful": len(durations),
        "errors": sum(r["status"] in ("error", "interrupted") for r in rs),
        "model_utilization": dict(Counter(r["model_id"] for r in rs)),
        "input_tokens": sum(r["input_tokens"] or 0 for r in rs),
        "output_tokens": sum(r["output_tokens"] or 0 for r in rs),
        "estimated_usage_requests": sum(r["usage_source"] == "estimated" for r in rs),
        "priced_requests": sum(r["cost"] is not None for r in rs),
        "estimated_micros": sum(r["cost"] or 0 for r in rs),
        "average_ms": sum(durations) / len(durations) if durations else None,
        "p95_ms": percentile(durations, 0.95),
    }


if Path("studio/out").is_dir():
    app.mount("/", StaticFiles(directory="studio/out", html=True), name="studio")
