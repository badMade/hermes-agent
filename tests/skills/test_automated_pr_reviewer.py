"""Security-property tests for skills/github/automated-pr-reviewer/SKILL.md.

Verifies that the automated PR reviewer skill uses only static diff review
(gh pr diff) and never checks out or executes code from untrusted PR branches.
"""

import re
from pathlib import Path


SKILL_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "github"
    / "automated-pr-reviewer"
    / "SKILL.md"
)


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


class TestStaticDiffApproach:
    """The review workflow must use gh pr diff and not check out PR code."""

    def test_uses_gh_pr_diff(self):
        """Skill must obtain the PR diff via 'gh pr diff' (static approach)."""
        assert "gh pr diff" in _skill_text(), (
            "Skill must use 'gh pr diff' to obtain the diff without checking out the branch"
        )

    def test_no_git_checkout_of_pr_branch(self):
        """Skill must not instruct the agent to run git checkout on the PR branch."""
        text = _skill_text()
        # 'git checkout' appearing in an instruction block would indicate local checkout
        # Allow it only if it appears in a negation context ("Do not ... checkout")
        checkout_matches = [
            m.start()
            for m in re.finditer(r"\bgit checkout\b", text)
        ]
        for pos in checkout_matches:
            surrounding = text[max(0, pos - 80): pos + 40].lower()
            assert "do not" in surrounding or "not " in surrounding, (
                f"Found 'git checkout' in a non-negation context near: "
                f"{text[max(0, pos-40):pos+40]!r}"
            )

    def test_prohibits_executing_pr_code(self):
        """Skill must explicitly prohibit running tests, linters, or build commands."""
        text = _skill_text()
        # The skill should contain explicit prohibitions on code execution
        assert re.search(
            r"[Dd]o not.{0,80}(test|lint|build|run|execut)",
            text,
        ), "Skill should explicitly prohibit running tests/linters/build commands from the PR"

    def test_prohibits_checkout(self):
        """The security requirements section must say not to checkout PR code."""
        text = _skill_text()
        assert re.search(
            r"[Dd]o not.{0,60}checkout",
            text,
        ), "Skill security requirements must explicitly forbid checking out PR code"


class TestAuthorizationRequirements:
    """The workflow must validate author_association before acting on a review request."""

    def test_validates_author_association(self):
        """Skill must check author_association to verify trusted commenters."""
        assert "author_association" in _skill_text(), (
            "Skill must validate author_association to prevent unauthorized review requests"
        )

    def test_requires_trusted_associations(self):
        """Skill must enumerate trusted roles: OWNER, MEMBER, or COLLABORATOR."""
        text = _skill_text()
        assert "OWNER" in text, "Skill must accept OWNER as a trusted role"
        assert "MEMBER" in text, "Skill must accept MEMBER as a trusted role"
        assert "COLLABORATOR" in text, "Skill must accept COLLABORATOR as a trusted role"

    def test_skips_fork_prs_by_default(self):
        """Skill must skip fork PRs whose head comes from a different repository."""
        text = _skill_text()
        assert re.search(r"fork|head.{0,30}repo|HEAD_REPO", text, re.IGNORECASE), (
            "Skill must include fork-detection logic to skip untrusted external PRs"
        )


class TestLabelingSequence:
    """The jules-reviewed label must only be added after the review is complete."""

    def test_labels_after_review_not_before(self):
        """Skill must label the PR only after the static review is complete."""
        text = _skill_text()
        assert re.search(
            r"(after|once).{0,80}(review|complete|done).{0,80}label"
            r"|label.{0,80}(after|once).{0,80}(review|complete)",
            text,
            re.IGNORECASE | re.DOTALL,
        ), "Skill must add the label only after the review completes, not before"

    def test_uses_jules_reviewed_label(self):
        """Skill must use the 'jules-reviewed' label to prevent re-processing."""
        assert "jules-reviewed" in _skill_text(), (
            "Skill must use 'jules-reviewed' label to track reviewed PRs"
        )


class TestSkillMetadata:
    """Basic SKILL.md frontmatter checks."""

    def test_skill_file_exists(self):
        """The automated-pr-reviewer SKILL.md must exist."""
        assert SKILL_PATH.exists(), f"SKILL.md not found at {SKILL_PATH}"

    def test_has_name_field(self):
        """Frontmatter must include a name field."""
        assert "name: automated-pr-reviewer" in _skill_text()

    def test_has_version_field(self):
        """Frontmatter must include a version field."""
        assert re.search(r"^version:", _skill_text(), re.MULTILINE), (
            "SKILL.md frontmatter must include a version field"
        )
