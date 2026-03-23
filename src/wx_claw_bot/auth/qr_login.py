"""QR code login flow (get_bot_qrcode + poll get_qrcode_status)."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

import qrcode

from wx_claw_bot.auth.credentials import Credentials, save_credentials
from wx_claw_bot.ilink.client import DEFAULT_BOT_TYPE, IlinkClient

logger = logging.getLogger(__name__)

MAX_QR_REFRESH = 3


def _print_qr_to_terminal(data: str) -> None:
    qr = qrcode.QRCode(border=1)
    qr.add_data(data)
    try:
        qr.make(fit=True)
    except qrcode.exceptions.DataOverflowError:
        print("二维码内容过长，请使用下方链接在微信中打开。", file=sys.stderr)
        return
    qr.print_ascii(invert=True, tty=sys.stdout.isatty())


async def wait_for_scan(
    client: IlinkClient,
    qrcode_value: str,
    *,
    poll_timeout_sec: float,
    total_timeout_sec: float = 480.0,
) -> Credentials | None:
    deadline = time.monotonic() + total_timeout_sec
    refresh_count = 0
    current_qr = qrcode_value

    while time.monotonic() < deadline:
        status = await client.get_qrcode_status(current_qr, long_poll_timeout_sec=poll_timeout_sec)
        st = status.get("status", "wait")
        if st == "wait":
            await asyncio.sleep(0.2)
            continue
        if st == "scaned":
            print("\n已扫码，请在手机上确认…", flush=True)
            await asyncio.sleep(0.2)
            continue
        if st == "expired":
            refresh_count += 1
            if refresh_count > MAX_QR_REFRESH:
                print("二维码多次过期，请重新运行 login。", file=sys.stderr)
                return None
            print("\n二维码已过期，正在刷新…", flush=True)
            qr_data = await client.get_bot_qrcode(DEFAULT_BOT_TYPE)
            current_qr = str(qr_data.get("qrcode", ""))
            url = qr_data.get("qrcode_img_content")
            if url:
                print(f"新二维码链接: {url}", flush=True)
                _print_qr_to_terminal(str(url))
            if not current_qr:
                return None
            continue
        if st == "confirmed":
            token = status.get("bot_token")
            bot_id = status.get("ilink_bot_id")
            baseurl = (status.get("baseurl") or "").strip() or client.base_url.rstrip("/")
            user_id = status.get("ilink_user_id")
            if not token or not bot_id:
                print("登录确认但缺少 token 或 bot_id。", file=sys.stderr)
                return None
            if not baseurl.startswith("http"):
                baseurl = client.base_url.rstrip("/")
            return Credentials(
                token=str(token),
                base_url=baseurl if baseurl.endswith("/") else f"{baseurl}/",
                account_id=str(bot_id),
                user_id=str(user_id) if user_id else None,
            )
        await asyncio.sleep(0.5)

    print("等待扫码超时。", file=sys.stderr)
    return None


async def run_login(
    *,
    base_url: str,
    state_dir: Path,
    route_tag: str | None,
    poll_timeout_sec: float,
) -> int:
    client = IlinkClient(base_url, route_tag=route_tag)
    print("正在获取登录二维码…", flush=True)
    try:
        qr_data = await client.get_bot_qrcode(DEFAULT_BOT_TYPE)
    except Exception as e:
        print(f"获取二维码失败: {e}", file=sys.stderr)
        return 1

    qrcode_value = str(qr_data.get("qrcode", ""))
    img_url = qr_data.get("qrcode_img_content")
    if img_url:
        print("请使用微信扫描下方二维码（或打开链接）完成授权：\n", flush=True)
        _print_qr_to_terminal(str(img_url))
        print(f"\n链接: {img_url}\n", flush=True)
    if not qrcode_value:
        print("服务端未返回有效 qrcode。", file=sys.stderr)
        return 1

    print("等待扫码确认…", flush=True)
    creds = await wait_for_scan(client, qrcode_value, poll_timeout_sec=poll_timeout_sec)
    if not creds:
        return 1

    save_credentials(state_dir, creds)
    print(f"已保存凭证到 {state_dir / 'credentials.json'}", flush=True)
    if creds.user_id:
        print(
            f"提示: 可将允许列表设为 WX_CLAW_BOT_ALLOW_FROM={creds.user_id}",
            flush=True,
        )
    return 0
