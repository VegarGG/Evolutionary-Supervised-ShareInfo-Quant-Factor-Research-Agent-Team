"""Versioned YAML configuration; loading is offline and does not authorize execution."""

from collections.abc import Hashable
from pathlib import Path
from typing import Literal, Self, cast

import yaml
from pydantic import BaseModel, JsonValue, PositiveInt, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from qfr_core.contracts.base import Contract, Text


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QFR_", extra="ignore", frozen=True)
    config_root: Path = Path("configs")


class ConfigDocument(Contract):
    schema_version: Literal["1"]
    kind: Literal["protocol", "release_policy", "quota", "charter", "job"]
    profile: Literal["pilot_industry_v1", "stock_daily_v1"]
    revision: PositiveInt
    owner: Literal["evaluation", "research_lead", "operator"]
    status: Literal["draft"]
    source: list[Text]
    parameters: dict[Text, JsonValue]
    unresolved: list[Text]

    @model_validator(mode="after")
    def correct_owner(self) -> Self:
        expected = {
            "protocol": "evaluation",
            "release_policy": "evaluation",
            "quota": "evaluation",
            "charter": "research_lead",
            "job": "operator",
        }
        if self.owner != expected[self.kind]:
            raise ValueError("configuration owner does not match trust zone")
        return self


class UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(
        self, node: yaml.nodes.MappingNode, deep: bool = False
    ) -> dict[Hashable, object]:
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate YAML configuration key")
        return cast(dict[Hashable, object], super().construct_mapping(node, deep=deep))


def load_yaml[T: BaseModel](path: Path, contract: type[T]) -> T:
    value: object = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    return contract.model_validate(value)


def load_profile(settings: Settings, kind: str, profile: str) -> ConfigDocument:
    folders = {
        "protocol": "protocols",
        "release_policy": "release_policies",
        "quota": "quotas",
        "charter": "research",
        "job": "jobs",
    }
    if kind not in folders or profile not in {"pilot_industry_v1", "stock_daily_v1"}:
        raise ValueError("unknown configuration kind or profile")
    document = load_yaml(settings.config_root / folders[kind] / f"{profile}.yaml", ConfigDocument)
    if document.kind != kind or document.profile != profile:
        raise ValueError("configuration identity differs from requested file")
    return document
