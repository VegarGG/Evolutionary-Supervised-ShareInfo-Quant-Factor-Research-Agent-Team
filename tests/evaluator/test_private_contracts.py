import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError
from qfr_eval.backtest.prefix import PrefixCheck
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.records import (
    EvaluationRequest,
    Measurement,
    MeasurementReceipt,
    OfficialRecord,
    ReproductionResult,
    RuntimeIdentity,
    StoredFile,
    TrialLedgerEntry,
)
from qfr_eval.scheduler.models import (
    DevelopmentBehavior,
    IntakeCampaign,
    IntakePolicy,
    PilotScreeningPolicy,
)
from qfr_eval.statistics.bootstrap import Interval
from qfr_eval.statistics.clustering import BehavioralFingerprint, ClusterSnapshot
from qfr_eval.statistics.family import FamilyInterval, FamilyStatistics, TrialObservation
from qfr_eval.statistics.hurdles import TurnoverResult
from qfr_eval.statistics.incremental import IncrementalResult

MODELS = (
    DevelopmentBehavior,
    IntakeCampaign,
    IntakePolicy,
    PilotScreeningPolicy,
    BehavioralFingerprint,
    ClusterSnapshot,
    EvaluationRequest,
    Measurement,
    MeasurementReceipt,
    OfficialRecord,
    RuntimeIdentity,
    ReproductionResult,
    StoredFile,
    TrialLedgerEntry,
    PrefixCheck,
    FrozenProtocol,
    Interval,
    FamilyInterval,
    FamilyStatistics,
    TrialObservation,
    TurnoverResult,
    IncrementalResult,
)


@pytest.mark.parametrize("model", MODELS)
def test_private_schemas_validate_examples_without_entering_public_catalog(model):
    root = Path("packages/qfr_eval/src/qfr_eval/private_contracts")
    valid = json.loads((root / f"{model.__name__}.valid.json").read_text())
    invalid = json.loads((root / f"{model.__name__}.invalid.json").read_text())
    schema = json.loads((root / f"{model.__name__}.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    model.model_validate(valid)
    validator.validate(valid)
    with pytest.raises(ValidationError):
        model.model_validate(invalid)
    assert list(validator.iter_errors(invalid))
    assert model.__name__ not in json.loads(Path("contracts/public-contracts.json").read_text())
