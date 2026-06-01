"""Regression tests for install.sh Python environment sanitization.

When install.sh is launched from another Python-driven tool session, inherited
PYTHONPATH/PYTHONHOME can shadow the freshly installed checkout. The installer
must sanitize those vars both during installation and at runtime launch.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH_CANDIDATES = (REPO_ROOT / "scripts" / "install.sh", REPO_ROOT / "install.sh")
INSTALL_SH = next((path for path in INSTALL_SH_CANDIDATES if path.exists()), INSTALL_SH_CANDIDATES[0])


def test_install_script_unsets_pythonpath_and_pythonhome_early() -> None:
    assert INSTALL_SH.exists(), (
        f"install.sh not found at any expected location: "
        f"{', '.join(str(path) for path in INSTALL_SH_CANDIDATES)}"
    )
    text = INSTALL_SH.read_text()

    # During install, inherited Python env must be sanitized before pip/venv use.
    assert 'unset PYTHONPATH' in text
    assert 'unset PYTHONHOME' in text


def test_hermes_launcher_wrapper_clears_python_env_before_exec() -> None:
    assert INSTALL_SH.exists(), (
        f"install.sh not found at any expected location: "
        f"{', '.join(str(path) for path in INSTALL_SH_CANDIDATES)}"
    )
    text = INSTALL_SH.read_text()

    # Wrapper should clear env and forward args untouched to the venv entrypoint.
    assert 'cat > "$command_link_dir/hermes" <<EOF' in text
    assert 'unset PYTHONPATH' in text
    assert 'unset PYTHONHOME' in text
    assert 'exec "$HERMES_BIN" "\\$@"' in text
