"""Application settings (env + defaults)."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_state_dir() -> Path:
    env = os.environ.get("WX_CLAW_BOT_STATE_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".wx-claw-bot"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WX_CLAW_BOT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    base_url: str = Field(default="https://ilinkai.weixin.qq.com")
    state_dir: Path = Field(default_factory=default_state_dir)
    route_tag: str | None = Field(default=None)

    # Cursor Agent CLI (env: WX_CLAW_BOT_AGENT_CMD, _WORKSPACE, _AGENT_MODEL, _AGENT_TIMEOUT_SEC)
    agent_cmd: str = Field(default="agent")
    workspace: Path | None = Field(default=None)
    agent_model: str | None = Field(default=None)
    agent_timeout_sec: int = Field(default=600, ge=1)

    # Cursor Agent 持久会话（用于复用对话上下文）
    # 注意：Cursor CLI 具体参数名可能会随版本变动，因此提供可配置的 resume 参数。
    # 默认不开启，避免你未确认参数名时导致 agent 直接失败。
    cursor_persistent_session: bool = Field(default=True)
    cursor_resume_chat_id_arg: str = Field(default="--resume")

    # Long poll
    get_updates_timeout_sec: int = Field(default=40, ge=5, le=120)
    qrcode_status_timeout_sec: int = Field(default=36, ge=5, le=120)

    # Messaging
    # Outbound text max chunk length.
    # WeChat display/UX may effectively limit visible text per message,
    # so keep it small to avoid truncation.
    outbound_chunk_size: int = Field(default=1000, ge=200, le=8000)

    log_level: str = Field(default="INFO")

    # Echo WeChat user text / agent subprocess / final reply to the terminal (stdout/stderr)
    terminal_verbose: bool = Field(default=True)
    terminal_max_inbound_preview: int = Field(default=2000, ge=200, le=50_000)

    # Security: comma-separated from_user_id; if non-empty, only these users are handled
    allow_from: str = Field(default="")


def _agent_cmd_from_environ() -> str | None:
    """
    Read agent command from OS environment explicitly.

    Some Windows setups (GUI apps / old shells) do not inject User-level env vars
    into the process until restart; pydantic-settings only sees ``os.environ``.
    Also accept a shorter alias used in docs.
    """
    for key in ("WX_CLAW_BOT_AGENT_CMD", "CURSOR_AGENT_CMD"):
        v = os.environ.get(key, "").strip()
        if v:
            return v
    return None


def load_settings() -> Settings:
    cmd = _agent_cmd_from_environ()
    if cmd:
        return Settings(agent_cmd=cmd)
    return Settings()
