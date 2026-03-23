"""Persist ilink bot token and account metadata."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class Credentials:
    token: str
    base_url: str
    account_id: str
    user_id: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None and v != ""}


def credentials_path(state_dir: Path) -> Path:
    return state_dir / "credentials.json"


def ensure_state_dir(state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)


def save_credentials(state_dir: Path, creds: Credentials) -> None:
    ensure_state_dir(state_dir)
    path = credentials_path(state_dir)
    data = creds.to_json_dict()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_credentials(state_dir: Path) -> Credentials | None:
    path = credentials_path(state_dir)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    token = str(raw.get("token", "")).strip()
    base_url = str(raw.get("base_url", "")).strip()
    account_id = str(raw.get("account_id", "")).strip()
    if not token or not base_url or not account_id:
        return None
    uid = raw.get("user_id")
    user_id = str(uid).strip() if uid else None
    return Credentials(
        token=token,
        base_url=base_url,
        account_id=account_id,
        user_id=user_id or None,
    )
