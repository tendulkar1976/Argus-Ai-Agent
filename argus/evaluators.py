"""Closed, bounded expression interpreter for integer-function benchmark cases.

No eval, imports, filesystem, network, arbitrary call targets or generated process.
"""

import ast
import operator
import json

OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}


def integer(value):
    if type(value) is not int or value.bit_length() > 128:
        raise ValueError("Integer outside evaluator domain")
    return value


def evaluate_expr(node, args):
    if isinstance(node, ast.Constant):
        return integer(node.value)
    if isinstance(node, ast.Name):
        return args[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -evaluate_expr(node.operand, args)
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        return integer(
            OPS[type(node.op)](
                evaluate_expr(node.left, args), evaluate_expr(node.right, args)
            )
        )
    raise ValueError("Unsupported expression")


def check_function(text, suite):
    if len(text) > 4096:
        return False
    if text.startswith("```python\n") and text.endswith("\n```"):
        text = text[10:-4]
    try:
        tree = ast.parse(text)
        if len(list(ast.walk(tree))) > 64 or len(tree.body) != 1:
            return False
        f = tree.body[0]
        if (
            not isinstance(f, ast.FunctionDef)
            or f.name != suite["function"]
            or len(f.body) != 1
            or not isinstance(f.body[0], ast.Return)
            or f.decorator_list
        ):
            return False
        if (
            f.args.defaults
            or f.args.kwonlyargs
            or f.args.vararg
            or f.args.kwarg
            or f.args.posonlyargs
        ):
            return False
        names = [a.arg for a in f.args.args]
        if f.returns or any(a.annotation for a in f.args.args):
            return False
        return all(
            len(test["args"]) == len(names)
            and evaluate_expr(
                f.body[0].value, dict(zip(names, map(integer, test["args"])))
            )
            == integer(test["returns"])
            for test in suite["tests"]
        )
    except (
        SyntaxError,
        ValueError,
        KeyError,
        TypeError,
        ArithmeticError,
        RecursionError,
    ):
        return False


def parse_suite(raw):
    suite = json.loads(raw)
    if (
        not isinstance(suite, dict)
        or not isinstance(suite.get("function"), str)
        or not suite["function"].isidentifier()
    ):
        raise ValueError("Supply a function name")
    trials = suite.get("tests")
    if not isinstance(trials, list) or not 1 <= len(trials) <= 100:
        raise ValueError("Supply 1–100 integer test vectors")
    for trial in trials:
        if (
            not isinstance(trial, dict)
            or not isinstance(trial.get("args"), list)
            or len(trial["args"]) > 16
        ):
            raise ValueError("Invalid function arguments")
        for n in [*trial["args"], trial.get("returns")]:
            integer(n)
    return suite


def schema_check(raw):
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    schema = json.loads(raw)
    allowed = {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "const",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "description",
        "title",
    }

    def validate(node, depth=0):
        if not isinstance(node, dict) or depth > 12 or not set(node) <= allowed:
            raise ValueError("Schema exceeds the supported bounded JSON Schema subset")
        for sub in node.get("properties", {}).values():
            validate(sub, depth + 1)
        for key in ("items", "additionalProperties"):
            if key in node and not isinstance(node[key], bool):
                validate(node[key], depth + 1)

    try:
        Draft202012Validator.check_schema(schema)
        validate(schema)
    except (SchemaError, AttributeError, TypeError) as err:
        raise ValueError("Invalid JSON schema") from err
    return Draft202012Validator(schema)
