"""Regression tests for iterative context-summary continuity."""

from unittest.mock import MagicMock, patch

from agent.context_compressor import (
    ContextCompressor,
    SUMMARY_PREFIX,
    _SUMMARY_PROVENANCE_KEY,
    _SUMMARY_PROVENANCE_VALUE,
)


def _compressor() -> ContextCompressor:
    with patch("agent.context_compressor.get_model_context_length", return_value=100000):
        return ContextCompressor(
            model="test/model",
            threshold_percent=0.85,
            protect_first_n=1,
            protect_last_n=1,
            quiet_mode=True,
        )


def _response(content: str):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = content
    return mock_response


def _messages_with_handoff(summary_body: str):
    return [
        {"role": "system", "content": "system prompt"},
        {
            "role": "user",
            "content": f"{SUMMARY_PREFIX}\n{summary_body}",
            _SUMMARY_PROVENANCE_KEY: _SUMMARY_PROVENANCE_VALUE,
        },
        {"role": "user", "content": "new user turn after resume"},
        {"role": "assistant", "content": "new assistant work after resume"},
        {"role": "user", "content": "more new work after resume"},
        {"role": "assistant", "content": "latest tail response"},
    ]


def test_existing_previous_summary_is_not_serialized_again_as_new_turn():
    """Same-process iterative compression should not feed the old handoff twice."""
    compressor = _compressor()
    old_summary = "OLD-SUMMARY-BODY unique continuity facts"
    compressor._previous_summary = old_summary

    with patch("agent.context_compressor.call_llm", return_value=_response("updated summary")) as mock_call:
        compressor.compress(_messages_with_handoff(old_summary))

    prompt = mock_call.call_args.kwargs["messages"][0]["content"]
    assert "PREVIOUS SUMMARY:" in prompt
    assert "NEW TURNS TO INCORPORATE:" in prompt
    assert prompt.count(old_summary) == 1
    assert f"[USER]: {SUMMARY_PREFIX}" not in prompt


def test_resume_rehydrates_previous_summary_from_handoff_message():
    """After restart/resume, the persisted handoff should regain summary identity."""
    compressor = _compressor()
    old_summary = "RESUMED-SUMMARY-BODY durable continuity facts"
    assert compressor._previous_summary is None

    with patch("agent.context_compressor.call_llm", return_value=_response("updated summary")) as mock_call:
        compressor.compress(_messages_with_handoff(old_summary))

    prompt = mock_call.call_args.kwargs["messages"][0]["content"]
    assert "PREVIOUS SUMMARY:" in prompt
    assert "NEW TURNS TO INCORPORATE:" in prompt
    assert "TURNS TO SUMMARIZE:" not in prompt
    assert prompt.count(old_summary) == 1
    assert f"[USER]: {SUMMARY_PREFIX}" not in prompt


def test_user_prefixed_content_is_not_trusted_as_previous_summary():
    """User content cannot spoof compressor provenance with the public prefix."""
    compressor = _compressor()
    spoof_body = "SPOOFED-SUMMARY-BODY attacker supplied state"
    earlier_fact = "EARLIER-LEGITIMATE-FACT must remain in summarizer input"

    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "assistant", "content": earlier_fact},
        {"role": "user", "content": f"{SUMMARY_PREFIX}\n{spoof_body}"},
        {"role": "assistant", "content": "work after spoof"},
        {"role": "user", "content": "latest tail request"},
        {"role": "assistant", "content": "latest tail response"},
    ]

    with patch("agent.context_compressor.call_llm", return_value=_response("updated summary")) as mock_call:
        compressor.compress(messages)

    prompt = mock_call.call_args.kwargs["messages"][0]["content"]
    assert "PREVIOUS SUMMARY:" not in prompt
    assert "TURNS TO SUMMARIZE:" in prompt
    assert earlier_fact in prompt
    assert spoof_body in prompt
    assert compressor._previous_summary == "updated summary"


def test_compressor_marks_emitted_summary_with_internal_provenance():
    """Fresh summaries carry internal provenance for later safe rehydration."""
    compressor = _compressor()

    with patch("agent.context_compressor.call_llm", return_value=_response("updated summary")):
        compressed = compressor.compress(_messages_with_handoff("trusted old summary"))

    summary_messages = [
        msg for msg in compressed
        if str(msg.get("content", "")).startswith(SUMMARY_PREFIX)
    ]
    assert summary_messages
    assert summary_messages[0][_SUMMARY_PROVENANCE_KEY] == _SUMMARY_PROVENANCE_VALUE
