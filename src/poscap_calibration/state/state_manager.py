"""status.jsonの読み書きと、再開時の前工程整合性チェック(FR-21)。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATUS_FILENAME = "status.json"

STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_RUNNING = "running"
STATUS_SKIPPED = "skipped"
#: 未着手(ファイルが存在しない)。進捗表示でのみ使う。
STATUS_PENDING = "pending"


def write_status(directory: str | Path, status: dict[str, Any]) -> Path:
    """工程フォルダへ``status.json``を書き出す。"""
    status_path = Path(directory) / STATUS_FILENAME
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return status_path


def read_status(directory: str | Path) -> dict[str, Any]:
    """工程フォルダの``status.json``を読み込む。"""
    status_path = Path(directory) / STATUS_FILENAME
    if not status_path.is_file():
        raise FileNotFoundError(f"status.jsonが見つかりません: {status_path}")
    return json.loads(status_path.read_text(encoding="utf-8"))
