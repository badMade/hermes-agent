#!/usr/bin/env python3
"""Install psutil on Termux/Android by patching upstream platform detection.

psutil's setup currently gates Linux sources behind
``sys.platform.startswith('linux')``. On Termux, Python reports
``sys.platform == 'android'``, so ``pip install psutil`` aborts with
"platform android is not supported" — even though psutil compiles fine
when the Linux source path is reused.

This script downloads the official psutil sdist, applies a one-line
patch (``LINUX = sys.platform.startswith(("linux", "android"))``), and
installs the patched tree with ``pip install --no-build-isolation``.

Usage:
    python scripts/install_psutil_android.py [--pip "/path/to/pip"] [--uv]

When neither flag is given, the script auto-detects ``uv`` on PATH and
falls back to ``<sys.executable> -m pip``.

This is a stopgap. Remove once psutil upstream merges
https://github.com/giampaolo/psutil/pull/2762 and ships a release.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

# Pin a version we know patches cleanly. Update when a newer psutil
# changes the marker line shape and we need to follow upstream.
PSUTIL_URL = (
    "https://files.pythonhosted.org/packages/aa/c6/"
    "d1ddf4abb55e93cebc4f2ed8b5d6dbad109ecb8d63748dd2b20ab5e57ebe/"
    "psutil-7.2.2.tar.gz"
)

MARKER = 'LINUX = sys.platform.startswith("linux")'
REPLACEMENT = 'LINUX = sys.platform.startswith(("linux", "android"))'


def _resolve_install_cmd(pip_arg: str | None, prefer_uv: bool) -> list[str]:
    if pip_arg:
        return pip_arg.split()
    if prefer_uv:
        uv = shutil.which("uv")
        if not uv:
            sys.exit("--uv requested but no uv on PATH")
        return [uv, "pip"]
    auto_uv = shutil.which("uv")
    if auto_uv:
        return [auto_uv, "pip"]
    return [sys.executable, "-m", "pip"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pip",
        help="Explicit installer command (e.g. '/usr/bin/uv pip' or 'python -m pip')",
    )
    parser.add_argument(
        "--uv",
        action="store_true",
        help="Force using uv (errors out if uv is not on PATH)",
    )
    args = parser.parse_args()

    install_cmd_prefix = _resolve_install_cmd(args.pip, args.uv)

    print(
        "→ Termux/Android: prebuilding psutil with Linux source path "
        "compatibility shim (see psutil#2762)..."
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / "psutil.tar.gz"
        urllib.request.urlretrieve(PSUTIL_URL, archive)
        with tarfile.open(archive) as tar:
            import os
            base_path = os.path.realpath(tmp_path)
            members = tar.getmembers()
            for member in members:
                if member.issym() or member.islnk() or not (member.isdir() or member.isreg()):
                    raise tarfile.TarError(
                        f"refusing to extract non-file member: {member.name!r}"
                    )
                try:
                    target_path = os.path.realpath(os.path.join(base_path, member.name))
                    if os.path.commonpath([base_path, target_path]) != base_path:
                        raise tarfile.TarError(
                            f"refusing to extract unsafe path: {member.name!r}"
                        )
                except ValueError:
                    raise tarfile.TarError(
                        f"refusing to extract unsafe path: {member.name!r}"
                    )
            try:
                tar.extractall(tmp_path, filter="data")
            except TypeError:
                # Python < 3.12 — no filter kwarg
                for member in members:
                    tar.extract(member, tmp_path)

        try:
            src_root = next(
                p for p in tmp_path.iterdir()
                if p.is_dir() and p.name.startswith("psutil-")
            )
        except StopIteration:
            sys.exit("psutil sdist did not contain a psutil-* directory")

        common_py = src_root / "psutil" / "_common.py"
        content = common_py.read_text(encoding="utf-8")
        if MARKER not in content:
            sys.exit(
                "psutil Android compatibility patch marker not found — "
                "upstream may have changed the LINUX detection line. "
                "Update MARKER/REPLACEMENT in this script."
            )
        common_py.write_text(content.replace(MARKER, REPLACEMENT), encoding="utf-8")

        cmd = install_cmd_prefix + ["install", "--no-build-isolation", str(src_root)]
        print(f"  $ {' '.join(cmd)}")
        result = subprocess.run(cmd)
        if result.returncode != 0:
            return result.returncode

    print("✓ psutil installed via Android compatibility shim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
