"""Short-lived, opt-in reuse of successful deterministic direct completions."""

import hashlib
import json
import time
from sqlalchemy import Column, ForeignKey, MetaData, String, Table, Float, Index, select
from argus.config import seal, unseal
from argus.db import engine, lock, uid
from argus.schema_v1 import metadata as initial, traces

schema = MetaData()
# Resolve foreign keys without changing the frozen initial migration.
initial.tables["traces"].to_metadata(schema)
entries = Table(
    "cache_entries",
    schema,
    Column("trace", ForeignKey("traces.id", ondelete="CASCADE"), primary_key=True),
    Column("workspace", String(64), nullable=False),
    Column("signature", String(64), nullable=False),
    Column("created", Float, nullable=False),
)
Index("cache_lookup", entries.c.workspace, entries.c.signature, entries.c.created)


def signature(chat):
    data = chat.model_dump(exclude={"cache_ttl_seconds", "parent_trace_id"})
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def remember(ws, chat, trace):
    with engine.begin() as db:
        db.execute(
            entries.insert().values(
                trace=trace,
                workspace=ws,
                signature=signature(chat),
                created=time.time(),
            )
        )


def recall(ws, chat):
    start = time.monotonic()
    with engine.begin() as db:
        lock(db, ws)
        row = (
            db.execute(
                select(traces.c.id, traces.c.payload)
                .join(entries, entries.c.trace == traces.c.id)
                .where(
                    entries.c.workspace == ws,
                    traces.c.workspace == ws,
                    entries.c.signature == signature(chat),
                    entries.c.created >= time.time() - chat.cache_ttl_seconds,
                )
                .order_by(entries.c.created.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        if not row:
            return None
        from argus.gateway import rate_limit

        rate_limit(db, ws)
        data = unseal(row["payload"])
        obj = data["cached_response"]
        id = uid()
        obj["id"] = "argus-cache-" + id
        # The original provider usage applies to the origin trace only.
        obj["usage"] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        data.update(cache_origin=row["id"], raw_usage=None, request=chat.model_dump())
        data.pop("cached_response", None)
        elapsed = 1000 * (time.monotonic() - start)
        db.execute(
            traces.insert().values(
                id=id,
                workspace=ws,
                model_id=chat.model,
                created=time.time(),
                status="ok",
                kind="cache_hit",
                reserved=0,
                cost=0,
                elapsed_ms=elapsed,
                input_tokens=0,
                output_tokens=0,
                usage_source="cache",
                payload=seal(data),
            )
        )
        from argus.workflows import attach

        attach(db, ws, id, chat.parent_trace_id, data["sent_messages"], chat.model)
        return obj, id, {"elapsed_ms": elapsed}
