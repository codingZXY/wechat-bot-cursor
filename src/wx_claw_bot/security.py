"""Sender allowlist for inbound messages."""

from __future__ import annotations


def parse_allow_from(raw: str) -> frozenset[str]:
    """Comma-separated Weixin user ids (e.g. xxx@im.wechat)."""
    if not raw or not raw.strip():
        return frozenset()
    return frozenset(x.strip() for x in raw.split(",") if x.strip())


def is_sender_allowed(from_user_id: str, allowlist: frozenset[str]) -> bool:
    """
    If allowlist is empty, allow everyone (dev convenience).
    If non-empty, only listed senders are allowed.
    """
    if not allowlist:
        return True
    return from_user_id in allowlist
