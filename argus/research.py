import json
import math
import statistics
import time
from sqlalchemy import select
from fastapi import HTTPException
from argus.config import seal, unseal
from argus.judges import evaluate_case, load_judge, judges
from argus.contracts import Chat, Experiment, Check
from argus.db import audit, digest, engine, lock, rows, scoped, uid
from argus.gateway import execute, lookup
from argus.intelligence import evaluate, fingerprint, inspect, transform
from argus.schema_v1 import experiments, models, policies, traces, workspaces, events


def percentile(values, q):
    return sorted(values)[max(0, math.ceil(q * len(values)) - 1)] if values else None


def investigation(ws, id):
    with engine.connect() as db:
        row = lookup(db, traces, ws, id)
        data = unseal(row["payload"])
        chat = Chat.model_validate(data["request"])
        cfg = json.loads(lookup(db, models, ws, chat.model)["config"])
        analysis = inspect(chat, cfg.get("tokenizer_sha256"))
        alternatives = []
        for model in rows(db, scoped(models, ws)):
            target = json.loads(model["config"])
            if model["id"] == chat.model or any(
                x is None
                for x in (
                    target["input_rate"],
                    target["output_rate"],
                    cfg["input_rate"],
                    cfg["output_rate"],
                )
            ):
                continue
            if (
                target["input_rate"] <= cfg["input_rate"]
                and target["output_rate"] <= cfg["output_rate"]
                and (target["input_rate"], target["output_rate"])
                != (cfg["input_rate"], cfg["output_rate"])
            ):
                alternatives.append(model["id"])
        from argus.workflows import timeline

        workflow = timeline(ws, id)
        analysis["findings"].extend(workflow["findings"])
        candidates = list(
            dict.fromkeys(f["strategy"] for f in analysis["findings"] if f["strategy"])
        )
        if alternatives:
            candidates.append("route_model")
        if alternatives and any(
            s in candidates for s in ("deduplicate", "select_evidence")
        ):
            candidates.append("combined")
        history = {s: {"accepted": 0, "evaluated": 0} for s in candidates}
        for past in rows(
            db,
            scoped(experiments, ws).where(
                experiments.c.status.in_(("eligible", "rejected"))
            ),
        ):
            report = unseal(past["payload"])
            if report["model"] == chat.model and report["strategy"] in history:
                counts = history[report["strategy"]]
                counts["evaluated"] += 1
                counts["accepted"] += past["status"] == "eligible"
        candidates.sort(
            key=lambda s: -(history[s]["accepted"] + 1) / (history[s]["evaluated"] + 2)
        )
    actions = [
        {"tool": "inspect_trace", "result": id},
        {
            "tool": "inspect_workflow",
            "result": f"{len(workflow['spans'])} linked calls",
        },
        {
            "tool": "analyze_context",
            "result": f"{len(analysis['blocks'])} blocks examined",
        },
        {
            "tool": "detect_repetition_and_rank_evidence",
            "result": f"{len(analysis['findings'])} findings",
        },
        {
            "tool": "compare_model_prices",
            "result": f"{len(alternatives)} lower-priced model versions",
        },
        {"tool": "rank_candidates", "result": history},
    ]
    return dict(
        trace_id=id,
        analysis=analysis,
        strategies=candidates,
        alternative_models=alternatives,
        activity=actions,
        history=history,
    )


def totals(items):
    times = [i["elapsed_ms"] for i in items]
    costs = [i["cost"] for i in items]
    return {
        "runs": len(items),
        "passed": sum(i["check"]["passed"] for i in items),
        "accuracy": statistics.mean(int(i["check"]["passed"]) for i in items),
        "input_tokens": sum(i["input_tokens"] for i in items),
        "output_tokens": sum(i["output_tokens"] for i in items),
        "usage_source": "provider"
        if all(i["usage_source"] == "provider" for i in items)
        else "includes estimates",
        "inference_micros": sum(costs) if all(c is not None for c in costs) else None,
        "p50_ms": percentile(times, 0.5),
        "p95_ms": percentile(times, 0.95),
        "latency_stdev_ms": statistics.stdev(times) if len(times) > 1 else None,
    }


