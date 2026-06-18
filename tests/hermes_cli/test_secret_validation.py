"""Tests for shared secret placeholder validation."""

import pytest

from hermes_cli.auth import has_usable_secret


@pytest.mark.parametrize(
    "value",
    [
        "your_api_key_here",
        "your-api-key-here",
        "${API_SERVER_KEY}",
    ],
)
def test_has_usable_secret_rejects_predictable_placeholders(value):
    assert has_usable_secret(value, min_length=8) is False


def test_has_usable_secret_accepts_generated_length_secret():
    assert has_usable_secret("a" * 32, min_length=8) is True
