import io
import tarfile
from pathlib import Path

import pytest

from scripts import install_psutil_android


def _write_tar(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def test_verify_archive_hash_rejects_substituted_archive(tmp_path: Path) -> None:
    archive = tmp_path / "psutil.tar.gz"
    archive.write_bytes(b"not the pinned psutil sdist")

    with pytest.raises(RuntimeError, match="hash mismatch"):
        install_psutil_android._verify_archive_hash(archive)


def test_safe_extract_tar_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "psutil.tar.gz"
    _write_tar(archive, {"../escaped": b"owned"})

    with tarfile.open(archive) as tar, pytest.raises(RuntimeError, match="unsafe"):
        install_psutil_android._safe_extract_tar(tar, tmp_path / "extract")

    assert not (tmp_path / "escaped").exists()


def test_safe_extract_tar_extracts_regular_members(tmp_path: Path) -> None:
    archive = tmp_path / "psutil.tar.gz"
    _write_tar(archive, {"psutil-7.2.2/psutil/_common.py": b"ok"})
    destination = tmp_path / "extract"
    destination.mkdir()

    with tarfile.open(archive) as tar:
        install_psutil_android._safe_extract_tar(tar, destination)

    assert (destination / "psutil-7.2.2" / "psutil" / "_common.py").read_bytes() == b"ok"
