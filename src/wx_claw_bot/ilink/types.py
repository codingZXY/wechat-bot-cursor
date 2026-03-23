"""JSON shapes for WeChat ilink bot API (aligned with openclaw-weixin)."""

from __future__ import annotations

from typing import Any, TypedDict


class BaseInfo(TypedDict):
    channel_version: str


class TextItem(TypedDict, total=False):
    text: str


class MessageItem(TypedDict, total=False):
    type: int
    text_item: TextItem


class WeixinMessage(TypedDict, total=False):
    seq: int
    message_id: int
    client_id: str
    from_user_id: str
    to_user_id: str
    create_time_ms: int
    session_id: str
    message_type: int
    message_state: int
    item_list: list[MessageItem]
    context_token: str


class GetUpdatesReq(TypedDict, total=False):
    get_updates_buf: str
    base_info: BaseInfo


class GetUpdatesResp(TypedDict, total=False):
    ret: int
    errcode: int
    errmsg: str
    msgs: list[WeixinMessage]
    get_updates_buf: str
    longpolling_timeout_ms: int


class SendMessageReq(TypedDict, total=False):
    msg: WeixinMessage
    base_info: BaseInfo


# Login / QR
class QRCodeResponse(TypedDict, total=False):
    qrcode: str
    qrcode_img_content: str


class QRStatusResponse(TypedDict, total=False):
    status: str
    bot_token: str
    ilink_bot_id: str
    baseurl: str
    ilink_user_id: str


JSONDict = dict[str, Any]
