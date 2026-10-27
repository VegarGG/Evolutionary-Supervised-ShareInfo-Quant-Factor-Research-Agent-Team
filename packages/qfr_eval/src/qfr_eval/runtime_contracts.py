"""Private execution identity; importing this module initializes no numerical library."""

from typing import Any, Literal, Self

from pydantic import PositiveInt, SerializerFunctionWrapHandler, model_serializer, model_validator
from qfr_core.contracts.base import Contract, Sha256, Text

THREAD_VARIABLES = (
    "POLARS_MAX_THREADS",
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "BLIS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "OMP_DYNAMIC",
    "MKL_DYNAMIC",
)


class NumericalLibrary(Contract):
    user_api: Literal["blas", "openmp"]
    internal_api: Literal["openblas", "mkl", "blis", "openmp"]
    prefix: Text
    version: Text | None
    num_threads: PositiveInt
    architecture: Text | None
    threading_layer: Text | None
    binary_sha256: Sha256


class NumericalExecution(Contract):
    schema_version: Literal["1"]
    system: Text
    machine: Text
    polars_threads: PositiveInt
    thread_environment: dict[Text, Text | None]
    libraries: list[NumericalLibrary]

    @model_validator(mode="after")
    def closed_startup_environment(self) -> Self:
        if set(self.thread_environment) != set(THREAD_VARIABLES):
            raise ValueError("numerical startup requires the exact thread-variable allowlist")
        for key, value in self.thread_environment.items():
            if value is None:
                continue
            if key.endswith("_DYNAMIC"):
                if value != "FALSE":
                    raise ValueError("dynamic numerical thread pools cannot be frozen")
            elif not value.isascii() or not value.isdecimal() or int(value) < 1:
                raise ValueError("thread counts must be positive decimal integers")
        if self.thread_environment["POLARS_MAX_THREADS"] != str(self.polars_threads):
            raise ValueError("Polars startup and effective pool must agree")
        if not any(lib.user_api == "blas" for lib in self.libraries):
            raise ValueError("effective BLAS thread pools must be observable")
        controls = {
            "openblas": "OPENBLAS_NUM_THREADS",
            "openmp": "OMP_NUM_THREADS",
            "mkl": "MKL_NUM_THREADS",
            "blis": "BLIS_NUM_THREADS",
        }
        for lib in self.libraries:
            if self.thread_environment[controls[lib.internal_api]] != str(lib.num_threads):
                raise ValueError("library startup and effective thread pools must agree")
        return self


class RuntimeIdentity(Contract):
    schema_version: Literal["1", "2"] = "1"
    evaluator_git_sha: Text
    implementation_sha256: Sha256
    image_digest: Sha256
    software: dict[Text, Text]
    numerical_execution: NumericalExecution | None = None

    @model_validator(mode="after")
    def explicit_execution_version(self) -> Self:
        if (self.schema_version == "2") != (self.numerical_execution is not None):
            raise ValueError("runtime v2 requires numerical execution; legacy v1 cannot claim it")
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_identity(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        value: dict[str, Any] = handler(self)
        if self.schema_version == "1":
            value.pop("schema_version", None)
            value.pop("numerical_execution", None)
        return value


class RuntimeCompatibilityError(ValueError):
    """Fixed safe reason; never render environment values or driver exceptions."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("pinned evaluator runtime differs: " + reason)
