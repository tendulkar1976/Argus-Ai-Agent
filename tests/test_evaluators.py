import json
import pytest
from argus.contracts import Chat, Check, Evidence
from argus.intelligence import transform, evaluate
from argus.gateway import price


def test_protected_content():
    chat = Chat(
        model="test",
        messages=[
            {"role": "system", "content": "Retain sources."},
            {"role": "user", "content": "Find the badge"},
        ],
        evidence=[
            {"source": "A", "text": "Find badge"},
            {"source": "B", "text": "A total of 19"},
            {"source": "C", "text": "Different vocabulary", "critical": True},
            {"source": "D", "text": "Unrelated"},
            {"source": "E", "text": "A total of 19"},
        ],
    )
    result, changes = transform(chat, "select_evidence")
    assert result.messages == chat.messages and [s.source for s in result.evidence] == [
        "A",
        "B",
        "C",
    ]
    assert result.evidence[1].aliases == ["E"] and len(changes) == 2


def test_code_and_schema_checks():
    spec = Check(
        method="integer_function",
        expected=json.dumps(
            {"function": "twice", "tests": [{"args": [-4], "returns": -8}]}
        ),
    )
    assert evaluate("def twice(x):\n    return x+x", spec, [])["passed"]
    assert not evaluate("def twice(x):\n    return print(x)", spec, [])["passed"]
    schema = Check(
        method="json_schema",
        expected='{"type":"object","properties":{"n":{"type":"integer"}},"required":["n"]}',
    )
    assert evaluate('{"n":4}', schema, [])["passed"]
    assert not evaluate('{"n":"4"}', schema, [])["passed"]
    with pytest.raises(ValueError):
        Check(
            method="json_schema", expected='{"$ref":"https://example.invalid/schema"}'
        )


def test_accounting_categories():
    cfg = {"input_rate": 4, "output_rate": 10, "cached_rate": 1}
    assert price(cfg, 10, 2, 4) == 48
    assert price({**cfg, "cached_rate": None}, 10, 2, 4) is None
    assert price({**cfg, "input_rate": None}, 10, 2) is None


def test_citations_are_checked_against_sources():
    rule = Check(method="citations", expected="A")
    source = [Evidence(source="A", text="relevant")]
    assert evaluate("Answer [A]", rule, source)["passed"]
    assert not evaluate("Answer [A] [B]", rule, source)["passed"]
