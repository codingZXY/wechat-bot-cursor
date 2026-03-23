"""CLI entry: login | run."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from wx_claw_bot.auth.qr_login import run_login
from wx_claw_bot.bot import run_bot
from wx_claw_bot.config import load_settings


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wx-claw-bot", description="WeChat ilink + Cursor Agent bridge")
    parser.add_argument(
        "--log-level",
        default=None,
        help="Override WX_CLAW_BOT_LOG_LEVEL (DEBUG, INFO, …)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_login = sub.add_parser("login", help="QR login and save credentials")
    p_login.add_argument(
        "--base-url",
        default=None,
        help="Override WX_CLAW_BOT_BASE_URL",
    )

    sub.add_parser("run", help="Long-poll and reply via Cursor agent")

    args = parser.parse_args(argv)

    settings = load_settings()
    log_level = args.log_level or settings.log_level
    _setup_logging(log_level)

    if args.cmd == "login":
        base = (args.base_url or settings.base_url).strip()
        return asyncio.run(
            run_login(
                base_url=base.rstrip("/"),
                state_dir=settings.state_dir,
                route_tag=settings.route_tag,
                poll_timeout_sec=float(settings.qrcode_status_timeout_sec),
            )
        )

    if args.cmd == "run":
        try:
            return asyncio.run(run_bot(settings))
        except KeyboardInterrupt:
            logging.getLogger(__name__).info("Stopped")
            return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
