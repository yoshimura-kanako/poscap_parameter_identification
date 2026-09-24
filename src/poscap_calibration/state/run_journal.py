"""実行中のフェーズ・工程を逐次記録する実行ジャーナル(運用時の進捗把握用)。

プロジェクト直下へ次の2ファイルを出力する。

``run_journal.jsonl``
    1行1イベントの追記専用ログ。途中でプロセスが落ちても書き込み済みの行は残る。
``progress.json``
    「今どこを実行しているか」と各フェーズ・工程の状態のスナップショット。
    イベントごとに上書きするため、別プロセスから``cat``するだけで現況が分かる。

``get_journal()``は未設定時に何も書かないインスタンスを返すため、
ワークフロー側は有効化の有無を気にせず記録処理を書ける。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from poscap_calibration.state.state_manager import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
)

logger = logging.getLogger(__name__)

JOURNAL_FILENAME = "run_journal.jsonl"
PROGRESS_FILENAME = "progress.json"

#: ログ行へ付与する「現在のフェーズ/工程」。別スレッド・別タスクでも混ざらないようContextVarで持つ。
_current_scope: ContextVar[tuple[str | None, str | None]] = ContextVar(
    "poscap_current_scope", default=(None, None)
)


def current_scope() -> tuple[str | None, str | None]:
    """現在実行中の(フェーズ名, 工程名)を返す。"""
    return _current_scope.get()


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class RunJournal:
    """フェーズ・工程の開始/終了と中間結果を記録する。

    ``project_directory``が``None``の場合はファイルを書かず、呼び出しは全て無視される
    (単体テストやライブラリ利用時に副作用を出さないため)。
    """

    def __init__(
        self, project_directory: str | Path | None = None, *, run_id: str | None = None
    ) -> None:
        self._directory = Path(project_directory) if project_directory is not None else None
        self.run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self._lock = threading.Lock()
        self._progress: dict[str, Any] = {"phases": {}}

        if self._directory is None:
            return

        self._directory.mkdir(parents=True, exist_ok=True)
        self._progress = self._load_progress()
        # 再開時も過去フェーズの履歴を残したいので、phasesは読み込んだものを引き継ぐ。
        self._progress["phases"] = self._progress.get("phases") or {}
        self._progress["run_id"] = self.run_id
        self._progress["run_started_at"] = _now()
        self._progress["current"] = None
        self._write_progress()

    # --- パス ---------------------------------------------------------
    @property
    def journal_path(self) -> Path | None:
        return None if self._directory is None else self._directory / JOURNAL_FILENAME

    @property
    def progress_path(self) -> Path | None:
        return None if self._directory is None else self._directory / PROGRESS_FILENAME

    # --- 記録 ---------------------------------------------------------
    def event(self, kind: str, message: str | None = None, **details: Any) -> None:
        """単発イベントを追記する。"""
        phase, step = current_scope()
        record = {
            "time": _now(),
            "run_id": self.run_id,
            "kind": kind,
            "phase": details.pop("phase", phase),
            "step": details.pop("step", step),
            "message": message,
        }
        if details:
            record["details"] = details
        self._append(record)

    def progress(self, message: str, **details: Any) -> None:
        """進行中の状況をログとジャーナルの両方へ出す(``今何を実行しているか``用)。"""
        logger.info("%s", message)
        self.event("progress", message, **details)
        phase, step = current_scope()
        self._set_current(phase=phase, step=step, message=message)

    def record_result(self, name: str, value: Any, **details: Any) -> None:
        """中間結果(数値・ファイルパス等)を記録する。"""
        self.event("result", name, value=value, **details)
        with self._lock:
            results = self._progress.setdefault("results", {})
            results[name] = {"value": value, "time": _now(), **details}
            self._write_progress_locked()

    @contextmanager
    def phase(self, phase: str, title: str | None = None, **details: Any) -> Iterator[RunJournal]:
        """フェーズの開始・終了を記録するコンテキストマネージャ。"""
        label = title or phase
        entry = self._phase_entry(phase)
        entry.update(
            {
                "title": label,
                "status": STATUS_RUNNING,
                "started_at": _now(),
                "finished_at": None,
                "error": None,
                "run_id": self.run_id,
            }
        )
        token = _current_scope.set((phase, None))
        self._set_current(phase=phase, message=label, started_at=entry["started_at"])
        logger.info("=== フェーズ開始: %s ===", label)
        self.event("phase_start", label, **details)
        try:
            yield self
        except BaseException as error:
            entry["status"] = STATUS_FAILED
            entry["error"] = f"{type(error).__name__}: {error}"
            entry["finished_at"] = _now()
            logger.error("=== フェーズ失敗: %s (%s) ===", label, entry["error"])
            self.event("phase_failed", label, error=entry["error"])
            raise
        else:
            entry["status"] = STATUS_COMPLETED
            entry["finished_at"] = _now()
            logger.info("=== フェーズ完了: %s ===", label)
            self.event("phase_end", label)
        finally:
            _current_scope.reset(token)
            self._set_current()

    @contextmanager
    def step(
        self,
        step: str,
        title: str | None = None,
        *,
        index: int | None = None,
        total: int | None = None,
        **details: Any,
    ) -> Iterator[RunJournal]:
        """工程の開始・終了を記録するコンテキストマネージャ。"""
        phase, _ = current_scope()
        label = title or step
        if index is not None and total is not None:
            label = f"{label} ({index}/{total})"

        entry = self._step_entry(phase, step)
        entry.update(
            {
                "title": label,
                "status": STATUS_RUNNING,
                "started_at": _now(),
                "finished_at": None,
                "error": None,
            }
        )
        token = _current_scope.set((phase, step))
        self._set_current(
            phase=phase, step=step, message=label, started_at=entry["started_at"]
        )
        logger.info("--- 開始: %s ---", label)
        self.event("step_start", label, index=index, total=total, **details)
        try:
            yield self
        except BaseException as error:
            entry["status"] = STATUS_FAILED
            entry["error"] = f"{type(error).__name__}: {error}"
            entry["finished_at"] = _now()
            logger.error("--- 失敗: %s (%s) ---", label, entry["error"])
            self.event("step_failed", label, error=entry["error"])
            raise
        else:
            entry["status"] = STATUS_COMPLETED
            entry["finished_at"] = _now()
            logger.info("--- 完了: %s ---", label)
            self.event("step_end", label)
        finally:
            _current_scope.reset(token)
            self._set_current(phase=phase)

    def mark_step(self, step: str, status: str, message: str | None = None, **details: Any) -> None:
        """実行せずに確定した工程(スキップ等)の状態を記録する。"""
        phase, _ = current_scope()
        entry = self._step_entry(phase, step)
        entry.update({"title": message or step, "status": status, "finished_at": _now()})
        self.event("step_mark", message or step, step=step, status=status, **details)

    def mark_phase(self, phase: str, status: str, error: str | None = None) -> None:
        """フェーズの確定状態を上書きする(例執行を伴わない失敗の記録)。"""
        entry = self._phase_entry(phase)
        entry["status"] = status
        if error is not None:
            entry["error"] = error
        self.event("phase_mark", phase, phase=phase, status=status, error=error)
        self._write_progress()

    # --- 内部 ---------------------------------------------------------
    def _phase_entry(self, phase: str) -> dict[str, Any]:
        with self._lock:
            entry = self._progress.setdefault("phases", {}).setdefault(phase, {"steps": {}})
            entry.setdefault("steps", {})
            return entry

    def _step_entry(self, phase: str | None, step: str) -> dict[str, Any]:
        return self._phase_entry(phase or "_").setdefault("steps", {}).setdefault(step, {})

    def _set_current(
        self,
        *,
        phase: str | None = None,
        step: str | None = None,
        message: str | None = None,
        started_at: str | None = None,
    ) -> None:
        """``progress.json``の``current``(=今実行しているもの)を差し替える。"""
        with self._lock:
            previous = self._progress.get("current") or {}
            if phase is None and step is None and message is None:
                current: dict[str, Any] | None = None
            else:
                current = {
                    "phase": phase,
                    "step": step,
                    "message": message,
                    "started_at": started_at or previous.get("started_at"),
                }
            self._progress["current"] = current
            self._progress["updated_at"] = _now()
            self._write_progress_locked()

    def _load_progress(self) -> dict[str, Any]:
        path = self.progress_path
        if path is None or not path.is_file():
            return {"phases": {}}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"phases": {}}
        return loaded if isinstance(loaded, dict) else {"phases": {}}

    def _write_progress(self) -> None:
        with self._lock:
            self._write_progress_locked()

    def _write_progress_locked(self) -> None:
        path = self.progress_path
        if path is None:
            return
        # 読み取り側が壊れたJSONを掴まないよう、一時ファイル経由で差し替える。
        temporary = path.with_suffix(".json.tmp")
        try:
            temporary.write_text(
                json.dumps(self._progress, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, path)
        except OSError:
            logger.debug("progress.jsonの書き込みに失敗しました: %s", path, exc_info=True)

    def _append(self, record: dict[str, Any]) -> None:
        path = self.journal_path
        if path is None:
            return
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            try:
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(line + "\n")
                    stream.flush()
            except OSError:
                logger.debug("run_journal.jsonlの書き込みに失敗しました: %s", path, exc_info=True)


#: 有効化されていない場合に使う書き込み無しのジャーナル。
_NULL_JOURNAL = RunJournal()
_active_journal: RunJournal | None = None


def set_journal(journal: RunJournal | None) -> None:
    """プロセス全体で使用するジャーナルを差し替える。"""
    global _active_journal
    _active_journal = journal


def get_journal() -> RunJournal:
    """有効なジャーナルを返す(未設定なら何も書かないインスタンス)。"""
    return _active_journal if _active_journal is not None else _NULL_JOURNAL


def read_progress(project_directory: str | Path) -> dict[str, Any] | None:
    """``progress.json``を読み込む(無ければNone)。"""
    path = Path(project_directory) / PROGRESS_FILENAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_journal(
    project_directory: str | Path, *, tail: int | None = None
) -> list[dict[str, Any]]:
    """``run_journal.jsonl``を読み込む。``tail``指定時は末尾のみ返す。"""
    path = Path(project_directory) / JOURNAL_FILENAME
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records[-tail:] if tail else records
