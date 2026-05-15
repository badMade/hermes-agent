import importlib
import sys
from unittest.mock import patch


def _import_rl_cli():
    sys.modules.pop("rl_cli", None)
    return importlib.import_module("rl_cli")


def test_check_tinker_atropos_success(tmp_path):
    """Test successful case where submodule and environments dir exist."""
    project_root = tmp_path / "project"
    project_root.mkdir()
    tinker_path = project_root / "tinker-atropos"
    envs_path = tinker_path / "tinker_atropos" / "environments"
    envs_path.mkdir(parents=True)
    fake_file = str(project_root / "rl_cli.py")
    (project_root / "rl_cli.py").touch()

    (envs_path / "env1.py").touch()
    (envs_path / "env2.py").touch()
    (envs_path / "_hidden.py").touch()

    rl_cli = _import_rl_cli()

    with patch.object(rl_cli, "__file__", fake_file):
        ok, result = rl_cli.check_tinker_atropos()

    assert ok is True
    assert result["path"] == str(tinker_path)
    assert result["environments_count"] == 2


def test_check_tinker_atropos_no_submodule(tmp_path):
    """Test failure when tinker-atropos submodule is missing."""
    project_root = tmp_path / "project"
    project_root.mkdir()
    fake_file = str(project_root / "rl_cli.py")
    (project_root / "rl_cli.py").touch()

    rl_cli = _import_rl_cli()

    with patch.object(rl_cli, "__file__", fake_file):
        ok, result = rl_cli.check_tinker_atropos()

    assert ok is False
    assert "submodule not found" in result


def test_check_tinker_atropos_no_environments_dir(tmp_path):
    """Test failure when environments directory is missing."""
    project_root = tmp_path / "project"
    project_root.mkdir()
    tinker_path = project_root / "tinker-atropos"
    tinker_path.mkdir()
    fake_file = str(project_root / "rl_cli.py")
    (project_root / "rl_cli.py").touch()

    rl_cli = _import_rl_cli()

    with patch.object(rl_cli, "__file__", fake_file):
        ok, result = rl_cli.check_tinker_atropos()

    assert ok is False
    assert "environments directory not found" in result
