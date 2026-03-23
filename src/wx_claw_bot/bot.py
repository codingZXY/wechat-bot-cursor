"""Long-poll loop: getUpdates -> Cursor agent -> sendMessage."""

from __future__ import annotations

import asyncio
import logging
import traceback
from pathlib import Path

from wx_claw_bot.auth.credentials import Credentials, load_credentials
from wx_claw_bot.bridge.cursor_agent import run_cursor_agent
from wx_claw_bot.config import Settings
from wx_claw_bot.ilink.client import SESSION_EXPIRED_ERRCODE, IlinkClient
from wx_claw_bot.ilink.types import WeixinMessage
from wx_claw_bot.security import is_sender_allowed, parse_allow_from

logger = logging.getLogger(__name__)

MESSAGE_TYPE_BOT = 2
ITEM_TEXT = 1
ITEM_IMAGE = 2
ITEM_VOICE = 3
ITEM_FILE = 4
ITEM_VIDEO = 5

MAX_CONSECUTIVE_FAILURES = 3
BACKOFF_SEC = 30
RETRY_SEC = 2
SESSION_PAUSE_SEC = 600

MEDIA_UNSUPPORTED_ZH = "当前版本仅支持文本消息，暂不支持图片、语音、视频或文件。"


def _terminal_chat_block(settings: Settings, heading: str, body: str, *, truncate: bool) -> None:
    """Print a clear block to stdout when terminal_verbose is enabled."""
    if not settings.terminal_verbose:
        return
    text = body or ""
    if truncate and len(text) > settings.terminal_max_inbound_preview:
        text = (
            text[: settings.terminal_max_inbound_preview]
            + f"\n…（终端仅展示前 {settings.terminal_max_inbound_preview} 字，完整内容已交给 Agent）"
        )
    sep = "=" * 60
    print(f"\n{sep}\n{heading}\n{'-' * 60}\n{text}\n{sep}\n", flush=True)


def _safe_account_file_id(account_id: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in account_id)[:120]


def sync_buf_path(state_dir: Path, account_id: str) -> Path:
    return state_dir / f"get_updates_buf_{_safe_account_file_id(account_id)}.txt"


