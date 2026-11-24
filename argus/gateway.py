import asyncio
import json
import os
import ssl
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING

import httpx
from fastapi import HTTPException
from sqlalchemy import select, func, case
from starlette.responses import StreamingResponse
from argus.config import PROVIDERS, seal, unseal
from argus.contracts import Chat
from argus.db import engine, lock, scoped, uid
from argus.schema_v1 import workspaces, connections, models, traces
from argus.intelligence import prompt
from argus.tokens import count


def transport():
    ca_file = os.getenv("ARGUS_PROVIDER_CA")
    verify = ssl.create_default_context(cafile=ca_file) if ca_file else True
    return httpx.AsyncClient(
        verify=verify,
        timeout=httpx.Timeout(45, connect=5),
        follow_redirects=False,
        trust_env=False,
    )


def lookup(db, table, ws, id):
    item = db.execute(scoped(table, ws).where(table.c.id == id)).mappings().first()
    if not item:
        raise HTTPException(404, "Workspace resource not found")
    return dict(item)


async def discover(provider, key):
    if provider not in PROVIDERS:
        raise HTTPException(422, "Choose a provider from the server catalog")
    try:
        async with asyncio.timeout(20), transport() as client:
            r = await client.get(
                PROVIDERS[provider] + "/models",
                headers={"Authorization": "Bearer " + key},
            )
            r.raise_for_status()
            items = sorted(
                {m["id"] for m in r.json()["data"] if isinstance(m.get("id"), str)}
            )
            if not items:
                raise ValueError
            return items
    except (httpx.HTTPError, TimeoutError, KeyError, TypeError, ValueError):
        raise HTTPException(
            502,
            "Model discovery failed. Check the provider, credential and model permissions.",
        )


def price(config, sent, received, cached=0, reserve=False):
    if config["input_rate"] is None or config["output_rate"] is None:
        return None
    if cached and config["cached_rate"] is None:
        return None
    rate = Decimal(str(config["input_rate"]))
    cache = Decimal(str(config["cached_rate"] or 0))
    if reserve:
        rate = max(rate, cache)
    micros = (
        (sent - cached) * rate
        + cached * cache
        + received * Decimal(str(config["output_rate"]))
    )
    return int(micros.to_integral_value(rounding=ROUND_CEILING))


def rate_limit(db, ws):
    recent = db.scalar(
        select(func.count())
        .select_from(traces)
        .where(traces.c.workspace == ws, traces.c.created > time.time() - 60)
    )
    if recent >= 30:
        raise HTTPException(429, "Workspace per-minute limit reached")


def reserve(ws, chat, kind, policy):
    with engine.begin() as db:
        lock(db, ws)
        m = lookup(db, models, ws, chat.model)
        conn = lookup(db, connections, ws, m["connection"])
        cfg = json.loads(m["config"])
        if (
            chat.tools or any(m.tool_calls or m.role == "tool" for m in chat.messages)
        ) and not cfg.get("supports_tools"):
            raise HTTPException(
                422, "This model version has no configured tool capability"
            )
        if chat.tools and (kind != "request" or policy or chat.cache_ttl_seconds):
            raise HTTPException(
                422, "Tool-enabled executions require a direct uncached request"
            )
        messages = prompt(chat)
        if (
            chat.max_tokens > cfg["output_limit"]
            or sum(
                count(message_text(x), cfg.get("tokenizer_sha256")) for x in messages
            )
            > cfg["input_limit"]
        ):
            raise HTTPException(422, "Request exceeds configured model limits")
        cap = price(cfg, cfg["input_limit"], chat.max_tokens, reserve=True)
        w = db.execute(select(workspaces).where(workspaces.c.id == ws)).mappings().one()
        today = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .timestamp()
        )
        daily = traces.c.created >= today

        def trace_count(filter):
            return db.scalar(
                select(func.count())
                .select_from(traces)
                .where(traces.c.workspace == ws, filter)
            )

        rate_limit(db, ws)
        if trace_count(daily & (traces.c.kind != "cache_hit")) >= w["day_calls"]:
            raise HTTPException(429, "Workspace request limit reached")
        if w["day_micros"] is not None:
            # Unpriced or unresolved requests cannot be assumed free.
            accounting = case(
                (traces.c.usage_source == "estimated", traces.c.reserved),
                else_=func.coalesce(traces.c.cost, traces.c.reserved),
            )
            used = (
                db.scalar(
                    select(func.sum(accounting)).where(traces.c.workspace == ws, daily)
                )
                or 0
            )
            if (
                cap is None
                or trace_count(daily & accounting.is_(None))
                or used + cap > w["day_micros"]
            ):
                raise HTTPException(
                    402,
                    "USD ceiling requires complete pricing and sufficient remaining budget",
                )
        trace = uid()
        payload = {
            "request": chat.model_dump(),
            "sent_messages": messages,
            "pricing_version": m["id"],
            "requested_model": m["name"],
        }
        db.execute(
            traces.insert().values(
                id=trace,
                workspace=ws,
                model_id=m["id"],
                created=time.time(),
                status="running",
                kind=kind,
                policy=policy,
                reserved=cap,
                payload=seal(payload),
            )
        )
        from argus.workflows import attach

        attach(db, ws, trace, chat.parent_trace_id, messages, chat.model)
        body = {
            "model": m["name"],
            "messages": messages,
            cfg["output_parameter"]: chat.max_tokens,
            "stream": chat.stream,
        }
        if chat.tools:
            body["tools"] = [t.model_dump() for t in chat.tools]
        if chat.temperature is not None:
            body["temperature"] = chat.temperature
        if chat.stream and cfg["stream_usage"]:
            body["stream_options"] = {"include_usage": True}
        return (
            trace,
            payload,
            cfg,
            PROVIDERS[conn["provider"]] + "/chat/completions",
            unseal(conn["secret"]),
            body,
        )


