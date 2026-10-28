"""Parser/API refusal units; the separately marked native test proves real Apple APIs."""

import ctypes
import hashlib
import json
import platform
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError
from qfr_eval import apple_runtime as apple
from qfr_eval.runtime_contracts import (
    AppleAccelerateExecution,
    NumericalExecution,
    RuntimeCompatibilityError,
)


def macho(*, protection=5, identity=None, command_size=96, file_offset=0):
    identity = UUID(int=1) if identity is None else identity
    header = struct.pack("<IiiIIIII", 0xFEEDFACF, 16777228, 0, 6, 2, command_size, 0, 0)
    commands = struct.pack(
        "<II16sQQQQiiII", 0x19, 72, b"__TEXT", 0, 4096, file_offset, 512, 5, protection, 0, 0
    )
    commands += struct.pack("<II16s", 0x1B, 24, identity.bytes)
    return header, commands


def test_loaded_macho_identity_is_bounded_and_rejects_missing_or_mutable_text():
    header, commands = macho()
    assert apple.parse_image_commands(header, commands) == (UUID(int=1), 16777228, 0, 0, 512)
    assert apple.parse_image_commands(*macho(file_offset=65536)) == (
        UUID(int=1),
        16777228,
        0,
        0,
        512,
    )
    for bad_header, bad_commands in (
        (header[:-1], commands),
        (header, commands[:-1]),
        macho(protection=3),
        macho(identity=UUID(int=0)),
        macho(command_size=2**30),
        (header, b"\x00" * 8 + commands[8:]),
    ):
        with pytest.raises(RuntimeCompatibilityError):
            apple.parse_image_commands(bad_header, bad_commands)


def test_loaded_image_fingerprint_uses_mapped_text_not_path_or_aslr(monkeypatch):
    header, commands = macho()
    text = header + commands + b"a" * (512 - len(header) - len(commands))
    buffers = [ctypes.create_string_buffer(text), ctypes.create_string_buffer(text)]
    selected = [0]

    class Function:
        def __init__(self, call):
            self.call = call

        def __call__(self, *args):
            return self.call(*args)

    class Library:
        _dyld_image_count = Function(lambda: 1)
        _dyld_get_image_name = Function(lambda _: apple.BLAS.encode())
        _dyld_get_image_header = Function(lambda _: ctypes.addressof(buffers[selected[0]]))
        _dyld_get_image_vmaddr_slide = Function(lambda _: ctypes.addressof(buffers[selected[0]]))

    # Synthetic mappings exercise the real bounded reader. This is not native evidence.
    monkeypatch.setattr(apple.ctypes, "CDLL", lambda _: Library())
    first = apple.loaded_images()
    selected[0] = 1
    assert apple.loaded_images() == first
    assert first[0].text_sha256 == hashlib.sha256(text).hexdigest()
    buffers[1][200] = b"b"
    assert apple.loaded_images()[0].text_sha256 != first[0].text_sha256
    Library._dyld_get_image_vmaddr_slide = Function(lambda _: 0)
    with pytest.raises(RuntimeCompatibilityError, match="text_mapping_mismatch"):
        apple.loaded_images()


