"""Cursor agent bridge helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wx_claw_bot.bridge.cursor_agent import (
    parse_agent_stdout,
    parse_agent_stdout_payload,
    extract_agent_conversation_id,
    resolve_agent_executable,
    split_agent_cmd,
)


def test_parse_agent_stdout_plain_json_string() -> None:
    assert parse_agent_stdout(json.dumps({"text": "ok"})) == "ok"


def test_parse_agent_stdout_raw_when_not_json() -> None:
    assert parse_agent_stdout("plain\n") == "plain"


def test_parse_agent_stdout_nested_result() -> None:
    assert parse_agent_stdout(json.dumps({"result": "x"})) == "x"


def test_parse_agent_stdout_payload_extracts_conversation_id() -> None:
    reply, meta = parse_agent_stdout_payload(json.dumps({"text": "ok", "conversation_id": "c1"}))
    assert reply == "ok"
    assert extract_agent_conversation_id(meta) == "c1"


def test_parse_agent_stdout_payload_nested_id() -> None:
    reply, meta = parse_agent_stdout_payload(json.dumps({"result": "ok", "meta": {"chatId": "c2"}}))
    assert reply == "ok"
    assert extract_agent_conversation_id(meta) == "c2"


def test_split_agent_cmd_simple() -> None:
    assert split_agent_cmd("agent") == ["agent"]


def test_split_agent_cmd_quoted_windows_style(monkeypatch) -> None:
    monkeypatch.setattr("wx_claw_bot.bridge.cursor_agent.os.name", "nt")
    assert split_agent_cmd('"C:\\Program Files\\agent\\agent.exe"') == [
        "C:\\Program Files\\agent\\agent.exe",
    ]


def test_resolve_agent_executable_explicit_path(tmp_path) -> None:
    exe = tmp_path / "agent.exe"
    exe.write_bytes(b"")
    resolved = resolve_agent_executable(str(exe))
    assert Path(resolved) == exe.resolve()


def test_resolve_agent_executable_not_found(monkeypatch) -> None:
    monkeypatch.setattr("wx_claw_bot.bridge.cursor_agent.shutil.which", lambda *_a, **_k: None)
    monkeypatch.setattr("wx_claw_bot.bridge.cursor_agent.os.name", "posix")
    with pytest.raises(FileNotFoundError, match="找不到 Cursor CLI"):
        resolve_agent_executable("no-such-agent-binary-xyz")


def test_resolve_agent_executable_irm_windows_install_dir(tmp_path, monkeypatch) -> None:
    """Official win32 install script uses %LOCALAPPDATA%\\cursor-agent\\agent.cmd."""
    monkeypatch.setattr("wx_claw_bot.bridge.cursor_agent.os.name", "nt")
    monkeypatch.setattr("wx_claw_bot.bridge.cursor_agent.shutil.which", lambda *_a, **_k: None)
    local = tmp_path / "AppData" / "Local"
    agent = local / "cursor-agent" / "agent.cmd"
    agent.parent.mkdir(parents=True)
    agent.write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    out = resolve_agent_executable("agent")
    assert Path(out) == agent.resolve()
