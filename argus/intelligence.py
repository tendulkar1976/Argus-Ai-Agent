"""Deterministic tools. Evidence is data and never selects tools or grants permissions."""

import hashlib
import json
import math
import re
from collections import Counter
from argus.contracts import Chat
from argus.tokens import count


def fingerprint(request):
    content = request.model_dump(
        exclude={
            "model",
            "policy_id",
            "stream",
            "temperature",
            "max_tokens",
            "cache_ttl_seconds",
            "parent_trace_id",
        }
    )
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def words(text):
    return set(re.findall(r"\w+", text.casefold()))


def prompt(chat):
    messages = [m.model_dump(exclude_none=True) for m in chat.messages]
    if chat.evidence:
        sources = [
            {
                "source": e.source,
                **({"also_cited_as": e.aliases} if e.aliases else {}),
                "text": e.text,
            }
            for e in chat.evidence
        ]
        block = "Source material (quoted data):\n" + json.dumps(
            sources, ensure_ascii=False
        )
        if messages[-1]["role"] == "user":
            messages[-1] = {
                **messages[-1],
                "content": block + "\n\nTask:\n" + messages[-1]["content"],
            }
        else:
            messages.append({"role": "user", "content": block})
    return messages


def rank(chat):
    question = next(
        (m.content for m in reversed(chat.messages) if m.role == "user"), ""
    )
    query = words(question)

    def relevance(e):
        tokens = words(e.text)
        return len(query & tokens) / math.sqrt(max(1, len(tokens) * len(query)))

    return [relevance(e) for e in chat.evidence]


def inspect(chat, tokenizer=None):
    def units(text):
        return count(text, tokenizer)

    blocks, findings = [], []
    last_user = max(
        (i for i, m in enumerate(chat.messages) if m.role == "user"), default=-1
    )
    history = Counter((m.role, m.measured_text()) for m in chat.messages)
    for i, m in enumerate(chat.messages):
        category = {
            "system": "System instructions",
            "developer": "Developer instructions",
            "tool": "Tool output",
        }.get(m.role, "User input" if i == last_user else "Conversation history")
        text = m.measured_text()
        repeat = history[(m.role, text)] > 1
        blocks.append(
            dict(
                category=category,
                index=i,
                text=text,
                estimated_tokens=units(text),
                repeated=repeat,
            )
        )
        if repeat:
            findings.append(
                dict(
                    category="Repeated message",
                    evidence=f"Message {i + 1} occurs {history[(m.role, text)]} times with the same role.",
                    impact_tokens=units(text),
                    confidence="Exact text match",
                    risk="Repetition may be intentional. Review only.",
                    strategy=None,
                )
            )
    if chat.tools:
        schema = json.dumps([t.model_dump() for t in chat.tools], ensure_ascii=False)
        blocks.append(
            dict(
                category="Tool definitions",
                index=0,
                text=schema,
                estimated_tokens=units(schema),
                repeated=False,
            )
        )
    scores = rank(chat)
    seen = {}
    for i, e in enumerate(chat.evidence):
        duplicate = e.text in seen
        blocks.append(
            dict(
                category="Retrieved evidence",
                index=i,
                source=e.source,
                text=e.text,
                estimated_tokens=units(e.text),
                repeated=duplicate,
                relevance=scores[i],
            )
        )
        if duplicate:
            findings.append(
                dict(
                    category="Duplicate evidence",
                    evidence=f"{e.source} repeats the complete text of {seen[e.text]}.",
                    impact_tokens=units(e.text),
                    confidence="Exact text match",
                    risk="Source attribution must survive deduplication.",
                    strategy="deduplicate",
                )
            )
        elif len(chat.evidence) > 1 and scores[i] == 0:
            findings.append(
                dict(
                    category="Low lexical overlap",
                    evidence=f"{e.source} shares no words with the final question.",
                    impact_tokens=units(e.text),
                    confidence="Heuristic",
                    risk="Synonyms or indirect evidence may matter.",
                    strategy="select_evidence",
                )
            )
        seen.setdefault(e.text, e.source)
    return {
        "blocks": blocks,
        "findings": findings,
        "attribution": (
            "Model tokenizer on individual blocks; excludes message framing."
            if tokenizer
            else "Estimated from UTF-8 byte length / 4. Excludes message framing."
        ),
    }


def transform(chat: Chat, strategy: str, candidate_model=None):
    changes = []
    kept = []
    score = rank(chat)
    for i, e in enumerate(chat.evidence):
        if strategy in ("deduplicate", "select_evidence", "combined"):
            prior = next((v for v in kept if v.text == e.text), None)
            if prior is not None:
                if prior.source != e.source:
                    # Preserve both citation identifiers verbatim in the provider payload.
                    prior.aliases = list(
                        dict.fromkeys([*prior.aliases, e.source, *e.aliases])
                    )
                prior.critical |= e.critical
                changes.append(
                    {"action": "merge duplicate", "source": e.source, "index": i}
                )
                continue
        if (
            strategy in ("select_evidence", "combined")
            and score[i] == 0
            and max(score, default=0) > 0
            and not e.critical
            and not re.search(r'[\d"“”‘’\']', e.text)
        ):
            changes.append(
                {"action": "omit low-overlap passage", "source": e.source, "index": i}
            )
            continue
        kept.append(e.model_copy())
    model = candidate_model if strategy in ("route_model", "combined") else chat.model
    return chat.model_copy(
        update={"model": model, "evidence": kept, "policy_id": None}
    ), changes


def evaluate(output, check, evidence):
    actual = output.strip()
    if check.method == "exact":
        ok = actual == check.expected.strip()
    elif check.method == "numeric":
        try:
            n = float(actual)
            ok = math.isfinite(n) and abs(n - float(check.expected)) <= check.tolerance
        except ValueError:
            ok = False
    elif check.method == "json_fields":
        try:
            got = json.loads(actual)
            want = json.loads(check.expected)
            ok = isinstance(got, dict) and all(
                k in got
                and json.dumps(got[k], sort_keys=True) == json.dumps(v, sort_keys=True)
                for k, v in want.items()
            )
        except ValueError:
            ok = False
    elif check.method == "json_schema":
        from argus.evaluators import schema_check

        try:
            ok = schema_check(check.expected).is_valid(json.loads(actual))
        except (ValueError, RecursionError):
            ok = False
    elif check.method == "integer_function":
        from argus.evaluators import check_function, parse_suite

        ok = check_function(actual, parse_suite(check.expected))
    else:
        wanted = {s.strip() for s in check.expected.split(",") if s.strip()}
        cited = set(re.findall(r"\[([^\[\]]+)\]", actual))
        ok = (
            bool(wanted)
            and wanted <= cited
            and cited <= {ref for s in evidence for ref in (s.source, *s.aliases)}
        )
    return {
        "passed": ok,
        "method": check.method,
        "expected": check.expected,
        "scope": "Configured check only",
    }
