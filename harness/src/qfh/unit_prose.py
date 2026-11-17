"""Check a deliberately limited grammar of explicit raw/target unit claims.

This is not general language verification. Recognized equations must agree with
the source-derived scale even inside a historical quote: obsolete equalities belong
in the immutable parent, not the current explanation. Unknown phrasing still needs
independent semantic review. No model code is evaluated.
"""

import re
from decimal import Decimal, InvalidOperation
from fractions import Fraction

RAW = r"(?:raw(?:\s+stored)?(?:\s+ratio)?|uncorrected(?:\s+stored)?\s+ratio)"
TARGET = r"(?:(?:intended|target)(?:\s+dimensionless)?(?:\s+earnings)?(?:\s+yield|\s+ratio)?)"
ALIAS = rf"(?:{RAW}|{TARGET})"
NUMBER = r"(?:10\s*\^\s*\(?[+-]?\d+\)?|\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?(?:\s*/\s*\d[\d,]*)?)"
EQUALITY = re.compile(
    rf"\b(?P<left>{ALIAS})\s*(?:equals|is equal to|=)\s*(?:the\s+)?"
    rf"(?P<right>{ALIAS})\s*(?:times|multiplied by|\*)\s*\(?\s*(?P<factor>{NUMBER})",
    re.IGNORECASE,
)
DIRECTION = re.compile(
    rf"\b(?P<subject>{RAW}|initial[^.;\n]{{0,100}}claim)\s+"
    rf"(?P<direction>overstate[sd]?|understate[sd]?)\s+(?:the\s+)?"
    rf"(?:ratio(?:\s+level)?|{TARGET})"
    rf"(?:\s+by\s+(?:exactly\s+)?(?:a\s+)?factor\s+of\s+(?P<factor>{NUMBER}))?",
    re.IGNORECASE,
)


def multiplier(text):
    text = re.sub(r"[\s,()]", "", text)
    if len(text) > 1000:
        raise ValueError("unit multiplier is too long")
    if text.startswith("10^"):
        exponent = int(text[3:])
        if abs(exponent) > 12:
            raise ValueError("unit exponent outside source scale bounds")
        return Fraction(10) ** exponent
    # Check exponent notation before Fraction can allocate huge integers. Decimal
    # preserves the written value without float rounding or exponent expansion.
    if "/" not in text:
        try:
            bounded = Decimal(text)
            if not Decimal("1e-12") <= bounded <= Decimal("1e12"):
                raise ValueError("unit multiplier outside source scale bounds")
        except InvalidOperation as error:
            raise ValueError("invalid unit multiplier") from error
        value = Fraction(bounded)
    else:
        value = Fraction(text)
    if not 0 < value <= 10**12 or value.denominator > 10**12:
        raise ValueError("unit multiplier outside source scale bounds")
    return value


def texts(value, pointer=""):
    if isinstance(value, str):
        yield pointer, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from texts(item, f"{pointer}/{index}")
    elif isinstance(value, dict):
        for name, item in value.items():
            yield from texts(item, pointer + "/" + name.replace("~", "~0").replace("/", "~1"))


def relationships(output, target_per_raw: Fraction):
    checks = []

    def kind(alias):
        return "raw" if re.match(RAW, alias, re.IGNORECASE) else "target"

    for path, original in texts(output):
        text = original.replace("−", "-")
        for match in EQUALITY.finditer(text):
            left, right = kind(match["left"]), kind(match["right"])
            expected = (
                Fraction(1)
                if left == right
                else target_per_raw
                if left == "target"
                else 1 / target_per_raw
            )
            try:
                actual = multiplier(match["factor"])
            except (ValueError, ZeroDivisionError):
                actual = None
            checks.append(
                {
                    "path": path,
                    "quote": original[match.start() : match.end()],
                    "kind": "explicit_equality",
                    "passed": actual == expected,
                    "expected": f"{left} = {right} * ({expected.numerator}/{expected.denominator})",
                }
            )
        for match in DIRECTION.finditer(text):
            raw_per_target = 1 / target_per_raw
            expected = (
                "overstate"
                if raw_per_target > 1
                else "understate"
                if raw_per_target < 1
                else "equal"
            )
            direction_ok = match["direction"].lower().startswith(expected)
            factor_ok = True
            if match["factor"]:
                try:
                    factor_ok = multiplier(match["factor"]) == max(raw_per_target, target_per_raw)
                except (ValueError, ZeroDivisionError):
                    factor_ok = False
            checks.append(
                {
                    "path": path,
                    "quote": original[match.start() : match.end()],
                    "kind": "magnitude_direction",
                    "passed": direction_ok and factor_ok,
                    "expected": f"Raw magnitude must {expected} target magnitude; "
                    f"raw/target scale = {raw_per_target.numerator}/{raw_per_target.denominator}. "
                    "Zero remains zero and this is not an ordering claim for negative values.",
                }
            )
    return checks
