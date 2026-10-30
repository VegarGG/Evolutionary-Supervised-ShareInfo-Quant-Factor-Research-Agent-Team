"""Bounded byte/format validation only; never imports or executes source packages."""

import codecs
import hashlib
import json
import os
import stat
import struct
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from qfr_core.contracts.transfers import IntakeTransportPolicy, UploadDeclaration


@contextmanager
def confined_file(root: Path, relative: str) -> Iterator[BinaryIO]:
    parts = relative.split("/")
    if (
        PurePosixPath(relative).is_absolute()
        or any(p in {"", ".", ".."} for p in parts)
        or "\\" in relative
        or ":" in relative
        or "\x00" in relative
    ):
        raise ValueError("import path is not confined")
    # Open each directory through its descriptor: no resolve/open symlink race.
    current = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=current)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("import source is not a regular file")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                yield stream
        finally:
            os.close(fd)
    finally:
        os.close(current)


def _archive(stream: BinaryIO, size: int, policy: IntakeTransportPolicy) -> None:
    stream.seek(max(0, size - 65557))
    tail = stream.read(65557)
    pos = tail.rfind(b"PK\x05\x06")
    if pos < 0 or len(tail) - pos < 22:
        raise ValueError("archive end record unavailable")
    _, disk, start_disk, disk_count, count, directory, offset, comment = struct.unpack_from(
        "<4s4H2LH", tail, pos
    )
    end = size - len(tail) + pos
    if (
        disk
        or start_disk
        or count != disk_count
        or count > policy.max_archive_entries
        or directory > policy.max_archive_directory_bytes
        or offset + directory != end
        or end + 22 + comment != size
    ):
        raise ValueError("archive directory exceeds supported bounds")
    stream.seek(0)
    seen: set[str] = set()
    total = 0
    with zipfile.ZipFile(stream) as archive:
        if len(archive.infolist()) != count:
            raise ValueError("archive directory count differs")
        for info in archive.infolist():
            name = info.filename.removesuffix("/") if info.is_dir() else info.filename
            path = PurePosixPath(name)
            mode = stat.S_IFMT(info.external_attr >> 16)
            if (
                info.orig_filename != info.filename
                or not name
                or name in seen
                or path.is_absolute()
                or path.as_posix() != name
                or any(p in {"", ".", ".."} for p in name.split("/"))
                or "\\" in name
                or ":" in name
                or "\x00" in name
                or mode not in ({0, stat.S_IFDIR} if info.is_dir() else {0, stat.S_IFREG})
                or info.flag_bits & 1
                or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
            ):
                raise ValueError("unsafe archive member")
            seen.add(name)
            total += info.file_size
            if total > policy.max_expanded_bytes or info.file_size > policy.max_member_bytes:
                raise ValueError("archive expansion exceeds bound")
            if info.is_dir():
                if info.file_size:
                    raise ValueError("archive directory contains bytes")
                continue
            actual = 0
            with archive.open(info) as member:
                while chunk := member.read(
                    min(policy.chunk_bytes, policy.max_member_bytes - actual + 1)
                ):
                    actual += len(chunk)
                    if actual > info.file_size or actual > policy.max_member_bytes:
                        raise ValueError("archive member expansion differs")
            if actual != info.file_size:
                raise ValueError("archive member size differs")


def validate_transport(
    stream: BinaryIO, declaration: UploadDeclaration, policy: IntakeTransportPolicy
) -> None:
    if (
        declaration.bytes > policy.max_upload_bytes
        or declaration.media_type not in policy.media_types
    ):
        raise ValueError("source exceeds authorized transport policy")
    stream.seek(0)
    header = stream.read(512)
    if (
        header.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
        and declaration.media_type != "application/zip"
    ):
        raise ValueError("archive must declare its validated format")
    if (
        header.startswith(
            (b"\x1f\x8b", b"BZh", b"\xfd7zXZ", b"7z\xbc\xaf\x27\x1c", b"Rar!", b"\x28\xb5\x2f\xfd")
        )
        or header[257:262] == b"ustar"
    ):
        raise ValueError("archive format is not supported for source transport")
    stream.seek(0)
    digest, size = hashlib.sha256(), 0
    decoder = (
        codecs.getincrementaldecoder("utf-8")()
        if declaration.media_type.startswith("text/")
        else None
    )
    while chunk := stream.read(policy.chunk_bytes):
        size += len(chunk)
        if size > declaration.bytes:
            raise ValueError("source size differs")
        digest.update(chunk)
        if decoder:
            decoder.decode(chunk)
    if decoder:
        decoder.decode(b"", final=True)
    if size != declaration.bytes or digest.hexdigest() != declaration.sha256:
        raise ValueError("source checksum differs")
    if declaration.media_type == "application/zip":
        _archive(stream, size, policy)
    elif declaration.media_type == "application/json":
        if size > policy.max_metadata_bytes:
            raise ValueError("JSON source exceeds metadata bound")
        stream.seek(0)

        def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate JSON source key")
                result[key] = value
            return result

        value = json.load(stream, object_pairs_hook=unique)
        json.dumps(value, allow_nan=False)
    elif declaration.media_type == "application/vnd.apache.parquet":
        stream.seek(0)
        first = stream.read(4)
        stream.seek(max(0, size - 4))
        if size < 12 or first != b"PAR1" or stream.read(4) != b"PAR1":
            raise ValueError("Parquet source envelope differs")
