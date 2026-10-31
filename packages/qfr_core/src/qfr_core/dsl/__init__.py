"""qfr-dsl/1: grammar, checks, canonical form, similarity and diff (PLAN Section 7)."""

from qfr_core.dsl.analysis import (
    CompiledExpression,
    DslAnalysis,
    DslLimits,
    DslValidation,
    compile_expression,
    declaration_mismatches,
    validate,
)
from qfr_core.dsl.canonical import canonical_hash, canonicalize, to_string
from qfr_core.dsl.diff import apply_diff, ast_diff
from qfr_core.dsl.parser import DslError, parse
from qfr_core.dsl.similarity import ast_similarity, originality

__all__ = [
    "CompiledExpression",
    "DslAnalysis",
    "DslError",
    "DslLimits",
    "DslValidation",
    "apply_diff",
    "ast_diff",
    "ast_similarity",
    "canonical_hash",
    "canonicalize",
    "compile_expression",
    "declaration_mismatches",
    "originality",
    "parse",
    "to_string",
    "validate",
]