async def experiment(ws, spec: Experiment, idempotency_key: str | None = None):
    study_start = time.monotonic()
    exp = digest(f"experiment/{ws}/{idempotency_key}") if idempotency_key else uid()
    with engine.begin() as db:
        if idempotency_key:
            # Serialize only admission. Provider calls run after this transaction commits.
            lock(db, ws)
            prior = (
                db.execute(scoped(experiments, ws).where(experiments.c.id == exp))
                .mappings()
                .first()
            )
            if prior:
                report = unseal(prior["payload"])
                if report["config"] != spec.model_dump():
                    raise HTTPException(
                        409,
                        "This approval key belongs to a different experiment configuration",
                    )
                return {"id": exp, "status": prior["status"], **report}
        source = lookup(db, traces, ws, spec.trace_id)
        original = Chat.model_validate(unseal(source["payload"])["request"])
        if source["status"] != "ok":
            raise HTTPException(422, "Choose a successful discovery trace")
        if spec.candidate_model:
            lookup(db, models, ws, spec.candidate_model)
        ids = set()
        calibrated = {}
        for c in spec.cases:
            sig = fingerprint(c.request)
            if sig in ids or sig == fingerprint(original):
                raise HTTPException(
                    422, "Use distinct held-out cases separate from the discovery trace"
                )
            if (
                c.request.model != original.model
                or c.request.stream
                or c.request.policy_id
                or c.request.cache_ttl_seconds
            ):
                raise HTTPException(
                    422,
                    "Use the discovery model for every baseline, without streaming or a policy",
                )
            if c.check.method == "rubric_judge":
                question = next(
                    (
                        m.content
                        for m in reversed(c.request.messages)
                        if m.role == "user"
                    ),
                    None,
                )
                if question is None:
                    raise HTTPException(422, "Judge evaluation needs a user task")
                calibrated[sig] = load_judge(ws, c.check.expected, question)
            ids.add(sig)
        report = {
            "version": "paired-v2",
            "strategy": spec.strategy,
            "model": original.model,
            "config": spec.model_dump(),
            "pairs": [],
            "cost_basis": "Versioned operator rates; estimated inference charges in USD microdollars.",
            "net_system_savings": None,
            "overhead": {
                "external_analysis_calls": 0,
                "external_evaluation_calls": 0,
                "local_processing_ms": 0.0,
                "transform_ms": 0.0,
                "infrastructure_cost": None,
            },
        }
        db.execute(
            experiments.insert().values(
                id=exp,
                workspace=ws,
                trace=spec.trace_id,
                created=time.time(),
                status="running",
                payload=seal(report),
            )
        )
        audit(db, ws, "experiment.approved_calls", exp)

    def save(status):
        with engine.begin() as db:
            db.execute(
                experiments.update()
                .where(experiments.c.id == exp)
                .values(status=status, payload=seal(report))
            )

    status = "failed"
    try:
        for repeat in range(spec.repeats):
            for index, case in enumerate(spec.cases):
                t = time.monotonic()
                candidate, changes = transform(
                    case.request, spec.strategy, spec.candidate_model
                )
                transform_ms = (time.monotonic() - t) * 1000
                report["overhead"]["transform_ms"] += transform_ms
                report["overhead"]["local_processing_ms"] += transform_ms
                pair = {"repeat": repeat + 1, "case": index + 1, "changes": changes}
                report["pairs"].append(pair)
                arms = [("baseline", case.request), ("candidate", candidate)]
                if (index + repeat) % 2:
                    arms.reverse()
                for arm, chat in arms:
                    obj, trace, metrics = await execute(ws, chat, kind=arm)
                    t = time.monotonic()
                    check = await evaluate_case(
                        ws,
                        case,
                        obj["choices"][0]["message"]["content"],
                        calibrated.get(fingerprint(case.request)),
                    )
                    if check["method"] == "rubric_judge":
                        report["overhead"]["external_evaluation_calls"] += 1
                    pair[arm] = {**metrics, "check": check, "trace": trace}
                    report["overhead"]["local_processing_ms"] += max(
                        0, (time.monotonic() - t) * 1000 - check.get("elapsed_ms", 0)
                    )
                    save("running")
        a, b = (
            totals([pair[k] for pair in report["pairs"]])
            for k in ("baseline", "candidate")
        )
        saving = (
            None
            if a["inference_micros"] is None or b["inference_micros"] is None
            else a["inference_micros"] - b["inference_micros"]
        )
        from argus.accounting import rollout_cost

        totals_ms = [
            sum(p[k]["elapsed_ms"] for p in report["pairs"])
            for k in ("baseline", "candidate")
        ]
        study_ms = (time.monotonic() - study_start) * 1000 + source["elapsed_ms"]
        judge_costs = [
            p[k]["check"]["cost"]
            for p in report["pairs"]
            for k in ("baseline", "candidate")
            if "cost" in p[k]["check"]
        ]
        verifier_cost = (
            sum(judge_costs) if all(v is not None for v in judge_costs) else None
        )
        report["overhead"]["evaluation_inference_micros"] = verifier_cost
        discovery_and_judges = (
            source["cost"] + verifier_cost
            if source["cost"] is not None and verifier_cost is not None
            else None
        )
        net = rollout_cost(
            a,
            b,
            discovery_and_judges,
            report["overhead"],
            spec.cost_assumptions,
            *totals_ms,
            study_ms,
        )
        report["rollout_cost_scenario"] = net
        conditions = {
            "evidence_sufficient": all(
                p[k]["check"].get("verdict") != "uncertain"
                for p in report["pairs"]
                for k in ("baseline", "candidate")
            ),
            "quality_threshold": b["accuracy"] >= spec.min_accuracy,
            "quality_preserved": b["accuracy"] >= a["accuracy"]
            and all(
                not p["baseline"]["check"]["passed"]
                or p["candidate"]["check"]["passed"]
                for p in report["pairs"]
            ),
            "latency_limit": spec.max_latency_ms is None
            or b["p95_ms"] <= spec.max_latency_ms,
            "provider_usage_available": a["usage_source"]
            == b["usage_source"]
            == "provider",
            "improved": {
                "net_cost": net is not None and net["projected_net_saving_micros"] > 0,
                "tokens": b["input_tokens"] + b["output_tokens"]
                < a["input_tokens"] + a["output_tokens"],
                "inference_cost": saving is not None and saving > 0,
                "latency": b["p95_ms"] < a["p95_ms"],
            }[spec.objective],
        }
        report.update(
            baseline=a,
            candidate=b,
            inference_saving_micros=saving,
            conditions=conditions,
        )
        status = "eligible" if all(conditions.values()) else "rejected"
    except HTTPException as err:
        report["error"] = err.detail
        if err.headers:
            report["failed_trace"] = err.headers.get("X-Argus-Trace")
    finally:
        save(status)
    return {"id": exp, "status": status, **report}


