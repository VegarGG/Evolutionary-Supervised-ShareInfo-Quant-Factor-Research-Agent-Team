"""Closed Docker-native job specification; none of these options come from code."""

import hashlib
import io
import json
import re
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

from qfr_core import sandbox_guest
from qfr_core.contracts.execution import RunnerInput
from qfr_core.data_layer.snapshots import canonical_json

from qfr_eval.sandbox.models import DockerNativeProfile
from qfr_eval.sandbox.runner import _relative_file

LABEL = "org.qfr.sandbox.job"


def identity(value: str) -> str:
    if not re.fullmatch(r"qfr-native-[0-9a-f]{32}", value):
        raise ValueError("invalid controller-owned job identity")
    return value


def seccomp(profile: DockerNativeProfile) -> str:
    data = (Path(__file__).parent / "vendor/moby-default.json").read_bytes()
    if hashlib.sha256(data).hexdigest() != profile.seccomp_sha256:
        raise ValueError("pinned seccomp policy differs")
    return json.dumps(json.loads(data), separators=(",", ":"))


def volume_spec(profile: DockerNativeProfile, job: str) -> dict[str, Any]:
    identity(job)
    return {
        "Name": job + "-input",
        "Driver": "local",
        "DriverOpts": {
            "type": "tmpfs",
            "device": "tmpfs",
            "o": f"size={profile.input_tmpfs_bytes},uid={profile.user_id},gid={profile.user_id},"
            "mode=0700,noexec,nosuid,nodev",
        },
        "Labels": {LABEL: job, "org.qfr.sandbox.profile": profile.sha256},
    }


def container_spec(
    profile: DockerNativeProfile,
    image: str,
    job: str,
    seed: int,
    *,
    helper: bool,
) -> dict[str, Any]:
    identity(job)
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image) or not 0 <= seed < 2**32:
        raise ValueError("immutable image and bounded seed required")
    env = {
        "PYTHONHASHSEED": str(seed),
        "PYTHONPATH": "",
        "PYTHONHOME": "",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "POLARS_MAX_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
        "TZ": "UTC",
        "HOME": "/tmp",
        **{
            key: ""
            for key in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "NO_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
                "no_proxy",
            )
        },
    }
    return {
        "Image": image,
        "User": f"{profile.user_id}:{profile.user_id}",
        "Entrypoint": ["python"],
        "WorkingDir": "/",
        "Env": [f"{k}={v}" for k, v in env.items()],
        "Cmd": [
            "-I",
            "-B",
            "-c",
            "import time; time.sleep("
            + str(profile.timeout_seconds + 20 * profile.control_timeout_seconds)
            + ")",
        ],
        "Labels": {
            LABEL: job,
            "org.qfr.sandbox.profile": profile.sha256,
            "org.qfr.sandbox.role": "stager" if helper else "candidate",
        },
        "AttachStdin": False,
        "AttachStdout": False,
        "AttachStderr": False,
        "OpenStdin": False,
        "Tty": False,
        "NetworkDisabled": True,
        "HostConfig": {
            "Runtime": "runc",
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "CapAdd": [],
            "GroupAdd": [],
            "Privileged": False,
            "SecurityOpt": ["no-new-privileges:true", "seccomp=" + seccomp(profile)],
            "Memory": profile.memory_bytes,
            "MemorySwap": profile.memory_bytes,
            "NanoCpus": int(profile.cpus * 1_000_000_000),
            "PidsLimit": profile.pids_limit,
            "Ulimits": [
                {"Name": "cpu", "Soft": profile.cpu_seconds, "Hard": profile.cpu_seconds + 1},
                {
                    "Name": "fsize",
                    "Soft": profile.max_output_bytes,
                    "Hard": profile.max_output_bytes,
                },
                {
                    "Name": "nofile",
                    "Soft": profile.file_descriptors,
                    "Hard": profile.file_descriptors,
                },
                {"Name": "core", "Soft": 0, "Hard": 0},
            ],
            "Tmpfs": {"/tmp": f"rw,noexec,nosuid,nodev,size={profile.tmpfs_bytes},mode=1777"},
            "Mounts": [
                {
                    "Type": "volume",
                    "Source": job + "-input",
                    "Target": "/input",
                    "ReadOnly": not helper,
                    "VolumeOptions": {"NoCopy": True},
                }
            ],
            "ShmSize": 1048576,
            "IpcMode": "private",
            "CgroupnsMode": "private",
            "PidMode": "",
            "Devices": [],
            "DeviceRequests": [],
            "Binds": [],
            "VolumesFrom": [],
            "LogConfig": {"Type": "none", "Config": {}},
            "RestartPolicy": {"Name": "no"},
            "AutoRemove": False,
            "PublishAllPorts": False,
        },
    }


def input_archive(
    profile: DockerNativeProfile,
    files: dict[str, bytes],
    request: RunnerInput,
    options: dict[str, Any],
) -> bytes:
    data = canonical_json(request.model_dump(mode="json"))
    if len(data) > profile.max_input_bytes or len(files) > profile.max_package_files:
        raise ValueError("native input exceeds frozen bounds")
    if sum(map(len, files.values())) > profile.max_package_bytes:
        raise ValueError("native package exceeds frozen bounds")
    contents = {}
    for name, value in files.items():
        if len(name.encode()) > 240:
            raise ValueError("native package path is too long")
        contents["package/" + _relative_file(name)] = value
    contents.update(
        {
            "request.json": data,
            "guest.py": Path(sandbox_guest.__file__).read_bytes(),
            "options.json": canonical_json(
                {
                    **options,
                    "process_accounting": profile.process_accounting,
                    "pids_limit": profile.pids_limit,
                    "max_output_bytes": profile.max_output_bytes,
                }
            ),
        }
    )
    if len(contents["options.json"]) + len(contents["guest.py"]) > 65536:
        raise ValueError("trusted metadata exceeds frozen allowance")
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
    contents["seal.json"] = canonical_json(manifest)
    directories = {"package"}
    for name in contents:
        directories.update(str(p) for p in PurePosixPath(name).parents if str(p) != ".")
    if directories.intersection(contents):
        raise ValueError("package file shadows a directory")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(directories):
            info = tarfile.TarInfo(name)
            info.type, info.mode = tarfile.DIRTYPE, 0o555
            info.uid = info.gid = profile.user_id
            archive.addfile(info)
        for name, data in sorted(contents.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o444
            info.uid = info.gid = profile.user_id
            archive.addfile(info, io.BytesIO(data))
    if buffer.tell() > profile.input_tmpfs_bytes:
        raise ValueError("native archive exceeds staging allowance")
    return buffer.getvalue()


SEAL_CHECK = """
import hashlib,json,pathlib,stat
root=pathlib.Path('/input')
manifest=json.loads((root/'seal.json').read_bytes())
expected=set(manifest)|{'seal.json'}
actual=set()
for path in root.rglob('*'):
    st=path.lstat()
    assert not stat.S_ISLNK(st.st_mode)
    if stat.S_ISDIR(st.st_mode):
        continue
    assert stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_mode & 0o222 == 0
    name=str(path.relative_to(root)); actual.add(name)
    if name != 'seal.json':
        assert name in manifest
        with path.open('rb') as stream:
            assert hashlib.file_digest(stream,'sha256').hexdigest()==manifest[name]
assert actual==expected
"""
