"""Invoke Cursor `agent` CLI and parse printed output."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from wx_claw_bot.config import Settings

logger = logging.getLogger(__name__)

MAX_STDOUT_CHARS = 2_000_000

CURSOR_AGENT_SESSION_DIRNAME = "cursor_agent_sessions"
CURSOR_AGENT_CHAT_ID_FILE_PREFIX = "chat_id_"


def split_agent_cmd(cmd: str) -> list[str]:
    """Split command line for subprocess; Windows-friendly for quoted paths."""
    cmd = cmd.strip()
    if not cmd:
        return []
    # Whole-line quoting: "C:\Program Files\agent\agent.exe"
    if len(cmd) >= 2 and cmd[0] == cmd[-1] and cmd[0] in "\"'":
        cmd = cmd[1:-1].strip()
    # Windows: paths with spaces must be one argv element; shlex splits on spaces.
    if os.name == "nt" and " " in cmd:
        return [cmd]
    if os.name == "nt":
        return shlex.split(cmd, posix=False)
    return shlex.split(cmd)


def _windows_agent_path_guesses() -> list[Path]:
    """Common Cursor CLI locations when not on PATH (Windows)."""
    guesses: list[Path] = []
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        lp = Path(local)
        # Official Windows install script: irm 'https://cursor.com/install?win32=true' | iex
        guesses.append(lp / "cursor-agent" / "agent.cmd")
        guesses.append(lp / "cursor-agent" / "agent.exe")
        base = lp / "Programs"
        for name in ("cursor", "Cursor"):
            guesses.append(base / name / "resources" / "app" / "bin" / "agent.exe")
    prof = os.environ.get("USERPROFILE", "").strip()
    if prof:
        guesses.append(Path(prof) / ".cursor" / "bin" / "agent.exe")
    return guesses


def resolve_agent_executable(argv0: str) -> str:
    """
    Resolve the first argv token to an existing executable.

    On Windows, bare ``agent`` is often missing from PATH; we try ``.exe`` / ``.cmd``
    and a few default install directories.
    """
    raw = argv0.strip()
    if not raw:
        raise RuntimeError("WX_CLAW_BOT_AGENT_CMD is empty")

    # Explicit relative/absolute path
    if os.path.isabs(raw) or os.sep in raw or (os.name == "nt" and "/" in raw):
        p = Path(raw).expanduser()
        if p.is_file():
            return str(p.resolve())
        raise FileNotFoundError(
            f"WX_CLAW_BOT_AGENT_CMD 指向的文件不存在: {p}. "
            "请改为正确的 agent 可执行文件路径。"
        )

    found = shutil.which(raw)
    if found:
        return found

    if os.name == "nt":
        for suffix in (".exe", ".cmd", ".bat"):
            found = shutil.which(f"{raw}{suffix}")
            if found:
                return found
        for guess in _windows_agent_path_guesses():
            if guess.is_file():
                logger.info("Resolved agent via default path guess: %s", guess)
                return str(guess.resolve())

    raise FileNotFoundError(
        "找不到 Cursor CLI（agent）。请任选其一：\n"
        "1) 用官方脚本安装后，常见路径为：\n"
        "   %LOCALAPPDATA%\\cursor-agent\\agent.cmd\n"
        "2) 设置用户环境变量 WX_CLAW_BOT_AGENT_CMD 为该文件的完整路径后，"
        "务必完全退出并重新打开终端（或 Cursor），再运行 wx-claw-bot；\n"
        "3) 或将 cursor-agent 目录加入系统 PATH。\n"
        f"（当前尝试的命令名为: {raw!r}）"
    )


def parse_agent_stdout(stdout: str) -> str:
    """Prefer JSON `--print` payload; fall back to raw stdout."""
    reply, _meta = parse_agent_stdout_payload(stdout)
    return reply


def parse_agent_stdout_payload(stdout: str) -> tuple[str, dict[str, Any]]:
    """Parse Cursor Agent `--print --output-format json` payload.

    Returns:
        reply_text: best-effort assistant text extracted from common shapes
        meta: parsed JSON object (empty if stdout is not JSON)
    """
    s = stdout.strip()
    if not s:
        return "", {}
    try:
        data: Any = json.loads(s)
    except json.JSONDecodeError:
        logger.warning("Agent output is not JSON; using raw stdout.")
        return s, {}

    if isinstance(data, str):
        return data, {}
    if isinstance(data, dict):
        for key in ("result", "message", "content", "text", "output", "response"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val, data
        # Nested common shapes
        msg = data.get("messages")
        if isinstance(msg, list) and msg:
            last = msg[-1]
            if isinstance(last, dict):
                c = last.get("content")
                if isinstance(c, str):
                    return c, data
        return json.dumps(data, ensure_ascii=False), data
    if isinstance(data, list) and data:
        return json.dumps(data, ensure_ascii=False), {"data": data}
    return s, {}


def _safe_conversation_key(conversation_key: str) -> str:
    # Keep it compatible with filesystem and consistent across runs.
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in conversation_key)[:120]


def cursor_agent_chat_id_path(state_dir: Path, conversation_key: str) -> Path:
    return (
        state_dir
        / CURSOR_AGENT_SESSION_DIRNAME
        / f"{CURSOR_AGENT_CHAT_ID_FILE_PREFIX}{_safe_conversation_key(conversation_key)}.txt"
    )


def _deep_find_first_str_by_keys(obj: Any, keys: set[str]) -> str | None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k in keys and isinstance(v, str) and v.strip():
                return v.strip()
        # Recurse into values
        for v in obj.values():
            found = _deep_find_first_str_by_keys(v, keys)
            if found:
                return found
        return None
    if isinstance(obj, list):
        for it in obj:
            found = _deep_find_first_str_by_keys(it, keys)
            if found:
                return found
        return None
    return None


def extract_agent_conversation_id(meta: Any) -> str | None:
    """Extract Cursor Agent conversation/chat id from parsed JSON meta."""
    candidates = {
        "conversation_id",
        "conversationId",
        "chat_id",
        "chatId",
        "session_id",
        "sessionId",
        "agent_session_id",
        "agentSessionId",
    }
    return _deep_find_first_str_by_keys(meta, candidates)


def _pump_pipe(
    pipe: Any,
    chunks: list[bytes],
    *,
    echo_stream: Any | None,
) -> None:
    try:
        while True:
            data = pipe.read(4096)
            if not data:
                break
            chunks.append(data)
            if echo_stream is not None:
                echo_stream.write(data)
                echo_stream.flush()
    finally:
        try:
            pipe.close()
        except OSError:
            pass


def _run_agent_subprocess(
    cmd: list[str],
    *,
    timeout_sec: float,
    stream_to_terminal: bool,
) -> tuple[int, str, str]:
    """
    Run agent; optionally stream raw stdout/stderr to the terminal while collecting
    full output for JSON parsing.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        bufsize=0,
    )
    out_chunks: list[bytes] = []
    err_chunks: list[bytes] = []
    out_echo = sys.stdout.buffer if stream_to_terminal else None
    err_echo = sys.stderr.buffer if stream_to_terminal else None

    t_out = threading.Thread(
        target=_pump_pipe,
        args=(proc.stdout, out_chunks),
        kwargs={"echo_stream": out_echo},
        daemon=True,
    )
    t_err = threading.Thread(
        target=_pump_pipe,
        args=(proc.stderr, err_chunks),
        kwargs={"echo_stream": err_echo},
        daemon=True,
    )
    t_out.start()
    t_err.start()

    try:
        proc.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        t_out.join(timeout=5)
        t_err.join(timeout=5)
        raise TimeoutError(f"agent timed out after {timeout_sec}s") from None

    t_out.join()
    t_err.join()

    stdout = b"".join(out_chunks).decode("utf-8", errors="replace")
    stderr = b"".join(err_chunks).decode("utf-8", errors="replace")
    return proc.returncode, stdout, stderr