def message_text(message):
    return (message.get("content") or "") + (
        json.dumps(message["tool_calls"], ensure_ascii=False)
        if message.get("tool_calls")
        else ""
    )


def record(trace, payload, cfg, start, status, output="", usage=None, metadata=None):
    data = {"status": status, "elapsed_ms": round((time.monotonic() - start) * 1000, 2)}
    payload.update(output=output, raw_usage=usage, provider_metadata=metadata or {})
    if status == "ok":
        usage = usage if isinstance(usage, dict) else {}
        inp, out = usage.get("prompt_tokens"), usage.get("completion_tokens")
        native = all(type(n) is int and n >= 0 for n in (inp, out))
        if not native:
            inp = sum(
                count(message_text(m), cfg.get("tokenizer_sha256"))
                for m in payload["sent_messages"]
            )
            for tool in payload["request"].get("tools", []):
                inp += count(
                    json.dumps(tool, ensure_ascii=False), cfg.get("tokenizer_sha256")
                )
            out = count(output, cfg.get("tokenizer_sha256"))
        details = usage.get("prompt_tokens_details") or {}
        cached = details.get("cached_tokens", 0)
        unsupported = any(
            v for k, v in details.items() if k not in {"cached_tokens", "text_tokens"}
        )
        unsupported |= any(
            v
            for k, v in (usage.get("completion_tokens_details") or {}).items()
            if k in {"audio_tokens", "rejected_prediction_tokens"}
        )
        estimate = (
            price(cfg, inp, out, cached)
            if type(cached) is int and 0 <= cached <= inp and not unsupported
            else None
        )
        data.update(
            input_tokens=inp,
            output_tokens=out,
            usage_source="provider" if native else "estimated",
            cost=estimate,
        )
    with engine.begin() as db:
        db.execute(
            traces.update()
            .where(traces.c.id == trace)
            .values(payload=seal(payload), **data)
        )
    return data


def meta(obj):
    return {
        k: obj[k]
        for k in ("id", "model", "system_fingerprint", "created", "service_tier")
        if k in obj
    }


async def execute(ws, chat: Chat, kind="request", policy=None):
    from argus.cache import recall, remember

    cache_enabled = kind == "request" and bool(chat.cache_ttl_seconds)
    if cache_enabled:
        hit = recall(ws, chat)
        if hit:
            return hit
    start = time.monotonic()
    trace, payload, cfg, url, key, body = reserve(ws, chat, kind, policy)
    headers = {"Authorization": "Bearer " + key}
    client = transport()
    try:
        req = client.build_request("POST", url, headers=headers, json=body)
        async with asyncio.timeout(65):
            response = await client.send(req, stream=chat.stream)
        response.raise_for_status()
        if chat.stream:

            async def chunks():
                parts = []
                usage = None
                metadata = {}
                status = "interrupted"
                size = 0
                try:
                    async with asyncio.timeout(90):
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                status = "ok"
                                break
                            obj = json.loads(data)
                            if obj.get("error"):
                                raise ValueError
                            metadata.update(meta(obj))
                            if obj.get("usage"):
                                usage = obj["usage"]
                            for c in obj.get("choices", []):
                                delta = c.get("delta", {})
                                parts.append(message_text(delta))
                                if delta.get("tool_calls"):
                                    payload.setdefault(
                                        "provider_tool_call_deltas", []
                                    ).extend(delta["tool_calls"])
                            size += len(data)
                            if size > 4000000:
                                raise ValueError
                            yield "data: " + data + "\n\n"
                    if status != "ok":
                        raise ValueError
                except (ValueError, httpx.HTTPError, TimeoutError, TypeError, KeyError):
                    status = "error"
                    yield 'data: {"error":{"message":"Incomplete provider stream"}}\n\n'
                finally:
                    record(
                        trace,
                        payload,
                        cfg,
                        start,
                        status,
                        "".join(parts),
                        usage,
                        metadata,
                    )
                    await response.aclose()
                    await client.aclose()
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                chunks(),
                media_type="text/event-stream",
                headers={"X-Argus-Trace": trace},
            )
        obj = response.json()
        message = obj["choices"][0]["message"]
        output = message.get("content")
        if message.get("tool_calls"):
            payload["provider_tool_calls"] = message["tool_calls"]
            output = message_text(message)
        if not isinstance(output, str):
            raise ValueError
        if cache_enabled:
            payload["cached_response"] = obj
        metrics = record(
            trace, payload, cfg, start, "ok", output, obj.get("usage"), meta(obj)
        )
        if cache_enabled:
            remember(ws, chat, trace)
        await client.aclose()
        return obj, trace, metrics
    except (
        httpx.HTTPError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        IndexError,
        TimeoutError,
        asyncio.CancelledError,
    ) as err:
        record(
            trace,
            payload,
            cfg,
            start,
            "interrupted" if isinstance(err, asyncio.CancelledError) else "error",
        )
        await client.aclose()
        if isinstance(err, asyncio.CancelledError):
            raise
        raise HTTPException(
            502,
            "Provider execution failed. Inspect the trace and verify model parameters.",
            headers={"X-Argus-Trace": trace},
        )
