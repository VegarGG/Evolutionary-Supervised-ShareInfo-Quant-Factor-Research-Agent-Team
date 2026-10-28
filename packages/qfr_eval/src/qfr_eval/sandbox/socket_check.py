"""Read-only diagnostic for the trusted controller's existing Unix socket grant.

Run inside the intended controller container: Desktop's socket GID may differ
from the Mac host GID. Never chmod/chown, add groups, or open a TCP endpoint.
"""

import argparse
import json
import os
import stat
from pathlib import Path


def socket_access(path: str) -> dict[str, int | bool | list[int]]:
    value = Path(path).stat()
    if os.access in os.supports_effective_ids:
        permitted = os.access(path, os.W_OK, effective_ids=True)
    elif os.getuid() == os.geteuid() and os.getgid() == os.getegid():
        permitted = os.access(path, os.W_OK)
    else:
        raise ValueError("effective socket permissions cannot be observed")
    return {
        "socket": stat.S_ISSOCK(value.st_mode),
        "socket_uid": value.st_uid,
        "socket_gid": value.st_gid,
        "socket_mode": stat.S_IMODE(value.st_mode),
        "effective_uid": os.geteuid(),
        "effective_gid": os.getegid(),
        "supplementary_groups": sorted(os.getgroups()),
        "connect_permission": permitted,
    }


def require_socket_access(path: str) -> None:
    try:
        observed = socket_access(path)
    except (OSError, ValueError):
        raise ValueError("controller Docker socket is missing or unreadable") from None
    if not observed["socket"] or not observed["connect_permission"]:
        raise ValueError(
            "controller Docker socket access denied; inspect the mounted socket GID "
            "inside this container and grant only that existing group to the controller"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("socket", nargs="?", default="/var/run/docker.sock")
    args = parser.parse_args()
    try:
        observed = socket_access(args.socket)
    except (OSError, ValueError):
        raise SystemExit("controller socket observation unavailable") from None
    print(json.dumps(observed, sort_keys=True))
    if not observed["socket"] or not observed["connect_permission"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
