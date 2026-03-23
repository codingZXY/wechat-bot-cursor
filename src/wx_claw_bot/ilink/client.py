"""HTTP client for WeChat ilink bot API."""

from __future__ import annotations

import base64
import json
import secrets
import uuid
from typing import Any

import httpx

from wx_claw_bot import __version__
from wx_claw_bot.ilink.types import (
    BaseInfo,
    GetUpdatesResp,
    QRCodeResponse,
    QRStatusResponse,
    SendMessageReq,
    WeixinMessage,
)

# Align with openclaw-weixin session guard
SESSION_EXPIRED_ERRCODE = -14
DEFAULT_BOT_TYPE = "3"


def random_wechat_uin() -> str:
    """X-WECHAT-UIN: random uint32 as decimal string, UTF-8, then base64."""
    uint32 = int.from_bytes(secrets.token_bytes(4), "big") % (2**32)
    return base64.b64encode(str(uint32).encode("utf-8")).decode("ascii")


def build_base_info() -> BaseInfo:
    return {"channel_version": __version__}


def _ensure_trailing_slash(url: str) -> str:
    return url if url.endswith("/") else f"{url}/"


class IlinkClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        route_tag: str | None = None,
        api_timeout_sec: float = 15.0,
    ) -> None:
        self.base_url = _ensure_trailing_slash(base_url.rstrip("/"))
        self.token = token
        self.route_tag = route_tag.strip() if route_tag else None
        self.api_timeout_sec = api_timeout_sec

    def _auth_headers(self, body: bytes) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Content-Length": str(len(body)),
            "X-WECHAT-UIN": random_wechat_uin(),
        }
        if self.token and self.token.strip():
            headers["Authorization"] = f"Bearer {self.token.strip()}"
        if self.route_tag:
            headers["SKRouteTag"] = self.route_tag
        return headers

    def _route_headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.route_tag:
            h["SKRouteTag"] = self.route_tag
        return h

    async def get_bot_qrcode(self, bot_type: str = DEFAULT_BOT_TYPE) -> QRCodeResponse:
        from urllib.parse import quote

        u = f"{self.base_url}ilink/bot/get_bot_qrcode?bot_type={quote(bot_type, safe='')}"
        async with httpx.AsyncClient(timeout=self.api_timeout_sec) as client:
            r = await client.get(u, headers=self._route_headers())
            r.raise_for_status()
            data = r.json()
        return data  # type: ignore[return-value]

    async def get_qrcode_status(
        self,
        qrcode: str,
        *,
        long_poll_timeout_sec: float,
    ) -> QRStatusResponse:
        from urllib.parse import quote

        u = f"{self.base_url}ilink/bot/get_qrcode_status?qrcode={quote(qrcode, safe='')}"
        headers = {"iLink-App-ClientVersion": "1", **self._route_headers()}
        timeout = httpx.Timeout(long_poll_timeout_sec, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(u, headers=headers)
                r.raise_for_status()
                return r.json()  # type: ignore[return-value]
        except httpx.TimeoutException:
            return {"status": "wait"}

    async def get_updates(
        self,
        get_updates_buf: str,
        *,
        long_poll_timeout_ms: int | None = None,
    ) -> GetUpdatesResp:
        timeout_ms = long_poll_timeout_ms if long_poll_timeout_ms and long_poll_timeout_ms > 0 else 35_000
        timeout_sec = max(timeout_ms / 1000.0 + 5.0, 10.0)
        body_obj: dict[str, Any] = {
            "get_updates_buf": get_updates_buf or "",
            "base_info": build_base_info(),
        }
        body = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
        headers = self._auth_headers(body)
        url = f"{self.base_url}ilink/bot/getupdates"
        try:
            async with httpx.AsyncClient(timeout=timeout_sec) as client:
                r = await client.post(url, headers=headers, content=body)
                r.raise_for_status()
                return r.json()  # type: ignore[return-value]
        except httpx.TimeoutException:
            return {"ret": 0, "msgs": [], "get_updates_buf": get_updates_buf}

    async def send_message(self, req: SendMessageReq) -> None:
        body_obj: dict[str, Any] = dict(req)
        if "base_info" not in body_obj:
            body_obj["base_info"] = build_base_info()
        body = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
        headers = self._auth_headers(body)
        url = f"{self.base_url}ilink/bot/sendmessage"
        async with httpx.AsyncClient(timeout=self.api_timeout_sec) as client:
            r = await client.post(url, headers=headers, content=body)
            r.raise_for_status()

    @staticmethod
    def build_text_send(
        *,
        to_user_id: str,
        text: str,
        context_token: str,
        client_id: str | None = None,
    ) -> SendMessageReq:
        """BOT text message (message_type=2, state=FINISH=2)."""
        cid = client_id or str(uuid.uuid4())
        msg: WeixinMessage = {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": cid,
            "message_type": 2,
            "message_state": 2,
            "context_token": context_token,
            "item_list": [{"type": 1, "text_item": {"text": text}}],
        }
        return {"msg": msg, "base_info": build_base_info()}
