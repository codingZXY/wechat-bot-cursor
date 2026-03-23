"""ilink helpers and send payload shape."""

from __future__ import annotations

import base64

from wx_claw_bot.ilink.client import IlinkClient, build_base_info, random_wechat_uin


def test_random_wechat_uin_is_base64_decimal_uint32() -> None:
    for _ in range(20):
        s = random_wechat_uin()
        raw = base64.b64decode(s.encode("ascii")).decode("utf-8")
        assert raw.isdigit()
        n = int(raw)
        assert 0 <= n < 2**32


def test_build_base_info_has_version() -> None:
    d = build_base_info()
    assert "channel_version" in d
    assert d["channel_version"]


def test_build_text_send_shape() -> None:
    req = IlinkClient.build_text_send(
        to_user_id="abc@im.wechat",
        text="hello",
        context_token="ctx-token",
        client_id="fixed-id",
    )
    msg = req["msg"]
    assert msg["to_user_id"] == "abc@im.wechat"
    assert msg["context_token"] == "ctx-token"
    assert msg["message_type"] == 2
    assert msg["message_state"] == 2
    assert msg["client_id"] == "fixed-id"
    assert msg["item_list"][0]["type"] == 1
    assert msg["item_list"][0]["text_item"]["text"] == "hello"
    assert "base_info" in req
