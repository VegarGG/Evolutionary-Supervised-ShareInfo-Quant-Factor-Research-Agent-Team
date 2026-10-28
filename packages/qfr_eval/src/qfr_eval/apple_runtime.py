"""Observe Apple Accelerate through public APIs, never infer pools from an env var.

BLASSetThreading/BLASGetThreading apply to the calling thread (macOS 15+).
Mach-O definitions follow Apple's mach-o/loader.h; inspect only this process's
loaded system framework. __TEXT fingerprints also work for dyld-cache images
that have no standalone dylib file. No host setting or library file is changed.
"""

import ctypes
import hashlib
import importlib
import json
import platform
import plistlib
import struct
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

from qfr_eval.runtime_contracts import (
    AccelerateImage,
    AppleAccelerateExecution,
    RuntimeCompatibilityError,
)

FRAMEWORK = "/System/Library/Frameworks/Accelerate.framework/"
BLAS = FRAMEWORK + "Versions/A/Frameworks/vecLib.framework/Versions/A/libBLAS.dylib"
POLICY_BYTES = Path(__file__).with_name("apple_runtime_policy_v1.json").read_bytes()
POLICY = json.loads(POLICY_BYTES)
POLICY_HASH = hashlib.sha256(POLICY_BYTES).hexdigest()
AppleConsumers = dict[Literal["numpy", "scipy"], Literal["accelerate"]]
PACKAGES: tuple[Literal["numpy", "scipy"], ...] = ("numpy", "scipy")


def consumers() -> AppleConsumers:
    """Require declared new-Accelerate linkage, not a generic BLAS stub guess."""
    if platform.system() != "Darwin":
        return {}
    result: AppleConsumers = {}
    try:
        for name in PACKAGES:
            dependencies = importlib.import_module(name).show_config(mode="dicts")[
                "Build Dependencies"
            ]
            blas, lapack = (dependencies[k] for k in ("blas", "lapack"))
            if blas["name"] == "accelerate" or lapack["name"] == "accelerate":
                if not all(d["name"] == "accelerate" and d["found"] for d in (blas, lapack)):
                    raise RuntimeCompatibilityError("accelerate_ambiguous_linkage")
                result[name] = "accelerate"
    except RuntimeCompatibilityError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError):
        raise RuntimeCompatibilityError("unobservable_package_blas_linkage") from None
    return result


@lru_cache(maxsize=1)
def threading_api() -> tuple[Callable[[], int], Callable[[int], int]]:
    if (platform.system(), platform.machine()) != ("Darwin", "arm64"):
        raise RuntimeCompatibilityError("accelerate_requires_native_apple_arm64")
    try:
        library = ctypes.CDLL(FRAMEWORK + "Accelerate")
        getter = library.BLASGetThreading
        getter.argtypes, getter.restype = [], ctypes.c_uint
        setter = library.BLASSetThreading
        setter.argtypes, setter.restype = [ctypes.c_uint], ctypes.c_int
        return getter, setter
    except (OSError, AttributeError):
        raise RuntimeCompatibilityError("accelerate_threading_api_unavailable") from None


def initialize_single_thread() -> None:
    """Explicit new-runtime/bootstrap initialization; verification never calls this."""
    getter, setter = threading_api()
    # SDK BLAS_THREADING_SINGLE_THREADED = 1; MULTI_THREADED = 0 is adaptive.
    if POLICY["threading_mode"] != 1 or setter(1) != 0 or getter() != 1:
        raise RuntimeCompatibilityError("accelerate_single_thread_request_failed")


