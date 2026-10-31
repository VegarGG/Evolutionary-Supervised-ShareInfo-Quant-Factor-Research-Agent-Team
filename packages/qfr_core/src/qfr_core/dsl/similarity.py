"""AST similarity (PLAN Section 7.5).

Similarity is the size of the largest common subtree divided by the node count of the
larger tree. A common subtree is matched top-down from a pair of nodes with equal
labels and arity; children are matched position by position, and the two children of
a commutative operator may also be matched crosswise. Matching is memoized.
"""

from collections.abc import Iterable

from qfr_core.dsl.ast import BinOp, Call, Node, children, label, size, walk
from qfr_core.dsl.catalog import COMMUTATIVE_BINARY, OPERATORS


def _commutative(node: Node) -> bool:
    if isinstance(node, BinOp):
        return node.op in COMMUTATIVE_BINARY
    return isinstance(node, Call) and OPERATORS[node.name].commutative


def largest_common_subtree(a: Node, b: Node) -> int:
    memo: dict[tuple[int, int], int] = {}

    def match(x: Node, y: Node) -> int:
        key = (id(x), id(y))
        if key in memo:
            return memo[key]
        xs, ys = children(x), children(y)
        if label(x) != label(y) or len(xs) != len(ys):
            result = 0
        elif _commutative(x) and len(xs) == 2:
            straight = match(xs[0], ys[0]) + match(xs[1], ys[1])
            crossed = match(xs[0], ys[1]) + match(xs[1], ys[0])
            result = 1 + max(straight, crossed)
        else:
            result = 1 + sum(match(cx, cy) for cx, cy in zip(xs, ys, strict=True))
        memo[key] = result
        return result

    return max(match(x, y) for x in walk(a) for y in walk(b))


def ast_similarity(a: Node, b: Node) -> float:
    return largest_common_subtree(a, b) / max(size(a), size(b))


def originality(candidate: Node, others: Iterable[Node]) -> float:
    """1 minus the maximum similarity against the library and the population."""
    return 1.0 - max((ast_similarity(candidate, other) for other in others), default=0.0)
