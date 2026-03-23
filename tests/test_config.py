"""Settings env wiring."""

from __future__ import annotations

import os

from wx_claw_bot.config import Settings, load_settings


def test_settings_allow_from_env(monkeypatch) -> None:
    monkeypatch.setenv("WX_CLAW_BOT_ALLOW_FROM", "u1@im.wechat,u2@im.wechat")
    s = Settings()
    assert "u1@im.wechat" in s.allow_from


def test_load_settings_cursor_agent_cmd_alias(monkeypatch) -> None:
    monkeypatch.delenv("WX_CLAW_BOT_AGENT_CMD", raising=False)
    monkeypatch.setenv("CURSOR_AGENT_CMD", r"C:\fake\agent.cmd")
    assert load_settings().agent_cmd == r"C:\fake\agent.cmd"


def test_load_settings_wx_claw_bot_agent_cmd_wins(monkeypatch) -> None:
    monkeypatch.setenv("WX_CLAW_BOT_AGENT_CMD", r"C:\a\agent.cmd")
    monkeypatch.setenv("CURSOR_AGENT_CMD", r"C:\b\agent.cmd")
    assert load_settings().agent_cmd == r"C:\a\agent.cmd"
