"""Allowlist parsing."""

from __future__ import annotations

from wx_claw_bot.security import is_sender_allowed, parse_allow_from


def test_empty_allowlist_allows_all() -> None:
    assert is_sender_allowed("any@im.wechat", frozenset()) is True


def test_nonempty_allowlist() -> None:
    s = parse_allow_from("a@im.wechat, b@im.wechat ")
    assert is_sender_allowed("a@im.wechat", s) is True
    assert is_sender_allowed("c@im.wechat", s) is False
