"""Tenant-scoped span relationships for instrumented multi-call applications."""

import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import Column, ForeignKey, MetaData, String, Table, Index, select
from argus.db import engine
from argus.schema_v1 import metadata as initial, traces

schema = MetaData()
initial.tables["traces"].to_metadata(schema)
spans = Table(
    "workflow_spans",
    schema,
    Column("trace_id", ForeignKey("traces.id", ondelete="CASCADE"), primary_key=True),
    Column("workspace", String(64), nullable=False),
    Column("workflow_id", String(64), nullable=False),
    Column("parent_id", String(64)),
    Column("signature", String(64), nullable=False),
)
Index("workflow_spans_workspace", spans.c.workspace, spans.c.workflow_id)


def attach(db, ws, trace, parent, messages, model):
    root = trace
    if parent:
        root = db.scalar(
            select(spans.c.workflow_id).where(
                spans.c.workspace == ws, spans.c.trace_id == parent
            )
        )
        if not root:
            raise HTTPException(404, "Parent trace not found in this workspace")
    signature = hashlib.sha256(
        json.dumps([model, messages], sort_keys=True).encode()
    ).hexdigest()
    db.execute(
        spans.insert().values(
            trace_id=trace,
            workspace=ws,
            workflow_id=root,
            parent_id=parent,
            signature=signature,
        )
    )


def timeline(ws, trace):
    with engine.connect() as db:
        root = db.scalar(
            select(spans.c.workflow_id).where(
                spans.c.trace_id == trace, spans.c.workspace == ws
            )
        )
        if not root:
            return {"id": None, "spans": [], "findings": []}
        q = (
            select(
                spans.c.trace_id,
                spans.c.parent_id,
                spans.c.signature,
                traces.c.status,
                traces.c.kind,
                traces.c.created,
                traces.c.elapsed_ms,
                traces.c.input_tokens,
                traces.c.output_tokens,
                traces.c.cost,
            )
            .join(traces, traces.c.id == spans.c.trace_id)
            .where(
                spans.c.workflow_id == root,
                spans.c.workspace == ws,
                traces.c.workspace == ws,
            )
            .order_by(traces.c.created)
        )
        result = [dict(r) for r in db.execute(q).mappings()]
    seen = {}
    findings = []
    for r in result:
        signature = r.pop("signature")
        earlier = seen.get(signature)
        if (
            earlier
            and r["kind"] == "request"
            and earlier["status"] in ("error", "interrupted")
        ):
            findings.append(
                {
                    "category": "Repeated call after failure",
                    "evidence": f"Trace {r['trace_id']} repeated the model and messages of failed trace {earlier['trace_id']}.",
                    "impact_tokens": r["input_tokens"],
                    "confidence": "Observed request repetition",
                    "risk": "The retry may be necessary. Inspect provider failures before changing retry behavior.",
                    "strategy": None,
                }
            )
        seen[signature] = r
    return {"id": root, "spans": result, "findings": findings}
