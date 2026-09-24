"""同定したパラメータをプロジェクト直下へ一元記録する(運用時の最終成果物)。

フェーズ1(粉体パラメータ)とフェーズ2(壁面摩擦係数)の同定値が別々の出力先に散らばると
「結局いくつになったのか」が分からなくなるため、``identified_parameters.json``へ集約する。
履歴も残すので、やり直した場合に前回値と比較できる。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

IDENTIFIED_PARAMETERS_FILENAME = "identified_parameters.json"

PHASE1 = "phase1"
PHASE2 = "phase2"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_identified_parameters(project_directory: str | Path) -> dict[str, Any]:
    """``identified_parameters.json``を読み込む(無ければ空の器を返す)。"""
    path = Path(project_directory) / IDENTIFIED_PARAMETERS_FILENAME
    if not path.is_file():
        return {"phases": {}, "history": []}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"phases": {}, "history": []}
    if not isinstance(loaded, dict):
        return {"phases": {}, "history": []}
    loaded.setdefault("phases", {})
    loaded.setdefault("history", [])
    return loaded


def record_identified_parameters(
    project_directory: str | Path,
    phase: str,
    values: dict[str, Any],
    *,
    source: str | Path | None = None,
    targets: dict[str, Any] | None = None,
    notes: str | None = None,
) -> Path:
    """フェーズの同定値を記録し、``identified_parameters.json``のパスを返す。"""
    if not values:
        raise ValueError("同定値が空です。")

    directory = Path(project_directory)
    directory.mkdir(parents=True, exist_ok=True)
    document = load_identified_parameters(directory)

    entry: dict[str, Any] = {
        "phase": phase,
        "values": values,
        "recorded_at": _now(),
    }
    if source is not None:
        entry["source"] = str(source)
    if targets is not None:
        entry["targets"] = targets
    if notes is not None:
        entry["notes"] = notes

    document["phases"][phase] = entry
    document["history"].append(entry)
    document["updated_at"] = entry["recorded_at"]

    path = directory / IDENTIFIED_PARAMETERS_FILENAME
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def format_identified_parameters(document: dict[str, Any]) -> str:
    """同定値を人が読める1行/項目の形式へ整形する。"""
    phases = document.get("phases") or {}
    if not phases:
        return "同定値はまだ記録されていません。"

    lines: list[str] = []
    for phase in sorted(phases):
        entry = phases[phase]
        lines.append(f"[{phase}] 記録日時: {entry.get('recorded_at', '-')}")
        for key, value in (entry.get("values") or {}).items():
            lines.append(f"    {key} = {value}")
        if entry.get("targets"):
            lines.append(f"    目標値: {entry['targets']}")
        if entry.get("source"):
            lines.append(f"    取得元: {entry['source']}")
        if entry.get("notes"):
            lines.append(f"    備考: {entry['notes']}")
    return "\n".join(lines)