async def run_cursor_agent(prompt: str, settings: Settings, *, conversation_key: str) -> str:
    parts = split_agent_cmd(settings.agent_cmd)
    if not parts:
        raise RuntimeError("WX_CLAW_BOT_AGENT_CMD is empty")

    resolved = resolve_agent_executable(parts[0])
    cmd: list[str] = [
        resolved,
        *parts[1:],
        "-p",
        prompt,
        "--print",
        "--output-format",
        "json",
        "--trust",
    ]
    if settings.workspace is not None:
        cmd.extend(["--workspace", str(settings.workspace.expanduser().resolve())])
    if settings.agent_model:
        cmd.extend(["--model", settings.agent_model])

    logger.debug("Running agent: %s", cmd[:6])

    stream = settings.terminal_verbose
    if stream:
        print("\n--- Cursor Agent 子进程输出（stdout / stderr 实时）---\n", flush=True)

    cmd_with_resume = None
    prev_chat_id = ""
    if settings.cursor_persistent_session:
        path = cursor_agent_chat_id_path(settings.state_dir, conversation_key)
        try:
            prev_chat_id = path.read_text(encoding="utf-8").strip()
        except OSError:
            prev_chat_id = ""
        if prev_chat_id:
            arg = settings.cursor_resume_chat_id_arg.strip()
            if "{chat_id}" in arg:
                cmd_with_resume = cmd + [arg.format(chat_id=prev_chat_id)]
            else:
                cmd_with_resume = cmd + [arg, prev_chat_id]

    def _run_one(cmd_to_run: list[str]) -> tuple[int, str, str]:
        return _run_agent_subprocess(
            cmd_to_run,
            timeout_sec=float(settings.agent_timeout_sec),
            stream_to_terminal=stream,
        )

    attempts: list[list[str]] = []
    if cmd_with_resume is not None:
        attempts.append(cmd_with_resume)
    attempts.append(cmd)

    last_err: str = ""
    for i, cmd_try in enumerate(attempts):
        try:
            if i == 0:
                logger.debug("Running agent attempt %d (with persistent resume)", i + 1)
            else:
                logger.debug("Running agent attempt %d (fallback without resume)", i + 1)
            returncode, stdout, stderr = await asyncio.to_thread(lambda: _run_one(cmd_try))
        except Exception as e:
            last_err = str(e)
            continue

        if stderr.strip() and not stream:
            logger.debug("agent stderr: %s", stderr[:2000])

        if returncode != 0:
            err = (stderr or stdout or "").strip() or f"exit {returncode}"
            last_err = err[:4000]
            continue

        out = stdout or ""
        if len(out) > MAX_STDOUT_CHARS:
            logger.warning("Truncating agent stdout from %d chars", len(out))
            out = out[:MAX_STDOUT_CHARS]

        reply_text, meta = parse_agent_stdout_payload(out)
        if settings.cursor_persistent_session:
            new_chat_id = extract_agent_conversation_id(meta)
            if new_chat_id:
                logger.debug("Cursor Agent chat_id updated: %s -> %s", prev_chat_id or None, new_chat_id)
                chat_path = cursor_agent_chat_id_path(settings.state_dir, conversation_key)
                try:
                    chat_path.parent.mkdir(parents=True, exist_ok=True)
                    chat_path.write_text(new_chat_id, encoding="utf-8")
                except OSError:
                    logger.warning("Failed to persist chat_id to %s", chat_path)

        return reply_text

    raise RuntimeError(f"agent failed after attempts: {last_err[:4000]}")