def hardware_text(name: Literal["hw.model", "machdep.cpu.brand_string"]) -> str:
    """Read two non-unique hardware labels. The write arguments are always NULL/0."""
    if name not in ("hw.model", "machdep.cpu.brand_string"):
        raise RuntimeCompatibilityError("accelerate_unknown_hardware_field")
    read = ctypes.CDLL(None).sysctlbyname
    read.argtypes = [
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    read.restype = ctypes.c_int
    maximum = POLICY["max_sysctl_text_bytes"]
    buffer = ctypes.create_string_buffer(maximum)
    size = ctypes.c_size_t(maximum)
    if read(name.encode("ascii"), buffer, ctypes.byref(size), None, 0) != 0:
        raise RuntimeCompatibilityError("accelerate_hardware_identity_unavailable")
    if not 1 < size.value <= maximum or buffer.raw[size.value - 1] != 0:
        raise RuntimeCompatibilityError("accelerate_invalid_hardware_identity")
    value = buffer.raw[: size.value - 1].decode("utf-8")
    if not value.strip() or "\0" in value:
        raise RuntimeCompatibilityError("accelerate_invalid_hardware_identity")
    return value


def parse_image_commands(header: bytes, commands: bytes) -> tuple[UUID, int, int, int, int]:
    """Pure bounded parsing, also tested with malformed synthetic Mach-O data."""
    if len(header) != 32:
        raise RuntimeCompatibilityError("accelerate_invalid_macho")
    magic, cpu, subtype, _, count, size, _, _ = struct.unpack("<IiiIIIII", header)
    if (
        magic != 0xFEEDFACF
        or not 0 < count <= POLICY["max_macho_commands"]
        or not 0 < size <= POLICY["max_macho_command_bytes"]
        or len(commands) != size
    ):
        raise RuntimeCompatibilityError("accelerate_invalid_macho")
    offset = 0
    identity = None
    text_bytes = None
    text_vmaddr = None
    for _ in range(count):
        if offset + 8 > size:
            raise RuntimeCompatibilityError("accelerate_invalid_macho")
        command, length = struct.unpack_from("<II", commands, offset)
        if length < 8 or offset + length > size:
            raise RuntimeCompatibilityError("accelerate_invalid_macho")
        if command == 0x1B:  # LC_UUID
            if length != 24 or identity is not None:
                raise RuntimeCompatibilityError("accelerate_invalid_macho")
            identity = UUID(bytes=commands[offset + 8 : offset + 24])
        if command == 0x19:  # LC_SEGMENT_64
            if length < 72:
                raise RuntimeCompatibilityError("accelerate_invalid_macho")
            segment = struct.unpack_from("<II16sQQQQiiII", commands, offset)
            if segment[2].rstrip(b"\0") == b"__TEXT":
                _, _, _, vmaddr, vmsize, _, filesize, _, protection, _, _ = segment
                if (
                    text_bytes is not None
                    or not 32 + size <= filesize <= min(vmsize, POLICY["max_image_text_bytes"])
                    or protection & 2  # VM_PROT_WRITE
                    or not protection & 1  # VM_PROT_READ
                ):
                    raise RuntimeCompatibilityError("accelerate_invalid_text_segment")
                text_bytes = filesize
                text_vmaddr = vmaddr
        offset += length
    if (
        offset != size
        or identity is None
        or not identity.int
        or text_bytes is None
        or text_vmaddr is None
    ):
        raise RuntimeCompatibilityError("accelerate_incomplete_image_identity")
    return identity, cpu, subtype, text_vmaddr, text_bytes


def loaded_images() -> list[AccelerateImage]:
    library = ctypes.CDLL(None)
    count = library._dyld_image_count
    count.argtypes, count.restype = [], ctypes.c_uint32
    name_at = library._dyld_get_image_name
    name_at.argtypes, name_at.restype = [ctypes.c_uint32], ctypes.c_char_p
    header_at = library._dyld_get_image_header
    header_at.argtypes, header_at.restype = [ctypes.c_uint32], ctypes.c_void_p
    slide_at = library._dyld_get_image_vmaddr_slide
    slide_at.argtypes, slide_at.restype = [ctypes.c_uint32], ctypes.c_ssize_t
    image_count = count()
    if not 0 < image_count <= POLICY["max_loaded_images"]:
        raise RuntimeCompatibilityError("accelerate_loaded_image_limit")
    result = []
    total = 0
    for index in range(image_count):
        raw_name = name_at(index)
        if raw_name is None:
            raise RuntimeCompatibilityError("accelerate_loaded_images_changed")
        name = raw_name.decode("utf-8")
        if not name.startswith(FRAMEWORK):
            continue
        address = header_at(index)
        if not address:
            raise RuntimeCompatibilityError("accelerate_missing_image_header")
        header = ctypes.string_at(address, 32)
        magic, _, _, _, ncmds, size, _, _ = struct.unpack("<IiiIIIII", header)
        if (
            magic != 0xFEEDFACF
            or not 0 < ncmds <= POLICY["max_macho_commands"]
            or not 0 < size <= POLICY["max_macho_command_bytes"]
        ):
            raise RuntimeCompatibilityError("accelerate_invalid_macho")
        identity, cpu, subtype, vmaddr, size = parse_image_commands(
            header, ctypes.string_at(address + 32, size)
        )
        # Use dyld's actual mapping, not standalone-file offset assumptions.
        # Cache image file offsets need not be zero. No ASLR address is recorded.
        if vmaddr + slide_at(index) != address:
            raise RuntimeCompatibilityError("accelerate_text_mapping_mismatch")
        total += size
        if total > POLICY["max_total_text_bytes"]:
            raise RuntimeCompatibilityError("accelerate_text_limit")
        # Read the mapped immutable __TEXT segment without a same-sized copy.
        digest = hashlib.sha256((ctypes.c_ubyte * size).from_address(address)).hexdigest()
        result.append(
            AccelerateImage(
                install_name=name,
                image_uuid=identity,
                cpu_type=cpu,
                cpu_subtype=subtype,
                text_bytes=size,
                text_sha256=digest,
            )
        )
    if count() != image_count:
        raise RuntimeCompatibilityError("accelerate_loaded_images_changed")
    return sorted(result, key=lambda image: image.install_name)


@lru_cache(maxsize=16)
def _extension_hash(path: str, size: int, mtime: int) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observe(linked_consumers: AppleConsumers) -> AppleAccelerateExecution:
    try:
        getter, _ = threading_api()
        if getter() != 1:
            raise RuntimeCompatibilityError("accelerate_not_single_threaded")
        # Resolve lazy system code identically before both capture and verify.
        # These fixed 2x2 preflight inputs are unrelated to research/holdout data.
        import numpy as np
        import scipy.linalg

        np.linalg.solve(np.eye(2), np.ones(2))
        scipy.linalg.solve(np.eye(2), np.ones(2))
        version = plistlib.loads(
            Path("/System/Library/CoreServices/SystemVersion.plist").read_bytes()
        )
        extensions = {}
        for name in (
            "numpy._core._multiarray_umath",
            "numpy.linalg._umath_linalg",
            "scipy.linalg._fblas",
            "scipy.linalg._flapack",
        ):
            module = importlib.import_module(name)
            if module.__file__ is None:
                raise RuntimeCompatibilityError("accelerate_missing_extension_file")
            path = Path(module.__file__)
            stat = path.stat()
            extensions[name] = _extension_hash(str(path), stat.st_size, stat.st_mtime_ns)
        return AppleAccelerateExecution(
            schema_version="1",
            policy_sha256=POLICY_HASH,
            threading_mode="single_threaded",
            threading_scope="calling_thread",
            effective_threads=1,
            os_version=version["ProductVersion"],
            os_build=version["ProductBuildVersion"],
            hardware_model=hardware_text("hw.model"),
            cpu_brand=hardware_text("machdep.cpu.brand_string"),
            consumers=linked_consumers,
            extension_hashes=extensions,
            images=loaded_images(),
        )
    except RuntimeCompatibilityError:
        raise
    except (OSError, AttributeError, KeyError, TypeError, ValueError, struct.error):
        raise RuntimeCompatibilityError("accelerate_unobservable_execution") from None