def load_sync_buf(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_sync_buf(path: Path, buf: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(buf, encoding="utf-8")


def extract_inbound_body(msg: WeixinMessage) -> tuple[str, bool]:
    """
    Returns (text, has_non_text_media).
    """
    items = msg.get("item_list") or []
    texts: list[str] = []
    has_media = False
    for it in items:
        t = it.get("type")
        if t == ITEM_TEXT:
            ti = it.get("text_item") or {}
            tx = ti.get("text")
            if tx is not None:
                texts.append(str(tx))
        elif t in (ITEM_IMAGE, ITEM_VOICE, ITEM_FILE, ITEM_VIDEO):
            has_media = True
    return ("\n".join(texts).strip(), has_media)


def split_outbound_text(body: str, *, chunk_size: int) -> list[str]:
    """
    Split outbound text into chunks <= chunk_size.

    Prefer splitting by newline boundaries to avoid breaking sentences.
    If a single line is still longer than chunk_size, fall back to hard slicing.
    """
    if chunk_size <= 0:
        return [body]

    body = (body or "").strip()
    if not body:
        return []

    if len(body) <= chunk_size:
        return [body]

    lines = body.splitlines(keepends=True)
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for line in lines:
        # Hard fallback for extremely long single lines.
        if len(line) > chunk_size:
            flush()
            for i in range(0, len(line), chunk_size):
                chunks.append(line[i : i + chunk_size])
            continue

        if len(current) + len(line) <= chunk_size:
            current += line
        else:
            flush()
            current = line

    flush()
    return chunks


async def send_plain_text(
    client: IlinkClient,
    *,
    to_user_id: str,
    context_token: str,
    text: str,
    chunk_size: int,
) -> None:
    body = (text or "").strip()
    if not body:
        return

    for chunk in split_outbound_text(body, chunk_size=chunk_size):
        req = IlinkClient.build_text_send(
            to_user_id=to_user_id,
            text=chunk,
            context_token=context_token,
        )
        await client.send_message(req)


async def try_notify(
    client: IlinkClient,
    *,
    to_user_id: str,
    context_token: str | None,
    message: str,
    chunk_size: int,
) -> None:
    if not context_token:
        logger.warning("Cannot notify user: missing context_token")
        return
    try:
        await send_plain_text(
            client,
            to_user_id=to_user_id,
            context_token=context_token,
            text=message[:2000],
            chunk_size=chunk_size,
        )
    except Exception:
        logger.exception("Failed to send notice to %s", to_user_id)


async def process_user_message(
    msg: WeixinMessage,
    *,
    client: IlinkClient,
    settings: Settings,
    allowlist: frozenset[str],
) -> None:
    from_uid = (msg.get("from_user_id") or "").strip()
    ctx = (msg.get("context_token") or "").strip()

    if not from_uid:
        logger.debug("Skip message without from_user_id")
        return

    if not is_sender_allowed(from_uid, allowlist):
        logger.info("Dropped message from non-allowed sender: %s", from_uid)
        return

    mt = msg.get("message_type")
    if mt == MESSAGE_TYPE_BOT:
        return

    text, has_media = extract_inbound_body(msg)
    if not ctx:
        logger.warning("Inbound message missing context_token from=%s", from_uid)
        return

    if has_media and not text:
        await try_notify(
            client,
            to_user_id=from_uid,
            context_token=ctx,
            message=MEDIA_UNSUPPORTED_ZH,
            chunk_size=settings.outbound_chunk_size,
        )
        return

    if not text:
        logger.debug("Skip empty inbound (no text) from=%s", from_uid)
        return

    logger.info("Inbound from=%s text_len=%d", from_uid, len(text))
    _terminal_chat_block(
        settings,
        f"微信用户 {from_uid} 的消息",
        text,
        truncate=True,
    )

    try:
        reply = await run_cursor_agent(text, settings, conversation_key=from_uid)
    except Exception as e:
        logger.exception("Cursor agent error for %s", from_uid)
        err_msg = f"处理失败：{e!s}"[:1500]
        await try_notify(
            client,
            to_user_id=from_uid,
            context_token=ctx,
            message=err_msg,
            chunk_size=settings.outbound_chunk_size,
        )
        return

    _terminal_chat_block(
        settings,
        "发往微信的回复（解析 Agent 输出后）",
        reply or "（无输出）",
        truncate=False,
    )

    try:
        await send_plain_text(
            client,
            to_user_id=from_uid,
            context_token=ctx,
            text=reply or "（无输出）",
            chunk_size=settings.outbound_chunk_size,
        )
    except Exception:
        logger.exception("sendMessage failed to=%s", from_uid)
        await try_notify(
            client,
            to_user_id=from_uid,
            context_token=ctx,
            message=f"回复发送失败：{traceback.format_exc()[-800:]}",
            chunk_size=settings.outbound_chunk_size,
        )


def _is_api_error(resp: dict) -> bool:
    ret = resp.get("ret")
    err = resp.get("errcode")
    if ret is not None and ret != 0:
        return True
    if err is not None and err != 0:
        return True
    return False


def _is_session_expired(resp: dict) -> bool:
    if resp.get("errcode") == SESSION_EXPIRED_ERRCODE:
        return True
    if resp.get("ret") == SESSION_EXPIRED_ERRCODE:
        return True
    return False


async def run_forever(settings: Settings, creds: Credentials) -> None:
    allowlist = parse_allow_from(settings.allow_from)
    if allowlist:
        logger.info("Allowlist active (%d ids)", len(allowlist))
    else:
        logger.warning("Allowlist empty — any user can trigger agent (set WX_CLAW_BOT_ALLOW_FROM)")

    buf_path = sync_buf_path(settings.state_dir, creds.account_id)
    get_updates_buf = load_sync_buf(buf_path)

    client = IlinkClient(
        creds.base_url,
        token=creds.token,
        route_tag=settings.route_tag,
        api_timeout_sec=30.0,
    )

    next_timeout_ms = int(settings.get_updates_timeout_sec * 1000)
    consecutive_failures = 0

    while True:
        try:
            resp = await client.get_updates(
                get_updates_buf,
                long_poll_timeout_ms=next_timeout_ms,
            )
            lp = resp.get("longpolling_timeout_ms")
            if isinstance(lp, int) and lp > 0:
                next_timeout_ms = lp

            if _is_api_error(resp):
                if _is_session_expired(resp):
                    logger.error(
                        "Session expired (err %s). Pausing %ss — re-run login.",
                        SESSION_EXPIRED_ERRCODE,
                        SESSION_PAUSE_SEC,
                    )
                    consecutive_failures = 0
                    await asyncio.sleep(SESSION_PAUSE_SEC)
                    continue

                consecutive_failures += 1
                logger.error(
                    "getUpdates error ret=%s errcode=%s errmsg=%s (%s/%s)",
                    resp.get("ret"),
                    resp.get("errcode"),
                    resp.get("errmsg"),
                    consecutive_failures,
                    MAX_CONSECUTIVE_FAILURES,
                )
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    consecutive_failures = 0
                    await asyncio.sleep(BACKOFF_SEC)
                else:
                    await asyncio.sleep(RETRY_SEC)
                continue

            consecutive_failures = 0
            new_buf = resp.get("get_updates_buf")
            if isinstance(new_buf, str) and new_buf != "":
                save_sync_buf(buf_path, new_buf)
                get_updates_buf = new_buf

            for m in resp.get("msgs") or []:
                await process_user_message(m, client=client, settings=settings, allowlist=allowlist)

        except asyncio.CancelledError:
            raise
        except Exception:
            consecutive_failures += 1
            logger.exception(
                "Poll loop error (%s/%s)",
                consecutive_failures,
                MAX_CONSECUTIVE_FAILURES,
            )
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                consecutive_failures = 0
                await asyncio.sleep(BACKOFF_SEC)
            else:
                await asyncio.sleep(RETRY_SEC)


async def run_bot(settings: Settings) -> int:
    # Ensure Cursor Agent has a stable workspace root, so it can persist/load
    # any session state under that workspace (when supported by the installed CLI).
    if settings.workspace is None:
        settings.workspace = Path.cwd()
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    creds = load_credentials(settings.state_dir)
    if not creds:
        logger.error("No credentials. Run: wx-claw-bot login")
        return 1
    try:
        await run_forever(settings, creds)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Stopped by user")
        return 0
    return 0
