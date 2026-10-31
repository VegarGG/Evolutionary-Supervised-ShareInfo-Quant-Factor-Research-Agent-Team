"""The qfr-python/1 factor language: static rules shared by the registry, the evaluator
and the sandbox (PLAN Section 7.6 and P8.1).

A Python factor is a small module that defines `factor(...)`. Its parameters name the
panel fields it reads (the DSL's field names) and, optionally, `eligible`; it receives
each as a dates x instruments float matrix with no dates and no instrument ids, and
returns one matrix of the same shape. The module may import only numpy (as np) and math,
and may reach only the numpy and math names listed here. Everything else the static
check refuses: other imports, classes, try blocks, global state, attribute names that
start with an underscore, file and buffer methods, randomness and any name it cannot
resolve to its own definitions, its parameters, np, math or a short list of builtins.

These rules define the language, like the DSL's operator catalog, so research, the
registry and the evaluator can never disagree about them. Tunable limits (source length
and node count) come from the protocol's `python` section. The static check is the first
of several layers: the evaluator runs the code only in the eval-sandbox container, in a
fresh child process with resource limits and an audit hook (qfr_eval.sandbox_child).
"""

import ast
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from qfr_core.dsl.catalog import FIELD_COLUMNS

LANGUAGE: Final = "qfr-python/1"
ENTRYPOINT: Final = "factor"
ELIGIBLE: Final = "eligible"
# The import allow-list: the only import statements a module may contain.
IMPORTS: Final[dict[str, str]] = {"numpy": "np", "math": "math"}

# numpy names a factor may use: array creation, element-wise math, NaN-aware reductions,
# sorting and shape helpers. No I/O, no buffers, no random numbers (measurement is
# reproducible bit for bit), no ctypes and no submodules.
NUMPY_NAMES: Final[frozenset[str]] = frozenset(
    {
        # constants and types
        "nan", "inf", "pi", "e", "newaxis", "float64", "float32", "int64", "int32", "bool_",
        # creation
        "array", "asarray", "zeros", "ones", "full", "empty", "zeros_like", "ones_like",
        "full_like", "empty_like", "arange", "linspace", "eye", "copy",
        # element-wise
        "abs", "absolute", "sign", "log", "log1p", "log2", "log10", "exp", "expm1", "sqrt",
        "square", "power", "maximum", "minimum", "fmax", "fmin", "clip", "where", "isnan",
        "isfinite", "isinf", "nan_to_num", "floor", "ceil", "round", "rint", "trunc",
        "tanh", "sinh", "cosh", "arctan", "sin", "cos", "add", "subtract", "multiply",
        "divide", "true_divide", "mod", "fmod", "negative", "reciprocal", "logical_and",
        "logical_or", "logical_not", "logical_xor", "isclose", "greater", "less",
        "greater_equal", "less_equal", "equal", "not_equal", "heaviside",
        # reductions and statistics
        "sum", "mean", "std", "var", "median", "max", "min", "amax", "amin", "prod",
        "nansum", "nanmean", "nanstd", "nanvar", "nanmedian", "nanmax", "nanmin", "nanprod",
        "cumsum", "cumprod", "nancumsum", "nancumprod", "diff", "quantile", "nanquantile",
        "percentile", "nanpercentile", "count_nonzero", "any", "all", "argmax", "argmin",
        "nanargmax", "nanargmin", "corrcoef", "cov", "average", "ptp",
        # sorting and ranking
        "sort", "argsort", "searchsorted", "take_along_axis", "put_along_axis", "unique",
        # shapes
        "concatenate", "stack", "vstack", "hstack", "column_stack", "expand_dims", "squeeze",
        "reshape", "transpose", "swapaxes", "moveaxis", "broadcast_to", "broadcast_arrays",
        "atleast_2d", "roll", "flip", "tile", "repeat", "pad", "shape", "ndim", "size",
        "triu", "tril",
        # linear algebra on small blocks
        "dot", "matmul", "einsum", "outer", "inner",
        # rolling windows (numpy.lib.stride_tricks.sliding_window_view, exposed flat)
        "sliding_window_view",
    }
)  # fmt: skip
MATH_NAMES: Final[frozenset[str]] = frozenset(
    {
        "sqrt", "log", "log1p", "log2", "log10", "exp", "expm1", "fabs", "floor", "ceil",
        "trunc", "isnan", "isfinite", "isinf", "copysign", "tanh", "atan", "pow", "pi", "e",
        "inf", "nan", "fsum", "erf", "erfc", "hypot",
    }
)  # fmt: skip
# Builtins a factor may call. The sandbox gives the module exactly these.
BUILTINS: Final[frozenset[str]] = frozenset(
    {
        "abs", "min", "max", "sum", "len", "range", "float", "int", "bool", "round",
        "enumerate", "zip", "list", "tuple", "dict", "set", "sorted", "reversed", "any",
        "all", "map", "filter", "slice", "pow", "divmod", "True", "False", "None",
    }
)  # fmt: skip
# Attribute names refused on any object: file and buffer access, pickling, raw memory.
BANNED_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {
        "tofile", "dump", "dumps", "save", "savez", "savez_compressed", "savetxt", "load",
        "loadtxt", "fromfile", "frombuffer", "fromregex", "genfromtxt", "memmap", "ctypes",
        "ctypeslib", "lib", "f2py", "testing", "random", "os", "sys", "setflags",
        "getfield", "setfield", "tobytes", "data", "base", "flat", "format", "format_map",
        "mro",
        # frames and code objects: a generator or traceback is a way back to the caller
        "gi_frame", "gi_code", "gi_yieldfrom", "cr_frame", "cr_code", "ag_frame", "ag_code",
        "tb_frame", "tb_next", "f_back", "f_globals", "f_locals", "f_builtins", "f_code",
        "co_code", "func_globals",
    }
)  # fmt: skip
# Nodes the language does not have. Each is either useless for a factor or a way to
# hide state, catch the sandbox's refusals or reach the interpreter.
BANNED_NODES: Final[tuple[type[ast.AST], ...]] = (
    ast.ImportFrom, ast.ClassDef, ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith,
    ast.Await, ast.Global, ast.Nonlocal, ast.Try, ast.TryStar, ast.Raise, ast.With,
    ast.Yield, ast.YieldFrom, ast.JoinedStr, ast.FormattedValue, ast.Match, ast.Delete,
)  # fmt: skip
MAX_STRING_CHARS: Final = 64
# Nesting depth of the syntax tree. Deeper code is refused before any recursive pass over
# it (the checks, the canonical hash), so no input can exhaust the checker's stack.
MAX_DEPTH: Final = 64

