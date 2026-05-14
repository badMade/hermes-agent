import pytest

# Skip this test module if atroposlib is not installed (e.g. in some CI environments)
pytest.importorskip("atroposlib")

from environments.agentic_opd_env import _parse_hint_result

@pytest.mark.parametrize(
    "text, expected_score, expected_hint",
    [
        # Happy paths
        (r"\boxed{1}", 1, ""),
        (r"\boxed{-1}", -1, ""),
        (r"[HINT_START]This is a hint[HINT_END]", None, "This is a hint"),
        (r"\boxed{1} [HINT_START]This is a hint[HINT_END]", 1, "This is a hint"),
        (r"[HINT_START]This is a hint[HINT_END] \boxed{-1}", -1, "This is a hint"),

        # Multiline hint
        (
            "[HINT_START]\nLine 1\nLine 2\n[HINT_END]\n\\boxed{1}",
            1,
            "Line 1\nLine 2",
        ),

        # Invalid scores
        (r"\boxed{0}", None, ""),
        (r"\boxed{2}", None, ""),
        (r"\boxed{42}", None, ""),
        (r"\boxed{invalid}", None, ""),

        # Multiple matches (should take the last one)
        (r"\boxed{1} \boxed{-1}", -1, ""),
        (r"\boxed{-1} \boxed{1}", 1, ""),
        (r"[HINT_START]Hint 1[HINT_END] [HINT_START]Hint 2[HINT_END]", None, "Hint 2"),
        (
            r"\boxed{1} [HINT_START]Hint 1[HINT_END] \boxed{-1} [HINT_START]Hint 2[HINT_END]",
            -1,
            "Hint 2",
        ),

        # Empty and malformed inputs
        ("", None, ""),
        ("Some random text without any special formatting", None, ""),
        (r"\boxed{}", None, ""),
        (r"[HINT_START]Unclosed hint", None, ""),
        (r"Unopened hint[HINT_END]", None, ""),
    ],
)
def test_parse_hint_result(text: str, expected_score: int | None, expected_hint: str) -> None:
    score, hint = _parse_hint_result(text)
    assert score == expected_score
    assert hint == expected_hint
