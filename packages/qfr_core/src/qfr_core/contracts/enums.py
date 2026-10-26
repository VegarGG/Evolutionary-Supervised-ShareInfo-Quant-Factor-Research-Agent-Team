"""Closed public vocabularies; private diagnostic text never enters released reports."""

from enum import StrEnum


class InputKind(StrEnum):
    IDEA = "idea"
    FACTOR = "factor"
    MODEL = "model"
    STRATEGY = "strategy"
    BUNDLE = "bundle"


class ArtifactKind(StrEnum):
    FACTOR = "factor"
    MODEL = "model"
    STRATEGY = "strategy"
    RESEARCH_NOTE = "research_note"
    DATA_PRODUCT = "data_product"


class PITGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class JobState(StrEnum):
    RECEIVED = "received"
    VALIDATING = "validating"
    READY = "ready"
    RUNNING = "running"
    AWAITING_EVALUATION = "awaiting_evaluation"
    VALIDATING_DELIVERY = "validating_delivery"
    COMPLETED = "completed"
    NEEDS_INPUT = "needs_input"
    PAUSED = "paused"
    BUDGET_PAUSED = "budget_paused"
    WAITING_FOR_DATA = "waiting_for_data"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReasonCode(StrEnum):
    SCHEMA_INVALID = "SCHEMA_INVALID"
    KIND_UNSUPPORTED = "KIND_UNSUPPORTED"
    PARSE_ERROR = "PARSE_ERROR"
    TYPE_ERROR = "TYPE_ERROR"
    COMPLEXITY_LIMIT = "COMPLEXITY_LIMIT"
    FORBIDDEN_CONSTRUCT = "FORBIDDEN_CONSTRUCT"
    DECLARATION_MISMATCH = "DECLARATION_MISMATCH"
    DUPLICATE_OF = "DUPLICATE_OF"
    NEAR_DUPLICATE_OF = "NEAR_DUPLICATE_OF"
    QUOTA_DEFERRED = "QUOTA_DEFERRED"
    QUOTA_EXPIRED = "QUOTA_EXPIRED"
    LOW_COVERAGE = "LOW_COVERAGE"
    LOOKAHEAD_DETECTED = "LOOKAHEAD_DETECTED"
    RUNTIME_LIMIT = "RUNTIME_LIMIT"
    DEGENERATE = "DEGENERATE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class DiagnosticFlag(StrEnum):
    HIGH_TURNOVER = "HIGH_TURNOVER"
    LOW_MONOTONICITY = "LOW_MONOTONICITY"
    SIGN_MISMATCH = "SIGN_MISMATCH"
    CROWDED_WITH_LIBRARY = "CROWDED_WITH_LIBRARY"
    UNSTABLE_YEARLY = "UNSTABLE_YEARLY"
    DECAYS_FAST = "DECAYS_FAST"
    LOW_COVERAGE = "LOW_COVERAGE"
    WEAK_SIGNAL = "WEAK_SIGNAL"
    COST_DOMINATED = "COST_DOMINATED"


class Conclusion(StrEnum):
    POSITIVE = "supported_positive"
    NEGATIVE = "supported_negative"
    EMPTY_SHORTLIST = "empty_shortlist"
    DATA_BLOCKED = "data_blocked"
