"""Private wrapper: keep the earlier integrity receipt and its hash immutable."""

from typing import Literal

from pydantic import AwareDatetime
from qfr_core.contracts.base import Contract
from qfr_core.contracts.reports import Signature

from qfr_eval.records import MeasurementReceipt


class SignedMeasurementReceipt(Contract):
    schema_version: Literal["1"]
    kind: Literal["private_signed_measurement_receipt"]
    authenticity: Literal["signed_wrapper"]
    receipt: MeasurementReceipt
    signed_at: AwareDatetime
    signature: Signature