def test_missing_api_and_failed_readback_never_become_empty_success(monkeypatch):
    monkeypatch.setattr(apple.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(apple.platform, "machine", lambda: "arm64")
    apple.threading_api.cache_clear()
    with monkeypatch.context() as local:

        def missing(_):
            raise OSError("synthetic unavailable API")

        local.setattr(apple.ctypes, "CDLL", missing)
        with pytest.raises(RuntimeCompatibilityError, match="threading_api_unavailable"):
            apple.initialize_single_thread()
    for setter_result, getter_result in ((-1, 1), (0, 0), (0, 99)):
        monkeypatch.setattr(
            apple,
            "threading_api",
            lambda g=getter_result, s=setter_result: (lambda: g, lambda _: s),
        )
        with pytest.raises(RuntimeCompatibilityError, match="request_failed"):
            apple.initialize_single_thread()


def test_accelerate_detection_rejects_partial_or_unknown_linkage(monkeypatch):
    monkeypatch.setattr(apple.platform, "system", lambda: "Darwin")
    dependencies = {
        "blas": {"name": "accelerate", "found": True},
        "lapack": {"name": "accelerate", "found": True},
    }
    module = SimpleNamespace(show_config=lambda **_: {"Build Dependencies": dependencies})
    with monkeypatch.context() as local:
        local.setattr(apple.importlib, "import_module", lambda _: module)
        assert apple.consumers() == {"numpy": "accelerate", "scipy": "accelerate"}
        dependencies["lapack"]["name"] = "unknown-stub"
        with pytest.raises(RuntimeCompatibilityError, match="ambiguous_linkage"):
            apple.consumers()
        dependencies.clear()
        with pytest.raises(RuntimeCompatibilityError, match="unobservable_package"):
            apple.consumers()


def test_hardware_identity_reads_are_allowlisted_bounded_and_never_write(monkeypatch):
    failure = [False]

    def read(name, buffer, length, new, new_length):
        assert name == b"hw.model" and new is None and new_length == 0
        if failure[0]:
            return -1
        value = b"synthetic-model\0"
        ctypes.memmove(buffer, value, len(value))
        length._obj.value = len(value)
        return 0

    monkeypatch.setattr(apple.ctypes, "CDLL", lambda _: SimpleNamespace(sysctlbyname=read))
    assert apple.hardware_text("hw.model") == "synthetic-model"
    failure[0] = True
    with pytest.raises(RuntimeCompatibilityError, match="hardware_identity_unavailable"):
        apple.hardware_text("hw.model")
    with pytest.raises(RuntimeCompatibilityError, match="unknown_hardware_field"):
        apple.hardware_text("unapproved")


def test_apple_contract_requires_actual_evidence_and_preserves_previous_serialization():
    root = Path("packages/qfr_eval/src/qfr_eval/private_contracts")
    old = json.loads((root / "NumericalExecution.valid.json").read_bytes())
    assert NumericalExecution.model_validate(old).model_dump(mode="json") == old
    raw = json.loads((root / "AppleAccelerateExecution.valid.json").read_bytes())
    with pytest.raises(ValidationError, match="evidence"):
        AppleAccelerateExecution.model_validate({**raw, "images": []})
    with pytest.raises(ValidationError):
        AppleAccelerateExecution.model_validate({**raw, "effective_threads": 2})
    with pytest.raises(ValidationError, match="observable"):
        NumericalExecution.model_validate({**old, "libraries": []})
    value = {
        **old,
        "schema_version": "2",
        "system": "Darwin",
        "machine": "arm64",
        "libraries": [],
        "accelerate": raw,
    }
    assert NumericalExecution.model_validate(value).accelerate.effective_threads == 1
    with pytest.raises(ValidationError, match="native Apple"):
        NumericalExecution.model_validate({**value, "system": "Linux"})


@pytest.mark.skipif(
    platform.system() != "Darwin", reason="UNRUN: native Apple Accelerate APIs required"
)
def test_native_apple_api_readback_identity_and_calling_thread_refusal():
    from concurrent.futures import ThreadPoolExecutor

    from qfr_eval.runtime import capture_runtime, verify_runtime

    assert platform.machine() == "arm64"
    runtime = capture_runtime(evaluator_git_sha="0" * 40, image_digest="0" * 64)
    identity = runtime.numerical_execution.accelerate
    assert identity is not None and identity.consumers
    assert (
        identity.os_build and identity.os_version and identity.hardware_model and identity.cpu_brand
    )
    assert all(image.text_bytes > 0 and len(image.text_sha256) == 64 for image in identity.images)
    getter, setter = apple.threading_api()
    assert getter() == 1
    verify_runtime(runtime)

    def separate_thread():
        # Deliberate local API perturbation, never a host preference or environment workaround.
        original = getter()
        try:
            assert setter(0) == 0 and getter() == 0
            with pytest.raises(RuntimeCompatibilityError, match="accelerate_not_single_threaded"):
                verify_runtime(runtime)
        finally:
            assert setter(original) == 0

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(separate_thread).result(timeout=10)
    assert getter() == 1
    verify_runtime(runtime)


@pytest.mark.skipif(platform.system() != "Darwin", reason="UNRUN: native Apple SDK/API required")
def test_native_apple_sdk_constants_and_public_threading_api(tmp_path):
    # Verify the ABI against the installed official SDK, not duplicated Python constants.
    # Requires existing Xcode Command Line Tools; never installs or changes them.
    source = tmp_path / "threading.c"
    executable = tmp_path / "threading"
    source.write_text("""#include <Accelerate/Accelerate.h>
#include <stdio.h>
int main(void) {
    int status = BLASSetThreading(BLAS_THREADING_SINGLE_THREADED);
    printf("%u %u %zu %d %u\\n", (unsigned)BLAS_THREADING_MULTI_THREADED,
        (unsigned)BLAS_THREADING_SINGLE_THREADED, sizeof(enum BLAS_THREADING),
        status, (unsigned)BLASGetThreading());
    return status != 0;
}
""")
    environment = {"PATH": "/usr/bin:/bin", "TMPDIR": str(tmp_path)}
    build = subprocess.run(
        [
            "/usr/bin/xcrun",
            "--sdk",
            "macosx",
            "clang",
            str(source),
            "-framework",
            "Accelerate",
            "-o",
            str(executable),
        ],
        env=environment,
        capture_output=True,
        timeout=45,
        check=False,
    )
    assert build.returncode == 0, "Existing Apple SDK/clang cannot compile the public threading API"
    result = subprocess.run(
        [str(executable)],
        env=environment,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0 and result.stdout == b"0 1 4 0 1\n"
