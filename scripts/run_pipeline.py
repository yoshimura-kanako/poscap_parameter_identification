#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""フェーズ0→1→2を通しで自動実行する(docs/workflow.md 3章)。

長時間実行を前提とし、工程ごとに進捗・ログ・中間結果を保存する。
途中で停止しても、完了済み工程はスキップして続きから再開できる。

実行例:
    python scripts/run_pipeline.py --peak-ratio 1.05 --shear-target 0.69898 --saor-target 42.9
    python scripts/run_pipeline.py --dry-run
    python scripts/run_pipeline.py --phases phase2
    python scripts/run_pipeline.py --start-from phase1_rsm_shear --peak-ratio 1.05 \
        --shear-target 0.69898 --saor-target 42.9

実行中の確認(別ターミナル):
    poscap status --verbose
    poscap journal --tail 40
    poscap errors
"""

from __future__ import annotations

import argparse
from pathlib import Path

from poscap_calibration.project_layout import (
    DEFAULT_PROJECT_ID,
    ProjectLayout,
)
from poscap_calibration.run_session import start_run
from poscap_calibration.workflows.pipeline import (
    DEFAULT_LOADS_KPA,
    DEFAULT_SHEAR_CONDITION_IDS,
    DEFAULT_WALL_CONDITION_IDS,
    PHASE_KEYS,
    STAGE_KEYS,
    PipelineOptions,
    format_summary,
    run_pipeline,
    select_stages,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_ROOT = REPO_ROOT / "projects"
DEFAULT_DISTRIBUTION_CSV = REPO_ROOT / "input/particle_distribution/test_distribution.csv"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)

    parser.add_argument(
        "--peak-ratio", type=float, default=None,
        help="実験ピーク比(条件表Excelの作成に必要。phase0から実行する場合は必須)",
    )
    parser.add_argument(
        "--shear-target", type=float, default=None,
        help="実験定常傾き(せん断の目標値。フェーズ1の同定とフェーズ2の条件表に必要)",
    )
    parser.add_argument(
        "--saor-target", type=float, default=None,
        help="実験安息角の代表値(安息角の目標値)",
    )
    parser.add_argument(
        "--distribution-csv", type=Path, default=DEFAULT_DISTRIBUTION_CSV,
        help="DEM用粒度分布CSV",
    )

    parser.add_argument(
        "--shear-condition-ids", type=int, nargs="+", default=list(DEFAULT_SHEAR_CONDITION_IDS)
    )
    parser.add_argument(
        "--saor-condition-ids", type=int, nargs="+", default=list(DEFAULT_SHEAR_CONDITION_IDS)
    )
    parser.add_argument(
        "--wall-condition-ids", type=int, nargs="+", default=list(DEFAULT_WALL_CONDITION_IDS)
    )
    parser.add_argument("--loads", type=float, nargs="+", default=list(DEFAULT_LOADS_KPA))

    parser.add_argument(
        "--phases", nargs="+", choices=list(PHASE_KEYS), default=None,
        help="実行するフェーズ(既定は全フェーズ)",
    )
    parser.add_argument(
        "--stages", nargs="+", choices=list(STAGE_KEYS), default=None,
        help="実行する工程を直接指定する",
    )
    parser.add_argument("--start-from", choices=list(STAGE_KEYS), default=None)
    parser.add_argument("--stop-after", choices=list(STAGE_KEYS), default=None)

    parser.add_argument(
        "--force", action="store_true", help="完了済み工程も再実行する",
    )
    parser.add_argument(
        "--continue-on-error", action="store_true",
        help="工程が失敗しても後続を続行する(既定はその場で中断)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="実行せず、実行予定の工程一覧のみ表示する",
    )
    parser.add_argument(
        "--show-gui", action="store_true", help="Rocky GUIを表示して実行する(既定はheadless)",
    )
    return parser.parse_args()


def _require_targets(arguments: argparse.Namespace, stages) -> None:
    """選択した工程に必要な入力値が揃っているか、実行前に確認する。"""
    needed: dict[str, object] = {}
    keys = {stage.key for stage in stages}
    if {"phase0_shear_workbook", "phase1_overlay", "phase2_workbook"} & keys:
        needed["--peak-ratio"] = arguments.peak_ratio
    if {"phase1_overlay", "phase2_workbook"} & keys:
        needed["--shear-target"] = arguments.shear_target
    if "phase1_overlay" in keys:
        needed["--saor-target"] = arguments.saor_target

    missing = [name for name, value in needed.items() if value is None]
    if missing:
        raise SystemExit(
            f"必須の入力値が指定されていません: {missing}\n"
            "実験データ解析の結果(ピーク比・定常傾き・安息角)を指定してください。"
        )


def main() -> int:
    arguments = parse_arguments()

    layout = ProjectLayout(arguments.project_id, arguments.project_root)
    stages = select_stages(
        stage_keys=arguments.stages,
        phases=arguments.phases,
        start_from=arguments.start_from,
        stop_after=arguments.stop_after,
    )

    options = PipelineOptions(
        layout=layout,
        peak_ratio=arguments.peak_ratio if arguments.peak_ratio is not None else float("nan"),
        shear_target=(
            arguments.shear_target if arguments.shear_target is not None else float("nan")
        ),
        saor_target=arguments.saor_target if arguments.saor_target is not None else float("nan"),
        distribution_csv=arguments.distribution_csv,
        shear_condition_ids=tuple(arguments.shear_condition_ids),
        saor_condition_ids=tuple(arguments.saor_condition_ids),
        wall_condition_ids=tuple(arguments.wall_condition_ids),
        loads_kpa=tuple(arguments.loads),
        headless=not arguments.show_gui,
    )

    if arguments.dry_run:
        summary = run_pipeline(options, stages=stages, dry_run=True)
        print("実行予定の工程:")
        for planned in summary["planned_stages"]:
            mark = "完了済み" if planned["completed"] else "実行"
            print(f"  [{mark:^6}] {planned['stage']:<32} {planned['title']}")
        return 0

    _require_targets(arguments, stages)
    journal = start_run(
        layout.project_directory, title="DEMパラメータ同定 通し実行(フェーズ0〜2)"
    )
    journal.record_result(
        "pipeline_inputs",
        {
            "peak_ratio": arguments.peak_ratio,
            "shear_target": arguments.shear_target,
            "saor_target": arguments.saor_target,
        },
    )

    summary = run_pipeline(
        options,
        stages=stages,
        force=arguments.force,
        stop_on_error=not arguments.continue_on_error,
    )

    print()
    print(format_summary(summary))
    return 1 if summary["failed_stages"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
