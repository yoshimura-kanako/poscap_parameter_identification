"""9条件のせん断試験を順に実行するバッチ処理(docs/workflow.md 10章)。

条件ごとに 充填 → プリせん断 → 本せん断3/5/7 kPa → 解析Excel反映 を実行する。
完了済み工程は``status.json``を見て再実行を省略し、条件単位で失敗を隔離する。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from poscap_calibration.condition_table import load_shear_conditions
from poscap_calibration.models import ShearCondition
from poscap_calibration.rocky.client import RockyClient
from poscap_calibration.rocky.simulation_runner import (
    read_shear_time_series,
    run_filling,
    run_pre_shear,
    run_shear_test,
    shear_time_series_csv_path,
)
from poscap_calibration.shear_analysis_excel import (
    export_response_surface_data,
    update_and_recalculate,
)
from poscap_calibration.state.state_manager import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_SKIPPED,
    read_status,
    write_status,
)
from poscap_calibration.state.run_journal import get_journal

logger = logging.getLogger(__name__)

DEFAULT_LOADS_KPA: tuple[float, ...] = (3.0, 5.0, 7.0)
FILL_USER_PROCESS_NAME = "Split"
BATCH_SUMMARY_FILENAME = "shear_batch_summary.json"
CONDITION_SUMMARY_FILENAME = "shear_summary.json"
RESPONSE_SURFACE_CSV_FILENAME = "shear_response_surface_data.csv"

_PRE_SHEAR_INLET_RELATIVE_PATH = Path("pre_shear/converted/particles_inlet.csv")
_PRE_SHEAR_HEIGHT_RELATIVE_PATH = Path("pre_shear/raw/shear_cell_height.json")
_FILL_INLET_RELATIVE_PATH = Path("fill/converted/particles_1ml_inlet.csv")

ClientFactory = Callable[[], RockyClient]


def _is_step_completed(condition_directory: Path, step_directory_name: str) -> bool:
    try:
        status = read_status(condition_directory / step_directory_name)
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    return status.get("status") == STATUS_COMPLETED


def run_condition(
    client_factory: ClientFactory,
    condition: ShearCondition,
    filling_base_project_path: str | Path,
    pre_shear_template_path: str | Path,
    shear_templates: dict[float, Path],
    output_root: str | Path,
    workbook_path: str | Path,
    shear_cell_geometry_name: str,
    *,
    loads_kpa: tuple[float, ...] = DEFAULT_LOADS_KPA,
    skip_completed: bool = True,
    update_excel: bool = True,
) -> dict[str, Any]:
    """1条件分の充填〜本せん断〜Excel反映を実行し、条件サマリを返す。"""
    output_root = Path(output_root)
    condition_directory = output_root / condition.directory_name
    condition_directory.mkdir(parents=True, exist_ok=True)
    journal = get_journal()

    summary: dict[str, Any] = {
        "condition_id": condition.condition_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "rolling_resistance": condition.rolling_resistance,
            "dynamic_friction": condition.dynamic_friction,
            "static_friction": condition.static_friction,
        },
        "steps": {},
        "analysis_workbook": str(Path(workbook_path).resolve()),
    }

    try:
        journal.progress(
            f"条件{condition.condition_id}: 転がり抵抗={condition.rolling_resistance} "
            f"動摩擦={condition.dynamic_friction} 静摩擦={condition.static_friction}",
            condition_id=condition.condition_id,
        )
        if skip_completed and _is_step_completed(condition_directory, "fill"):
            summary["steps"]["fill"] = {"status": STATUS_SKIPPED}
            logger.info("condition=%d fill: 完了済みのためスキップ", condition.condition_id)
        else:
            journal.progress(f"条件{condition.condition_id}: 充填を実行中")
            run_filling(
                client_factory(),
                condition,
                base_project_path=filling_base_project_path,
                output_root=output_root,
                user_process_name=FILL_USER_PROCESS_NAME,
            )
            summary["steps"]["fill"] = {"status": STATUS_COMPLETED}

        if skip_completed and _is_step_completed(condition_directory, "pre_shear"):
            summary["steps"]["pre_shear"] = {"status": STATUS_SKIPPED}
            logger.info("condition=%d pre_shear: 完了済みのためスキップ", condition.condition_id)
        else:
            journal.progress(f"条件{condition.condition_id}: プリせん断を実行中")
            run_pre_shear(
                client_factory(),
                condition,
                template_project_path=pre_shear_template_path,
                inlet_csv_path=condition_directory / _FILL_INLET_RELATIVE_PATH,
                output_root=output_root,
                shear_cell_geometry_name=shear_cell_geometry_name,
            )
            summary["steps"]["pre_shear"] = {"status": STATUS_COMPLETED}

        height_json_path = condition_directory / _PRE_SHEAR_HEIGHT_RELATIVE_PATH
        if not height_json_path.is_file():
            raise FileNotFoundError(
                f"条件{condition.condition_id}: せん断セル高さが見つかりません: {height_json_path}"
            )
        shear_cell_height_m = float(
            json.loads(height_json_path.read_text(encoding="utf-8"))["maximum_y_m"]
        )
        summary["shear_cell_height_m"] = shear_cell_height_m

        inlet_csv_path = condition_directory / _PRE_SHEAR_INLET_RELATIVE_PATH
        summary["inlet_csv"] = str(inlet_csv_path.resolve())

        time_series_by_load: dict[float, tuple[list[float], list[float], list[float]]] = {}
        csv_paths: dict[str, str] = {}
        for load_kpa in loads_kpa:
            template_path = shear_templates.get(load_kpa)
            if template_path is None:
                raise ValueError(
                    f"条件{condition.condition_id}: 荷重{load_kpa}kPaのテンプレートが指定されていません。"
                )

            step_directory_name = f"shear_{load_kpa:g}kpa"
            csv_path = shear_time_series_csv_path(output_root, condition, load_kpa)
            if (
                skip_completed
                and _is_step_completed(condition_directory, step_directory_name)
                and csv_path.is_file()
            ):
                summary["steps"][step_directory_name] = {"status": STATUS_SKIPPED}
                logger.info(
                    "condition=%d %s: 完了済みのためスキップ",
                    condition.condition_id,
                    step_directory_name,
                )
            else:
                journal.progress(
                    f"条件{condition.condition_id}: 本せん断 {load_kpa:g}kPa を実行中"
                )
                csv_path = run_shear_test(
                    client_factory(),
                    condition,
                    load_kpa=load_kpa,
                    template_project_path=template_path,
                    inlet_csv_path=inlet_csv_path,
                    shear_cell_height_m=shear_cell_height_m,
                    output_root=output_root,
                    shear_cell_geometry_name=shear_cell_geometry_name,
                )
                summary["steps"][step_directory_name] = {"status": STATUS_COMPLETED}

            csv_paths[f"{load_kpa:g}"] = str(csv_path)
            time_series_by_load[load_kpa] = read_shear_time_series(csv_path)

        summary["time_series_csv"] = csv_paths
        summary["templates"] = {
            f"{load:g}": str(shear_templates[load]) for load in loads_kpa
        }

        if update_excel:
            journal.progress(f"条件{condition.condition_id}: 解析Excelへ反映中")
            summary["excel"] = update_and_recalculate(
                workbook_path, condition.condition_id, time_series_by_load
            )
        else:
            summary["excel"] = {"recalculated": False, "skipped": True}

        summary["status"] = STATUS_COMPLETED

    except Exception as error:
        summary["status"] = STATUS_FAILED
        summary["error"] = f"{type(error).__name__}: {error}"
        logger.exception("condition=%d の処理に失敗しました", condition.condition_id)
        raise
    finally:
        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        (condition_directory / CONDITION_SUMMARY_FILENAME).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    return summary


def run_conditions(
    client_factory: ClientFactory,
    workbook_path: str | Path,
    filling_base_project_path: str | Path,
    pre_shear_template_path: str | Path,
    shear_templates: dict[float, Path],
    output_root: str | Path,
    shear_cell_geometry_name: str,
    *,
    condition_ids: tuple[int, ...] | None = None,
    loads_kpa: tuple[float, ...] = DEFAULT_LOADS_KPA,
    skip_completed: bool = True,
    update_excel: bool = True,
    stop_on_error: bool = False,
    export_response_surface: bool = True,
) -> dict[str, Any]:
    """複数条件を順に実行する。条件単位で失敗を隔離し、バッチサマリを返す。"""
    conditions = load_shear_conditions(workbook_path)
    if condition_ids is not None:
        available = {condition.condition_id for condition in conditions}
        missing = sorted(set(condition_ids) - available)
        if missing:
            raise ValueError(
                f"条件表に存在しない条件番号が指定されました: {missing}"
                f"(利用可能: {sorted(available)})"
            )
        conditions = [c for c in conditions if c.condition_id in set(condition_ids)]

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    journal = get_journal()

    batch: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "condition_ids": [condition.condition_id for condition in conditions],
        "loads_kpa": list(loads_kpa),
        "analysis_workbook": str(Path(workbook_path).resolve()),
        "results": {},
    }

    total = len(conditions)
    journal.progress(
        f"せん断試験バッチを開始します: {total}条件 × 荷重{list(loads_kpa)}kPa",
        condition_ids=batch["condition_ids"],
    )
    for index, condition in enumerate(conditions, start=1):
        try:
            with journal.step(
                condition.directory_name,
                f"せん断試験 条件{condition.condition_id}",
                index=index,
                total=total,
            ):
                summary = run_condition(
                    client_factory,
                    condition,
                    filling_base_project_path=filling_base_project_path,
                    pre_shear_template_path=pre_shear_template_path,
                    shear_templates=shear_templates,
                    output_root=output_root,
                    workbook_path=workbook_path,
                    shear_cell_geometry_name=shear_cell_geometry_name,
                    loads_kpa=loads_kpa,
                    skip_completed=skip_completed,
                    update_excel=update_excel,
                )
            batch["results"][str(condition.condition_id)] = {
                "status": summary.get("status"),
                "steps": summary.get("steps"),
                "excel": summary.get("excel"),
            }
        except Exception as error:  # noqa: BLE001 - 条件単位で失敗を隔離する
            batch["results"][str(condition.condition_id)] = {
                "status": STATUS_FAILED,
                "error": f"{type(error).__name__}: {error}",
            }
            if stop_on_error:
                batch["stopped_at_condition"] = condition.condition_id
                journal.progress(f"条件{condition.condition_id}の失敗によりバッチを中断しました")
                break

    completed = [
        condition_id
        for condition_id, result in batch["results"].items()
        if result.get("status") == STATUS_COMPLETED
    ]
    batch["completed_condition_ids"] = sorted(int(value) for value in completed)
    batch["failed_condition_ids"] = sorted(
        int(condition_id)
        for condition_id, result in batch["results"].items()
        if result.get("status") == STATUS_FAILED
    )

    # 応答曲面用データは全条件完了後に1回だけ出力する(手順書1.2.8)。
    if export_response_surface:
        if batch["failed_condition_ids"]:
            batch["response_surface"] = {
                "skipped": True,
                "reason": f"未完了の条件があります: {batch['failed_condition_ids']}",
            }
        else:
            try:
                journal.progress("応答曲面用データを出力中")
                batch["response_surface"] = export_response_surface_data(
                    workbook_path, output_root / RESPONSE_SURFACE_CSV_FILENAME
                )
                logger.info(
                    "応答曲面用データを出力しました: %s",
                    batch["response_surface"]["output_csv"],
                )
                journal.record_result(
                    "shear_response_surface_csv",
                    batch["response_surface"]["output_csv"],
                )
            except Exception as error:  # noqa: BLE001 - 出力失敗でバッチ全体を落とさない
                batch["response_surface"] = {
                    "skipped": True,
                    "error": f"{type(error).__name__}: {error}",
                }
                logger.exception("応答曲面用データの出力に失敗しました")

    batch["finished_at"] = datetime.now(timezone.utc).isoformat()

    write_status(output_root, batch)
    (output_root / BATCH_SUMMARY_FILENAME).write_text(
        json.dumps(batch, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    journal.progress(
        f"せん断試験バッチ終了: 完了{batch['completed_condition_ids']} / "
        f"失敗{batch['failed_condition_ids']}",
        summary_json=str(output_root / BATCH_SUMMARY_FILENAME),
    )
    return batch
