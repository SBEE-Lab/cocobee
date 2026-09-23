"""Configuration comes from the environment, and an empty variable is not a value."""

from __future__ import annotations

import pytest

from slack_index import config


def test_a_set_variable_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-from-env")

    assert config.setting("SLACK_BOT_TOKEN") == "xoxb-from-env"
    assert config.bot_token() == "xoxb-from-env"


def test_an_empty_variable_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A leftover .env — which the cocoindex CLI auto-loads — must not blank a value out.
    monkeypatch.setenv("SLACK_INDEX_POLL_SECONDS", "")

    assert config.setting("SLACK_INDEX_POLL_SECONDS", "60") == "60"


def test_a_missing_token_says_where_it_comes_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="secrets.yaml"):
        config.bot_token()
