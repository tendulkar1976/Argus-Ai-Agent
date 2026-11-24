"""Scenario accounting. Monetary amounts returned in microdollars unless labeled otherwise."""

from decimal import Decimal


def rollout_cost(
    a, b, discovery_micros, overhead, assumptions, baseline_ms, candidate_ms, study_ms
):
    if assumptions is None or any(
        v is None
        for v in (a["inference_micros"], b["inference_micros"], discovery_micros)
    ):
        return None
    rate = Decimal(str(assumptions.host_usd_per_hour)) * 1_000_000 / 3_600_000
    fixed = Decimal(str(assumptions.other_micros_per_request))
    runs = Decimal(a["runs"])

    def host(ms):
        return rate * Decimal(str(ms))

    baseline = (Decimal(a["inference_micros"]) + host(baseline_ms)) / runs + fixed
    candidate = (
        Decimal(b["inference_micros"]) + host(candidate_ms + overhead["transform_ms"])
    ) / runs + fixed
    study = (
        Decimal(a["inference_micros"] + b["inference_micros"] + discovery_micros)
        + host(study_ms)
        + fixed * (2 * runs + 1)
        + Decimal(str(assumptions.other_study_micros))
    )
    volume = assumptions.rollout_calls
    return {
        "basis": "Scenario estimate using operator-allocated host time, provider rates and extra costs. Both arms use observed mean inference usage.",
        "assumptions": assumptions.model_dump(),
        "baseline_per_call_micros": float(baseline),
        "candidate_per_call_micros": float(candidate),
        "discovery_and_study_micros": float(study),
        "projected_net_saving_micros": float((baseline - candidate) * volume - study),
        "rollout_calls": volume,
        "host_time_includes_provider_wait": True,
    }
