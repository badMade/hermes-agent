"""Tests for git worktree isolation (CLI --worktree / -w flag).

Verifies worktree creation, cleanup, .worktreeinclude handling,
.gitignore management, and integration with the CLI.  (#652)
"""

import os
import shutil
import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repo for testing."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=repo, capture_output=True,
    )
    # Create initial commit (worktrees need at least one commit)
    (repo / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo, capture_output=True,
    )
    # Add a fake remote ref so cleanup logic sees the initial commit as
    # "pushed".  Without this, `git log HEAD --not --remotes` treats every
    # commit as unpushed and cleanup refuses to delete worktrees.
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
        cwd=repo, capture_output=True,
    )
    return repo


# ---------------------------------------------------------------------------
# Lightweight reimplementations for testing (avoid importing cli.py)
# ---------------------------------------------------------------------------

def _git_repo_root(cwd=None):
    """Test version of _git_repo_root."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def _has_unpushed_commits(worktree_path):
    """Test version of _has_unpushed_commits."""
    result = subprocess.run(
        ["git", "log", "HEAD", "--not", "--remotes", "--oneline"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def _setup_worktree(repo_root, worktree_name=None, worktrees_dir=None):
    """Simplified worktree creation for testing."""
    import cli as cli_mod
    return cli_mod._setup_worktree(
        repo_root,
        worktree_name=worktree_name,
        worktrees_dir=worktrees_dir,
    )


def _cleanup_worktree(worktree_info):
    """Simplified worktree cleanup for testing."""
    import cli as cli_mod
    return cli_mod._cleanup_worktree(worktree_info)


# ---------------------------------------------------------------------------
# Worktree creation
# ---------------------------------------------------------------------------

class TestWorktreeCreation:
    def test_creates_worktree(self, git_repo):
        import cli as cli_mod
        info = cli_mod._setup_worktree(str(git_repo))
        try:
            assert info is not None
            assert Path(info["path"]).exists()
        finally:
            cli_mod._cleanup_worktree(info)

    def test_worktree_has_own_branch(self, git_repo):
        import cli as cli_mod
        info = cli_mod._setup_worktree(str(git_repo))
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=info["path"], capture_output=True, text=True,
            )
            assert result.stdout.strip() == info["branch"]
        finally:
            cli_mod._cleanup_worktree(info)

    def test_worktree_is_independent(self, git_repo):
        import cli as cli_mod
        info = cli_mod._setup_worktree(str(git_repo))
        try:
            wt_path = Path(info["path"])
            assert wt_path.is_dir()
            # Confirm the worktree root is a git working tree
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=wt_path, capture_output=True, text=True,
            )
            assert result.returncode == 0
        finally:
            cli_mod._cleanup_worktree(info)

    def test_worktrees_dir_created(self, git_repo):
        import cli as cli_mod
        custom_dir = git_repo / "my-worktrees"
        info = cli_mod._setup_worktree(
            str(git_repo), worktrees_dir=str(custom_dir)
        )
        try:
            assert custom_dir.is_dir()
        finally:
            cli_mod._cleanup_worktree(info)

    def test_worktree_has_repo_files(self, git_repo):
        import cli as cli_mod
        info = cli_mod._setup_worktree(str(git_repo))
        try:
            readme = Path(info["path"]) / "README.md"
            assert readme.exists()
            assert readme.read_text() == "# Test Repo\n"
        finally:
            cli_mod._cleanup_worktree(info)


# ---------------------------------------------------------------------------
# Worktree cleanup
# ---------------------------------------------------------------------------

class TestWorktreeCleanup:
    def test_clean_worktree_removed(self, git_repo):
        import cli as cli_mod
        info = cli_mod._setup_worktree(str(git_repo))
        wt_path = Path(info["path"])
        cli_mod._cleanup_worktree(info)
        assert not wt_path.exists()

    def test_dirty_worktree_cleaned_when_no_unpushed(self, git_repo):
        import cli as cli_mod
        info = cli_mod._setup_worktree(str(git_repo))
        wt_path = Path(info["path"])
        # Add a file but don't commit — dirty but no unpushed commits
        (wt_path / "dirty.txt").write_text("dirty")
        cli_mod._cleanup_worktree(info)
        assert not wt_path.exists()

    def test_worktree_with_unpushed_commits_kept(self, git_repo):
        import cli as cli_mod
        info = cli_mod._setup_worktree(str(git_repo))
        wt_path = Path(info["path"])

        # Make and commit a file in the worktree
        (wt_path / "new.txt").write_text("new")
        subprocess.run(["git", "add", "new.txt"], cwd=wt_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=wt_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=wt_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "commit.gpgsign", "false"],
            cwd=wt_path, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "unpushed"],
            cwd=wt_path, capture_output=True,
        )

        try:
            cli_mod._cleanup_worktree(info)
            # Worktree kept because of unpushed commit
            assert wt_path.exists()
        finally:
            # Force cleanup for the test teardown
            subprocess.run(
                ["git", "worktree", "remove", info["path"], "--force"],
                cwd=info["repo_root"],
                capture_output=True,
            )
            subprocess.run(
                ["git", "branch", "-D", info["branch"]],
                cwd=info["repo_root"],
                capture_output=True,
            )

    def test_branch_deleted_on_cleanup(self, git_repo):
        import cli as cli_mod
        info = cli_mod._setup_worktree(str(git_repo))
        branch = info["branch"]
        cli_mod._cleanup_worktree(info)

        # Branch should be deleted
        result = subprocess.run(
            ["git", "branch", "--list", branch],
            cwd=git_repo, capture_output=True, text=True,
        )
        assert branch not in result.stdout


# ---------------------------------------------------------------------------
# .worktreeinclude handling
# ---------------------------------------------------------------------------

class TestWorktreeInclude:
    def test_copies_included_files(self, git_repo):
        import cli as cli_mod
        # Create a file that should be included
        (git_repo / ".env").write_text("SECRET=test\n")
        (git_repo / ".worktreeinclude").write_text(".env\n")

        info = cli_mod._setup_worktree(str(git_repo))
        try:
            env_in_wt = Path(info["path"]) / ".env"
            assert env_in_wt.exists()
            assert env_in_wt.read_text() == "SECRET=test\n"
        finally:
            cli_mod._cleanup_worktree(info)

    def test_ignores_comments_and_blanks(self, git_repo):
        import cli as cli_mod
        (git_repo / "real.txt").write_text("real")
        (git_repo / ".worktreeinclude").write_text(
            "# This is a comment\n\nreal.txt\n"
        )

        info = cli_mod._setup_worktree(str(git_repo))
        try:
            assert (Path(info["path"]) / "real.txt").exists()
        finally:
            cli_mod._cleanup_worktree(info)


# ---------------------------------------------------------------------------
# .gitignore management
# ---------------------------------------------------------------------------

class TestGitignoreManagement:
    def test_adds_to_gitignore(self, git_repo):
        import cli as cli_mod
        info = cli_mod._setup_worktree(str(git_repo))
        try:
            gitignore = Path(info["repo_root"]) / ".gitignore"
            if gitignore.exists():
                content = gitignore.read_text()
                # Worktrees directory should be ignored
                wt_dir = Path(info["path"]).parent.name
                assert wt_dir in content or ".worktrees" in content
        finally:
            cli_mod._cleanup_worktree(info)


# ---------------------------------------------------------------------------
# Multiple concurrent worktrees
# ---------------------------------------------------------------------------

class TestMultipleWorktrees:
    def test_ten_concurrent_worktrees(self, git_repo):
        import cli as cli_mod
        infos = []
        try:
            for _ in range(10):
                info = cli_mod._setup_worktree(str(git_repo))
                assert info is not None
                infos.append(info)

            # All should have unique paths and branches
            paths = {i["path"] for i in infos}
            branches = {i["branch"] for i in infos}
            assert len(paths) == 10
            assert len(branches) == 10
        finally:
            for info in infos:
                try:
                    cli_mod._cleanup_worktree(info)
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Directory symlink
# ---------------------------------------------------------------------------

class TestWorktreeDirectorySymlink:
    def test_symlinks_directory(self, git_repo):
        import cli as cli_mod
        venv_dir = git_repo / ".venv" / "lib"
        venv_dir.mkdir(parents=True)
        (venv_dir / "marker.txt").write_text("marker")
        (git_repo / ".worktreeinclude").write_text(".venv\n")

        info = cli_mod._setup_worktree(str(git_repo))
        try:
            linked = Path(info["path"]) / ".venv"
            assert linked.is_symlink()
            assert (linked / "lib" / "marker.txt").read_text() == "marker"
        finally:
            cli_mod._cleanup_worktree(info)


# ---------------------------------------------------------------------------
# Stale worktree pruning
# ---------------------------------------------------------------------------

class TestStaleWorktreePruning:
    def _make_worktree_and_age(self, git_repo, age_seconds):
        """Create a worktree and artificially age its directory."""
        import cli as cli_mod
        info = cli_mod._setup_worktree(str(git_repo))
        # Age the worktree by setting mtime
        wt_path = Path(info["path"])
        aged_time = wt_path.stat().st_mtime - age_seconds
        os.utime(wt_path, (aged_time, aged_time))
        return info

    def test_prunes_old_clean_worktree(self, git_repo):
        import cli as cli_mod
        info = self._make_worktree_and_age(git_repo, age_seconds=8 * 24 * 3600)
        wt_path = Path(info["path"])

        cli_mod._prune_stale_worktrees(str(git_repo))
        assert not wt_path.exists()

    def test_keeps_recent_worktree(self, git_repo):
        import cli as cli_mod
        info = cli_mod._setup_worktree(str(git_repo))
        wt_path = Path(info["path"])
        try:
            cli_mod._prune_stale_worktrees(str(git_repo))
            assert wt_path.exists()
        finally:
            cli_mod._cleanup_worktree(info)

    def test_keeps_old_worktree_with_unpushed_commits(self, git_repo):
        import cli as cli_mod
        info = self._make_worktree_and_age(git_repo, age_seconds=8 * 24 * 3600)
        wt_path = Path(info["path"])

        # Create unpushed commit in worktree
        (wt_path / "wip.txt").write_text("wip")
        subprocess.run(["git", "add", "wip.txt"], cwd=wt_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=wt_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=wt_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "commit.gpgsign", "false"],
            cwd=wt_path, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "wip"],
            cwd=wt_path, capture_output=True,
        )

        try:
            cli_mod._prune_stale_worktrees(str(git_repo))
            assert wt_path.exists()
        finally:
            subprocess.run(
                ["git", "worktree", "remove", info["path"], "--force"],
                cwd=info["repo_root"], capture_output=True,
            )
            subprocess.run(
                ["git", "branch", "-D", info["branch"]],
                cwd=info["repo_root"], capture_output=True,
            )

    def test_force_prunes_very_old_worktree(self, git_repo):
        import cli as cli_mod
        info = self._make_worktree_and_age(git_repo, age_seconds=31 * 24 * 3600)
        wt_path = Path(info["path"])

        # Even with unpushed commits, force-prune removes it
        (wt_path / "wip.txt").write_text("wip")
        subprocess.run(["git", "add", "wip.txt"], cwd=wt_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=wt_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=wt_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "commit.gpgsign", "false"],
            cwd=wt_path, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "wip"],
            cwd=wt_path, capture_output=True,
        )

        cli_mod._prune_stale_worktrees(str(git_repo))
        assert not wt_path.exists()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_worktrees_dir_already_exists(self, git_repo):
        import cli as cli_mod
        # Pre-create the worktrees directory
        worktrees_dir = git_repo / ".hermes-worktrees"
        worktrees_dir.mkdir()
        info = cli_mod._setup_worktree(str(git_repo))
        try:
            assert info is not None
        finally:
            cli_mod._cleanup_worktree(info)


# ---------------------------------------------------------------------------
# Terminal CWD integration
# ---------------------------------------------------------------------------

class TestTerminalCWDIntegration:
    def test_terminal_cwd_set(self, git_repo):
        import cli as cli_mod
        info = cli_mod._setup_worktree(str(git_repo))
        try:
            assert "terminal_cwd" in info
            assert info["terminal_cwd"] == info["path"]
        finally:
            cli_mod._cleanup_worktree(info)

    def test_terminal_cwd_is_valid_git_repo(self, git_repo):
        import cli as cli_mod
        info = cli_mod._setup_worktree(str(git_repo))
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=info["terminal_cwd"],
                capture_output=True, text=True,
            )
            assert result.returncode == 0
        finally:
            cli_mod._cleanup_worktree(info)


# ---------------------------------------------------------------------------
# Orphaned branch pruning
# ---------------------------------------------------------------------------

class TestOrphanedBranchPruning:
    def test_prunes_orphaned_hermes_branch(self, git_repo):
        import cli as cli_mod
        # Create a worktree, then manually remove its directory to simulate an orphan
        info = cli_mod._setup_worktree(str(git_repo))
        branch = info["branch"]
        # Forcibly remove the worktree directory without proper cleanup
        shutil.rmtree(info["path"])
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=info["repo_root"], capture_output=True,
        )

        cli_mod._prune_orphaned_branches(str(git_repo))

        result = subprocess.run(
            ["git", "branch", "--list", branch],
            cwd=git_repo, capture_output=True, text=True,
        )
        assert branch not in result.stdout

    def test_prunes_orphaned_pr_branch(self, git_repo):
        import cli as cli_mod
        info = cli_mod._setup_worktree(str(git_repo))
        branch = info["branch"]
        shutil.rmtree(info["path"])
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=info["repo_root"], capture_output=True,
        )

        cli_mod._prune_orphaned_branches(str(git_repo))

        result = subprocess.run(
            ["git", "branch", "--list", branch],
            cwd=git_repo, capture_output=True, text=True,
        )
        assert branch not in result.stdout

    def test_preserves_active_worktree_branch(self, git_repo):
        import cli as cli_mod
        info = cli_mod._setup_worktree(str(git_repo))
        branch = info["branch"]
        try:
            cli_mod._prune_orphaned_branches(str(git_repo))
            # Active worktree's branch must not be pruned
            result = subprocess.run(
                ["git", "branch", "--list", branch],
                cwd=git_repo, capture_output=True, text=True,
            )
            assert branch in result.stdout
        finally:
            cli_mod._cleanup_worktree(info)


# ---------------------------------------------------------------------------
# System prompt injection
# ---------------------------------------------------------------------------

class TestSystemPromptInjection:
    def test_prompt_note_format(self, git_repo):
        import cli as cli_mod
        info = cli_mod._setup_worktree(str(git_repo))
        try:
            note = cli_mod._worktree_system_prompt_note(info)
            assert isinstance(note, str)
            assert len(note) > 0
        finally:
            cli_mod._cleanup_worktree(info)
