"""Regression tests for the NixOS container entrypoint shell snippet."""

from pathlib import Path


MODULE_SOURCE = Path(__file__).resolve().parents[1] / "nix" / "nixosModules.nix"


def test_container_entrypoint_chown_does_not_follow_symlinks():
    """The root entrypoint must not chown symlink targets outside HERMES_HOME."""
    source = MODULE_SOURCE.read_text()

    assert '-exec chown -h "$HERMES_UID:$HERMES_GID" {} +' in source
    assert '-exec chown "$HERMES_UID:$HERMES_GID" {} +' not in source


def test_container_entrypoint_repairs_user_or_group_mismatch():
    """Ownership repair should include group mismatches without touching mode bits."""
    source = MODULE_SOURCE.read_text()

    assert '\\( \\! -user "$HERMES_UID" -o \\! -group "$HERMES_GID" \\)' in source
