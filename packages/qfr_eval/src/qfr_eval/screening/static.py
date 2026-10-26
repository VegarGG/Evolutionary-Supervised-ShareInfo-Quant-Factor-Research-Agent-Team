"""Admission checks are defense in depth, never a substitute for isolation."""

import ast

from qfr_core.contracts.enums import ReasonCode

from qfr_eval.screening.models import ScreeningExecutionPolicy


def check_source(
    source: bytes, policy: ScreeningExecutionPolicy, *, constrained_factor: bool
) -> ReasonCode | None:
    if len(source) > policy.source_bytes:
        return ReasonCode.COMPLEXITY_LIMIT
    try:
        tree = ast.parse(source.decode("utf-8"))
        nodes = list(ast.walk(tree))
    except (UnicodeError, SyntaxError, RecursionError):
        return ReasonCode.PARSE_ERROR
    if len(nodes) > policy.source_ast_nodes:
        return ReasonCode.COMPLEXITY_LIMIT
    for node in nodes:
        if isinstance(node, ast.Import):
            if any(
                alias.name.split(".")[0] not in policy.allowed_import_roots for alias in node.names
            ):
                return ReasonCode.FORBIDDEN_CONSTRUCT
        elif isinstance(node, ast.ImportFrom):
            if (
                node.level
                or not node.module
                or node.module.split(".")[0] not in policy.allowed_import_roots
                or any(alias.name == "*" for alias in node.names)
            ):
                return ReasonCode.FORBIDDEN_CONSTRUCT
        elif isinstance(node, ast.Name) and node.id in {"__builtins__", "__loader__", "__spec__"}:
            return ReasonCode.FORBIDDEN_CONSTRUCT
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") or node.attr in policy.forbidden_attributes:
                return ReasonCode.FORBIDDEN_CONSTRUCT
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in policy.forbidden_calls:
                return ReasonCode.FORBIDDEN_CONSTRUCT
            if any(
                k.arg == "allow_pickle"
                and not (isinstance(k.value, ast.Constant) and k.value.value is False)
                for k in node.keywords
            ):
                return ReasonCode.FORBIDDEN_CONSTRUCT
        if constrained_factor:
            # Imported model/strategy packages need their declared dates/keys.
            # The constrained Python-factor specialization has no such access.
            if isinstance(node, ast.Attribute) and node.attr in {
                "date",
                "code",
                "industry",
                "ticker",
            }:
                return ReasonCode.FORBIDDEN_CONSTRUCT
            if isinstance(node, ast.Constant) and node.value in (
                "date",
                "code",
                "industry",
                "ticker",
            ):
                return ReasonCode.FORBIDDEN_CONSTRUCT
    return None