def approve(ws, id):
    with engine.begin() as db:
        lock(db, ws)
        item = lookup(db, experiments, ws, id)
        if item["status"] != "eligible":
            raise HTTPException(409, "Only quality-gated improvements can be approved")
        prior = (
            db.execute(scoped(policies, ws).where(policies.c.experiment == id))
            .mappings()
            .first()
        )
        if prior:
            return {"id": prior["id"], "active": prior["active"]}
        data = unseal(item["payload"])
        spec = Experiment.model_validate(data["config"])
        policy = uid()
        rules = {
            "strategy": spec.strategy,
            "candidate_model": spec.candidate_model,
            "checks": {
                fingerprint(c.request): c.check.model_dump() for c in spec.cases
            },
            "min_accuracy": spec.min_accuracy,
            "max_latency_ms": spec.max_latency_ms,
        }
        db.execute(
            policies.insert().values(
                id=policy,
                workspace=ws,
                experiment=id,
                model_id=data["model"],
                created=time.time(),
                active=True,
                payload=seal(rules),
            )
        )
        audit(db, ws, "policy.approved", policy)
        return {"id": policy, "active": True}


def apply_policy(ws, chat):
    with engine.connect() as db:
        p = lookup(db, policies, ws, chat.policy_id)
        if not p["active"] or p["model_id"] != chat.model or chat.stream:
            raise HTTPException(
                409,
                "Policy requires its original model, an active version and non-streaming execution",
            )
        rule = unseal(p["payload"])
    candidate, _ = transform(chat, rule["strategy"], rule["candidate_model"])
    return candidate, rule


def monitor(ws, trace, policy, chat, rule, output):
    with engine.begin() as db:
        info = lookup(db, traces, ws, trace)
        data = unseal(info["payload"])
        data["original_request"] = chat.model_dump()
        spec = rule["checks"].get(fingerprint(chat))
        check = (
            evaluate(output, Check.model_validate(spec), chat.evidence)
            if spec and spec["method"] != "rubric_judge"
            else None
        )
        too_slow = bool(
            rule["max_latency_ms"] and info["elapsed_ms"] > rule["max_latency_ms"]
        )
        data["monitor"] = {"quality": check, "latency_violation": too_slow}
        db.execute(
            traces.update().where(traces.c.id == trace).values(payload=seal(data))
        )
        if too_slow or (check and not check["passed"]):
            audit(db, ws, "policy.rollback_recommended", policy)


def prune():
    n = 0
    with engine.begin() as db:
        # Requests have a bounded gateway timeout. A stale open reservation remains charged.
        db.execute(
            traces.update()
            .where(traces.c.status == "running", traces.c.created < time.time() - 600)
            .values(status="interrupted")
        )
        db.execute(
            experiments.update()
            .where(
                experiments.c.status == "running",
                experiments.c.created < time.time() - 86400,
            )
            .values(status="interrupted")
        )
        for w in rows(db, select(workspaces)):
            lock(db, w["id"])
            cutoff = time.time() - 86400 * w["retention_days"]
            # Policies retain evaluation answers, so expire them along with the originating study.
            old = (
                scoped(experiments, w["id"])
                .where(experiments.c.created < cutoff)
                .with_only_columns(experiments.c.id)
            )
            db.execute(policies.delete().where(policies.c.experiment.in_(old)))
            for table in (experiments, traces, events, judges):
                n += db.execute(
                    table.delete().where(
                        table.c.workspace == w["id"], table.c.created < cutoff
                    )
                ).rowcount
    return n