Code = Literal["PARSE_ERROR", "FORBIDDEN_CONSTRUCT", "COMPLEXITY_LIMIT", "DECLARATION_MISMATCH"]


class PythonLimits(BaseModel):
    """Tunable limits from the protocol's `python` section."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    max_source_chars: int = Field(gt=0)
    max_ast_nodes: int = Field(gt=0)
    max_lookback_days: int = Field(ge=0)
    window_probe_dates: int = Field(ge=1)

    @classmethod
    def from_protocol(cls, protocol: Mapping[str, Any]) -> "PythonLimits":
        python = protocol.get("python")
        dsl = protocol.get("dsl")
        if not isinstance(python, dict) or not isinstance(dsl, dict):
            raise ValueError("the protocol has no python section")
        return cls(
            max_source_chars=int(python["max_source_chars"]),
            max_ast_nodes=int(python["max_ast_nodes"]),
            max_lookback_days=int(dsl["max_lookback_days"]),
            window_probe_dates=int(python["window_probe_dates"]),
        )


def public_python_limits(root: Path) -> PythonLimits | None:
    """The limits from the public protocol card (registry, front door). None when the
    shipped protocol has no python section: Python factors are then refused."""
    from qfr_core.config import public_cards

    protocol = public_cards(root)["protocol"]
    if not isinstance(protocol, dict) or not isinstance(protocol.get("python"), dict):
        return None
    return PythonLimits.from_protocol(protocol)


@dataclass(frozen=True)
class PythonError:
    code: Code
    message: str
    line: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "line": self.line}


@dataclass(frozen=True)
class PythonAnalysis:
    fields: list[str]  # Sorted field names the entrypoint reads (excluding eligible).
    uses_eligible: bool
    node_count: int
    canonical_hash: str
    parameters: list[str] = field(default_factory=list)  # The entrypoint's order.

    def as_dict(self) -> dict[str, Any]:
        return {
            "language": LANGUAGE,
            "fields": self.fields,
            "uses_eligible": self.uses_eligible,
            "node_count": self.node_count,
            "parameters": self.parameters,
        }


@dataclass(frozen=True)
class PythonCheck:
    analysis: PythonAnalysis | None
    errors: list[PythonError]

    @property
    def ok(self) -> bool:
        return self.analysis is not None and not self.errors


def _strip_docstrings(tree: ast.Module) -> ast.Module:
    clone = ast.parse(ast.unparse(tree))
    for node in ast.walk(clone):
        if isinstance(node, ast.Module | ast.FunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return clone


def canonical_hash(tree: ast.Module) -> str:
    """SHA-256 of the AST without docstrings: comments and formatting do not count."""
    dumped = ast.dump(_strip_docstrings(tree), annotate_fields=True, include_attributes=False)
    return hashlib.sha256(f"{LANGUAGE}\n{dumped}".encode()).hexdigest()


class _Checker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.errors: list[PythonError] = []
        self.defined: set[str] = {"np", "math"} | set(BUILTINS)
        self.loads: list[tuple[str, int]] = []

    def refuse(self, node: ast.AST, message: str) -> None:
        line = getattr(node, "lineno", None)
        self.errors.append(PythonError("FORBIDDEN_CONSTRUCT", message, line))

    def name(self, node: ast.AST, value: str) -> None:
        if value.startswith("_"):
            self.refuse(node, f"names may not start with an underscore: {value}")

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, BANNED_NODES):
            self.refuse(node, f"{type(node).__name__} is not part of qfr-python/1")
            return
        super().generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            expected = IMPORTS.get(alias.name)
            if expected is None or (alias.asname or alias.name) != expected:
                allowed = ", ".join(f"import {m} as {a}" for m, a in IMPORTS.items())
                self.refuse(node, f"only these imports are allowed: {allowed}")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.name(node, node.name)
        self.defined.add(node.name)
        args = node.args
        if args.vararg or args.kwarg or args.kwonlyargs or args.posonlyargs:
            self.refuse(node, "functions take plain positional parameters only")
        if node.decorator_list:
            self.refuse(node, "decorators are not allowed")
        if node.returns is not None or any(a.annotation is not None for a in args.args):
            self.refuse(node, "annotations are not allowed")
        for arg in args.args:
            self.name(arg, arg.arg)
            self.defined.add(arg.arg)
        for default in args.defaults:
            self.visit(default)
        for statement in node.body:
            self.visit(statement)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for arg in node.args.args:
            self.name(arg, arg.arg)
            self.defined.add(arg.arg)
        if node.args.vararg or node.args.kwarg or node.args.kwonlyargs:
            self.refuse(node, "lambdas take plain positional parameters only")
        self.visit(node.body)

    def visit_Name(self, node: ast.Name) -> None:
        self.name(node, node.id)
        if isinstance(node.ctx, ast.Store):
            if node.id in ("np", "math"):
                self.refuse(node, f"{node.id} may not be reassigned")
            self.defined.add(node.id)
        else:
            self.loads.append((node.id, node.lineno))

    def visit_arg(self, node: ast.arg) -> None:
        self.name(node, node.arg)
        self.defined.add(node.arg)

    def visit_keyword(self, node: ast.keyword) -> None:
        if node.arg is None:
            self.refuse(node, "**keyword unpacking is not allowed")
        else:
            self.name(node, node.arg)
        self.visit(node.value)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.name(node, node.attr)
        if node.attr in BANNED_ATTRIBUTES:
            self.refuse(node, f"attribute .{node.attr} is not allowed")
        if isinstance(node.value, ast.Name) and node.value.id == "np":
            if node.attr not in NUMPY_NAMES:
                self.refuse(node, f"np.{node.attr} is not in the numpy allow-list")
        if isinstance(node.value, ast.Name) and node.value.id == "math":
            if node.attr not in MATH_NAMES:
                self.refuse(node, f"math.{node.attr} is not in the math allow-list")
        if isinstance(node.ctx, ast.Store | ast.Del) and isinstance(node.value, ast.Name):
            if node.value.id in ("np", "math"):
                self.refuse(node, f"{node.value.id} may not be modified")
        self.visit(node.value)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, bytes):
            self.refuse(node, "bytes literals are not allowed")
        if isinstance(node.value, str) and len(node.value) > MAX_STRING_CHARS:
            self.refuse(node, f"string literals are at most {MAX_STRING_CHARS} characters")

    def finish(self) -> None:
        for name, line in self.loads:
            if name not in self.defined:
                self.errors.append(
                    PythonError("FORBIDDEN_CONSTRUCT", f"unknown or unavailable name: {name}", line)
                )


def _top_level(tree: ast.Module) -> list[PythonError]:
    errors = []
    body = tree.body
    for index, statement in enumerate(body):
        docstring = (
            index == 0
            and isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
        constant = (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Constant | ast.UnaryOp)
        )
        if not (docstring or constant or isinstance(statement, ast.Import | ast.FunctionDef)):
            errors.append(
                PythonError(
                    "FORBIDDEN_CONSTRUCT",
                    "the module holds only imports, functions and constant assignments",
                    statement.lineno,
                )
            )
    return errors


def _size(tree: ast.AST) -> tuple[int, int]:
    """Node count and nesting depth, without recursion."""
    nodes, deepest = 0, 0
    stack = [(tree, 1)]
    while stack:
        node, depth = stack.pop()
        nodes += 1
        deepest = max(deepest, depth)
        stack.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    return nodes, deepest


def check_source(source: str, limits: PythonLimits) -> PythonCheck:
    """Parse and check a qfr-python/1 module. Returns the analysis when it parses and
    names its fields, with every rule it breaks as an error."""
    if len(source) > limits.max_source_chars:
        return PythonCheck(
            None,
            [
                PythonError(
                    "COMPLEXITY_LIMIT",
                    f"the source has {len(source)} characters; the limit is "
                    f"{limits.max_source_chars}",
                )
            ],
        )
    try:
        tree = ast.parse(source, mode="exec", type_comments=False)
    except (SyntaxError, ValueError) as error:
        line = getattr(error, "lineno", None)
        return PythonCheck(None, [PythonError("PARSE_ERROR", "the module does not parse", line)])
    except (RecursionError, MemoryError):
        return PythonCheck(
            None, [PythonError("COMPLEXITY_LIMIT", "the module is nested too deeply")]
        )
    nodes, depth = _size(tree)
    if nodes > limits.max_ast_nodes or depth > MAX_DEPTH:
        return PythonCheck(
            None,
            [
                PythonError(
                    "COMPLEXITY_LIMIT",
                    f"the module has {nodes} syntax nodes nested {depth} deep; the limits "
                    f"are {limits.max_ast_nodes} and {MAX_DEPTH}",
                )
            ],
        )
    errors = _top_level(tree)
    checker = _Checker()
    checker.visit(tree)
    checker.finish()
    errors += checker.errors
    entry = [s for s in tree.body if isinstance(s, ast.FunctionDef) and s.name == ENTRYPOINT]
    if len(entry) != 1:
        errors.append(
            PythonError("FORBIDDEN_CONSTRUCT", f"define exactly one function {ENTRYPOINT}()")
        )
        return PythonCheck(None, errors)
    parameters = [a.arg for a in entry[0].args.args]
    unknown = [p for p in parameters if p != ELIGIBLE and p not in FIELD_COLUMNS]
    if unknown:
        errors.append(
            PythonError(
                "FORBIDDEN_CONSTRUCT",
                f"{ENTRYPOINT}() parameters must be field names or {ELIGIBLE}: {unknown}",
                entry[0].lineno,
            )
        )
    if entry[0].args.defaults:
        errors.append(
            PythonError("FORBIDDEN_CONSTRUCT", f"{ENTRYPOINT}() parameters take no defaults")
        )
    fields = sorted({p for p in parameters if p in FIELD_COLUMNS})
    if not fields:
        errors.append(PythonError("FORBIDDEN_CONSTRUCT", f"{ENTRYPOINT}() must read a field"))
    if len(parameters) != len(set(parameters)):
        errors.append(PythonError("FORBIDDEN_CONSTRUCT", "parameters must be distinct"))
    analysis = PythonAnalysis(
        fields=fields,
        uses_eligible=ELIGIBLE in parameters,
        node_count=nodes,
        canonical_hash=canonical_hash(tree),
        parameters=parameters,
    )
    return PythonCheck(analysis, errors)


def declaration_errors(
    analysis: PythonAnalysis, fields_used: list[str], max_lookback_days: int, limit: int
) -> list[PythonError]:
    """Declared fields must equal the entrypoint's field parameters; the declared lookback
    must respect the protocol cap (the evaluator checks it by the window probe)."""
    errors = []
    if sorted(set(fields_used)) != analysis.fields or len(fields_used) != len(set(fields_used)):
        errors.append(
            PythonError(
                "DECLARATION_MISMATCH",
                f"declared fields {sorted(fields_used)} differ from the parameters "
                f"{analysis.fields}",
            )
        )
    if max_lookback_days > limit:
        errors.append(
            PythonError(
                "COMPLEXITY_LIMIT",
                f"declared lookback {max_lookback_days} exceeds the limit {limit}",
            )
        )
    return errors
