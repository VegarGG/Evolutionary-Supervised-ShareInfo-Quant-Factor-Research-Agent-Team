"""Bounded case views and source-derived count checks, not general prose verification."""

import hashlib
import json
import math
import re


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def reference(resource_id, value, page_chars):
    raw = value if isinstance(value, str) else encoded(value).decode()
    return {
        "resource_id": resource_id,
        "sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "characters": len(raw),
        "pages": max(1, math.ceil(len(raw) / page_chars)),
    }


def page(resource_id, value, number, page_chars):
    ref = reference(resource_id, value, page_chars)
    if type(number) is not int or not 0 <= number < ref["pages"]:
        raise ValueError("page outside the immutable resource")
    raw = value if isinstance(value, str) else encoded(value).decode()
    return {
        **ref,
        "page": number,
        "text": raw[number * page_chars : (number + 1) * page_chars],
        "instruction": "Concatenate text pages in order for exact source/JSON; no ellipsis added.",
    }


def count_facts(rows, spec, calculated):
    window = max(spec.lookback, spec.volatility_window or 0)
    result = {}
    for symbol in sorted({r["symbol"] for r in rows}):
        own = [r for r in calculated if r["symbol"] == symbol]
        warmup = sum(r["excluded_reason"] == "insufficient_past_observations" for r in own)
        eligible = sum(r["score"] is not None for r in own)
        result[symbol] = {
            "observed_closes": len(own),
            "closes_required_per_signal": window + 1,
            "warmup_exclusions": warmup,
            "additional_exclusions": len(own) - warmup - eligible,
            "eligible_signals": eligible,
            "signals_with_next_observed_close": sum(
                r["score"] is not None and r["execution_date"] is not None for r in own
            ),
        }
    return result


def prose_checks(texts, facts):
    """Reject recognized false count claims. Unrecognized language still needs review."""
    issues = []
    for field, original in texts.items():
        text = original.lower().replace("−", "-").replace("–", "-")
        # Explicit arithmetic chains, including the inclusive-window +1 correction.
        pattern = r"(?<![\w.])(\d+(?:\s*[+-]\s*\d+)+)\s*=\s*(\d+)(?![\w.])"
        for match in re.finditer(pattern, text):
            terms = re.findall(r"[+-]?\s*\d+", match[1])
            total = sum(int(term.replace(" ", "")) for term in terms)
            if total != int(match[2]):
                issues.append({"field": field, "code": "false_count_equation", "text": match[0]})
        # The recorded '59 observations ... minus 6 ... leaves 54' false pass.
        verbal = (
            r"\b(\d+)\s+(?:observations|closes)[^.;\n]{0,100}?\bminus\s+(\d+)\b"
            r"([^.;\n]{0,100}?)\b(?:leaves|equals|yields)\s+(\d+)\b"
        )
        for match in re.finditer(verbal, text):
            plus = re.search(r"(?:plus|\+)\s*(\d+)", match[3])
            total = int(match[1]) - int(match[2]) + (int(plus[1]) if plus else 0)
            if total != int(match[4]):
                issues.append(
                    {"field": field, "code": "false_window_subtraction", "text": match[0]}
                )
        # A next observed price is not evidence that an order can be filled.
        # Catch the recorded count-to-tradability overstatement, not all prose.
        execution_claim = (
            r"\b(?:only\s+)?\d+(?:\s+of\s+\d+)?\s+(?:eligible\s+)?signals?\b"
            r"[^.;\n]{0,60}?\b(?:are|is)\s+(?:actually\s+)?"
            r"(?:executable|tradable|tradeable)\b"
        )
        for match in re.finditer(execution_claim, text):
            issues.append(
                {
                    "field": field,
                    "code": "observed_close_is_not_tradability",
                    "text": match[0],
                }
            )
        if any(f["warmup_exclusions"] for f in facts.values()):
            for sentence in re.split(r"[.;\n]", text):
                if (
                    re.search(r"\b(?:return|score|signal)\b", sentence)
                    and re.search(r"\b(?:defined|available|eligible|calculable)\b", sentence)
                    and re.search(
                        r"\b(?:every|all)\s+observed\s+(?:date|dates|day|days)\b", sentence
                    )
                    and not re.search(
                        r"\b(?:not|never|cannot|incorrect|false|after|following|except|once|"
                        r"with sufficient)\b",
                        sentence,
                    )
                ):
                    issues.append(
                        {"field": field, "code": "unqualified_all_dates", "text": sentence.strip()}
                    )
    return {
        "recognized_prose_ok": not issues,
        "issues": issues,
        "limits": "Checks explicit count equations, the recognized window-subtraction grammar, "
        "unqualified every-observed-date claims and the recorded numeric signal-count "
        "claim of executability/tradability. Not a general semantic proof.",
    }


def revision_texts(body):
    result = {k: body.get(k, "") for k in ("hypothesis", "rationale")}
    for key in ("limitations", "issue_resolutions"):
        result.update({f"{key}[{i}]": text for i, text in enumerate(body.get(key, []))})
    result.update({f"decisions[{i}]": d["reason"] for i, d in enumerate(body.get("decisions", []))})
    return result
