import importlib.util
import io
import shutil
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "install_psutil_android.py"

spec = importlib.util.spec_from_file_location("install_psutil_android", SCRIPT_PATH)
install_psutil_android = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(install_psutil_android)


def _build_tar(tmp_path: Path, entries: list[dict[str, str]]) -> Path:
    archive = tmp_path / "psutil.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for entry in entries:
            info = tarfile.TarInfo(entry["name"])
            kind = entry["kind"]
            if kind == "dir":
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            elif kind == "file":
                data = entry["data"].encode("utf-8")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = entry["target"]
                tar.addfile(info)
            else:
                raise ValueError(f"unknown entry kind: {kind}")
    return archive


def _mock_download(monkeypatch, archive: Path) -> None:
    monkeypatch.setattr(
        install_psutil_android.urllib.request,
        "urlretrieve",
        lambda _url, dest: (shutil.copyfile(archive, dest), None),
    )


def test_rejects_symlink_members(tmp_path, monkeypatch):
    archive = _build_tar(
        tmp_path,
        [
            {"kind": "dir", "name": "psutil-7.2.2"},
            {"kind": "symlink", "name": "psutil-7.2.2/link", "target": "../escape"},
        ],
    )
    _mock_download(monkeypatch, archive)
    monkeypatch.setattr(sys, "argv", ["install_psutil_android.py"])

    with pytest.raises(
        tarfile.TarError,
        match="refusing to extract link or special member",
    ):
        install_psutil_android.main()


def test_typeerror_fallback_extracts_safe_members_individually(tmp_path, monkeypatch):
    archive = _build_tar(
        tmp_path,
        [
            {"kind": "dir", "name": "psutil-7.2.2"},
            {"kind": "dir", "name": "psutil-7.2.2/psutil"},
            {
                "kind": "file",
                "name": "psutil-7.2.2/psutil/_common.py",
                "data": install_psutil_android.MARKER,
            },
        ],
    )
    _mock_download(monkeypatch, archive)
    monkeypatch.setattr(sys, "argv", ["install_psutil_android.py"])
    monkeypatch.setattr(
        install_psutil_android.subprocess,
        "run",
        lambda _cmd: SimpleNamespace(returncode=0),
    )

    def _extractall(self, path=".", members=None, *, numeric_owner=False, filter=None):
        if filter == "data":
            raise TypeError("filter unsupported")
        raise AssertionError("fallback should not call extractall without a filter")

    monkeypatch.setattr(tarfile.TarFile, "extractall", _extractall)

    assert install_psutil_android.main() == 0
