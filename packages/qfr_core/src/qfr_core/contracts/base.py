"""Shared schema primitives, not evaluation records."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

Text = Annotated[str, StringConstraints(min_length=1, strip_whitespace=False)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
SecretRef = Annotated[str, StringConstraints(pattern=r"^env:[A-Z][A-Z0-9_]*$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
