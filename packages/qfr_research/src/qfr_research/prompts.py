"""Versioned prompt templates (PLAN Section 11.5).

Templates are Markdown files under prompts/. The first line names the template id and
version (``<!-- qfr-prompt: engineer/1 -->``); placeholders are ``{{name}}``. Rendering
is deterministic and fails on a missing or unused value, and every rendered prompt is
trimmed to the context budget by dropping the oldest material of the long sections
first. The template id, the template hash and the rendered prompt's hash go into the
trace and the agent run.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

HEADER = re.compile(r"^<!-- qfr-prompt: ([a-z_]+/\d+) -->\n")
PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")
TRUNCATED = "[older material omitted to respect the context budget]"


class PromptError(ValueError):
    pass


@dataclass(frozen=True)
class Template:
    template_id: str
    body: str
    sha256: str

    @property
    def placeholders(self) -> set[str]:
        return set(PLACEHOLDER.findall(self.body))


@dataclass(frozen=True)
class RenderedPrompt:
    template_id: str
    template_sha256: str
    text: str
    truncated: list[str]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


class PromptLibrary:
    NAMES = (
        "rules",
        "supervisor",
        "hypothesis",
        "engineer",
        "mutation",
        "crossover",
        "strategy",
        "critic",
        "analyst",
        "interpretation_review",
    )

    def __init__(self, directory: Path) -> None:
        self.templates: dict[str, Template] = {}
        for name in self.NAMES:
            raw = (directory / f"{name}.md").read_text(encoding="utf-8")
            match = HEADER.match(raw)
            if match is None or not match.group(1).startswith(name + "/"):
                raise PromptError(f"{name}.md must start with its qfr-prompt header")
            body = raw[match.end() :].strip() + "\n"
            self.templates[name] = Template(
                match.group(1), body, hashlib.sha256(raw.encode()).hexdigest()
            )

    def get(self, name: str) -> Template:
        return self.templates[name]

    def render(
        self,
        name: str,
        values: dict[str, str],
        *,
        budget_chars: int,
        trimmable: tuple[str, ...] = (),
    ) -> RenderedPrompt:
        template = self.templates[name]
        values = dict(values)
        if "rules" in template.placeholders and "rules" not in values:
            values["rules"] = self.templates["rules"].body.strip()
        missing = template.placeholders - set(values)
        unused = set(values) - template.placeholders
        if missing or unused:
            raise PromptError(f"{name}: missing {sorted(missing)}, unused {sorted(unused)}")
        truncated: list[str] = []
        text = _fill(template.body, values)
        # Truncate the oldest material first: long sections hold items oldest first.
        for key in trimmable:
            if len(text) <= budget_chars:
                break
            excess = len(text) - budget_chars
            value = values[key]
            keep = max(0, len(value) - excess - len(TRUNCATED) - 1)
            values[key] = TRUNCATED + "\n" + value[len(value) - keep :] if keep else TRUNCATED
            truncated.append(key)
            text = _fill(template.body, values)
        if len(text) > budget_chars:
            raise PromptError(f"{name}: the prompt exceeds the context budget after trimming")
        return RenderedPrompt(template.template_id, template.sha256, text, truncated)


def _fill(body: str, values: dict[str, str]) -> str:
    return PLACEHOLDER.sub(lambda m: values[m.group(1)], body)
