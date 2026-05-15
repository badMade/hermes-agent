"""Tests for DingTalk gateway setup authorization defaults."""

import sys
from types import ModuleType

import pytest

pytest.importorskip("yaml")


def test_dingtalk_qr_setup_does_not_enable_allow_all(monkeypatch):
    """QR setup must not silently authorize every DingTalk sender."""
    from hermes_cli import gateway
    from hermes_cli import setup as setup_prompts

    saved_values = {}
    auth_module = ModuleType("hermes_cli.dingtalk_auth")
    auth_module.dingtalk_qr_auth = lambda: ("client-id", "client-secret")

    monkeypatch.setitem(sys.modules, "hermes_cli.dingtalk_auth", auth_module)
    monkeypatch.setattr(gateway, "get_env_value", lambda _name: None)
    monkeypatch.setattr(gateway, "save_env_value", saved_values.__setitem__)
    monkeypatch.setattr(setup_prompts, "prompt_choice", lambda *_args, **_kwargs: 0)

    gateway._setup_dingtalk()

    assert saved_values["DINGTALK_CLIENT_ID"] == "client-id"
    assert saved_values["DINGTALK_CLIENT_SECRET"] == "client-secret"
    assert "DINGTALK_ALLOW_ALL_USERS" not in saved_values


def test_dingtalk_manual_setup_does_not_enable_allow_all(monkeypatch):
    """Manual setup must not silently authorize every DingTalk sender."""
    from hermes_cli import gateway
    from hermes_cli import setup as setup_prompts

    saved_values = {}
    standard_setup_calls = []

    monkeypatch.setattr(gateway, "get_env_value", lambda _name: None)
    monkeypatch.setattr(gateway, "save_env_value", saved_values.__setitem__)
    monkeypatch.setattr(setup_prompts, "prompt_choice", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(
        gateway,
        "_setup_standard_platform",
        lambda platform: standard_setup_calls.append(platform["key"]),
    )

    gateway._setup_dingtalk()

    assert standard_setup_calls == ["dingtalk"]
    assert "DINGTALK_ALLOW_ALL_USERS" not in saved_values
