"""1回の実行(ラン)に対するログ設定と実行ジャーナルの有効化をまとめる。

各スクリプトの冒頭で``start_run()``を呼ぶと、以下が一括で有効になる。

- コンソールと``projects/{id}/logs/run_*.log``の両方へ出る統一フォーマットのログ
- 全ログ行への「今どのフェーズ・工程か」の付与
- ``run_journal.jsonl`` / ``progress.json`` への進捗記録

工程ごとの``*.log``(``fill.log``等)は従来どおり個別に出力され、
本モジュールのランログはそれらを時系列で串刺しにしたものになる。
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from poscap_calibration.state.run_journal import RunJournal, current_scope, set_journal

LOG_DIRECTORY_NAME = "logs"
LOG_FORMAT = "%(asctime)s %(levelname)-7s %(scope)s%(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"
#: パイプラインから子プロセスとして起動されたことを示す環境変数。
PIPELINE_ENV_FLAG = "POSCAP_PIPELINE_ACTIVE"
#: 本モジュールが追加したハンドラを識別し、二重登録を防ぐための印。
_HANDLER_MARK = "_poscap_handler"


class _ScopeFilter(logging.Filter):
    """全ログ行へ現在のフェーズ/工程を差し込む。"""

    def filter(self, record: logging.LogRecord) -> bool:
        phase, step = current_scope()
        scope = "/".join(part for part in (phase, step) if part)
        record.scope = f"[{scope}] " if scope else ""
        return True


def setup_logging(
    project_directory: str | Path | None = None,
    *,
    level: int = logging.INFO,
    run_id: str | None = None,
) -> Path | None:
    """ルートロガーへコンソール出力とランログを設定し、ランログのパスを返す。"""
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            root.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    scope_filter = _ScopeFilter()

    # コンソールの文字コードで表現できない文字があってもログ出力を止めない
    # (完全な内容はUTF-8のランログ側に残る)。
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(errors="replace")
        except (OSError, ValueError):
            pass

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.addFilter(scope_filter)
    setattr(console, _HANDLER_MARK, True)
    root.addHandler(console)

    if project_directory is None:
        return None

    log_directory = Path(project_directory) / LOG_DIRECTORY_NAME
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / f"run_{run_id or datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(scope)s%(name)s: %(message)s")
    )
    file_handler.addFilter(scope_filter)
    setattr(file_handler, _HANDLER_MARK, True)
    root.addHandler(file_handler)

    return log_path


def start_run(
    project_directory: str | Path | None = None,
    *,
    title: str | None = None,
    level: int = logging.INFO,
    run_id: str | None = None,
) -> RunJournal:
    """ログとジャーナルを有効化し、以降``get_journal()``で使えるようにする。"""
    # パイプラインから起動された場合、進捗ファイルは親が一元管理する。
    # 子は標準出力へ出すだけにして、progress.jsonの上書き合戦を避ける。
    if os.environ.get(PIPELINE_ENV_FLAG):
        project_directory = None

    resolved_run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = setup_logging(project_directory, level=level, run_id=resolved_run_id)

    journal = RunJournal(project_directory, run_id=resolved_run_id)
    set_journal(journal)

    logger = logging.getLogger(__name__)
    logger.info("実行開始: %s (run_id=%s)", title or "POSCAPパラメータ同定", resolved_run_id)
    if project_directory is not None:
        logger.info("プロジェクト: %s", Path(project_directory).resolve())
    if log_path is not None:
        logger.info("ランログ: %s", log_path.resolve())
    if journal.progress_path is not None:
        logger.info("進捗ファイル: %s", journal.progress_path.resolve())

    journal.event("run_start", title, log=str(log_path) if log_path else None)
    return journal
