"""プロジェクトフォルダを走査して現在の進捗と中間結果を一覧化する(運用時の状況確認用)。

処理が途中で止まっても、既に出力済みの``status.json``・サマリJSON・CSV・Excelから
「どこまで進んだか」「次に何をすべきか」を再構成できるようにする。
実行中プロセスには依存しないため、別ターミナルからいつでも確認できる。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from poscap_calibration.project_layout import (
    RSM_COMBINED_NAME,
    RSM_SAOR_NAME,
    RSM_SHEAR_NAME,
    ProjectLayout,
)
from poscap_calibration.state.identified_parameters import (
    format_identified_parameters,
    load_identified_parameters,
)
from poscap_calibration.state.run_journal import read_progress
from poscap_calibration.state.state_manager import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_FILENAME,
    STATUS_PENDING,
)

DEFAULT_SHEAR_LOADS: tuple[float, ...] = (3.0, 5.0, 7.0)
DEFAULT_SHEAR_CONDITION_COUNT = 9
DEFAULT_WALL_CONDITION_COUNT = 3

_STATUS_MARK = {
    STATUS_COMPLETED: "完了",
    STATUS_FAILED: "失敗",
    "running": "実行中",
    "skipped": "スキップ",
    STATUS_PENDING: "未実行",
}

PIPELINE_DIRECTORY_NAME = "pipeline"
PIPELINE_SUMMARY_FILENAME = "pipeline_summary.json"


def _read_status(directory: Path) -> dict[str, Any] | None:
    path = directory / STATUS_FILENAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _step_status(directory: Path) -> str:
    status = _read_status(directory)
    if status is None:
        return STATUS_PENDING
    return str(status.get("status") or STATUS_PENDING)


def _file_status(path: Path) -> str:
    return STATUS_COMPLETED if path.is_file() else STATUS_PENDING


def _item(name: str, status: str, detail: str | Path | None = None) -> dict[str, Any]:
    return {"name": name, "status": status, "detail": str(detail) if detail else None}


def _phase0_items(layout: ProjectLayout) -> list[dict[str, Any]]:
    particle_csvs = sorted(layout.particle_generation_results.glob("*.csv"))
    filling_project = layout.filling_input_directory / "work" / "Filling.rocky"
    return [
        _item(
            "粒子発生",
            STATUS_COMPLETED if particle_csvs else STATUS_PENDING,
            particle_csvs[0] if particle_csvs else layout.particle_generation_results,
        ),
        _item("充填インプット作成", _file_status(filling_project), filling_project),
    ]


def _shear_condition_rows(
    layout: ProjectLayout, loads_kpa: tuple[float, ...], condition_count: int
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for condition_id in range(1, condition_count + 1):
        directory = layout.shear_condition_directory(condition_id)
        if not directory.is_dir():
            rows.append({"condition_id": condition_id, "steps": {}, "status": STATUS_PENDING})
            continue
        steps = {"fill": _step_status(directory / "fill")}
        steps["pre_shear"] = _step_status(directory / "pre_shear")
        for load in loads_kpa:
            steps[f"shear_{load:g}kpa"] = _step_status(directory / f"shear_{load:g}kpa")
        if all(value == STATUS_COMPLETED for value in steps.values()):
            status = STATUS_COMPLETED
        elif any(value == STATUS_FAILED for value in steps.values()):
            status = STATUS_FAILED
        elif any(value != STATUS_PENDING for value in steps.values()):
            status = "running"
        else:
            status = STATUS_PENDING
        rows.append({"condition_id": condition_id, "steps": steps, "status": status})
    return rows


def _phase1_shear_items(
    layout: ProjectLayout, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    completed = [row["condition_id"] for row in rows if row["status"] == STATUS_COMPLETED]
    failed = [row["condition_id"] for row in rows if row["status"] == STATUS_FAILED]
    batch_summary = layout.shear_test_directory / "shear_batch_summary.json"
    return [
        _item("条件表Excel", _file_status(layout.shear_workbook), layout.shear_workbook),
        _item(
            "9条件シミュレーション",
            STATUS_COMPLETED if len(completed) == len(rows) and rows else "running",
            f"完了 {len(completed)}/{len(rows)} 条件"
            + (f" / 失敗 {failed}" if failed else ""),
        ),
        _item("バッチサマリ", _file_status(batch_summary), batch_summary),
        _item(
            "応答曲面用CSV",
            _file_status(layout.shear_response_surface_csv),
            layout.shear_response_surface_csv,
        ),
    ]


def _phase1_saor_items(layout: ProjectLayout) -> list[dict[str, Any]]:
    directories = sorted(layout.saor_test_directory.glob("condition_*"))
    completed = [
        directory.name for directory in directories if _step_status(directory) == STATUS_COMPLETED
    ]
    return [
        _item("条件表Excel", _file_status(layout.saor_workbook), layout.saor_workbook),
        _item(
            "安息角シミュレーション",
            STATUS_COMPLETED if completed else STATUS_PENDING,
            f"完了 {len(completed)}/{len(directories)} 条件" if directories else "未実行",
        ),
        _item(
            "応答曲面用CSV",
            _file_status(layout.saor_response_surface_csv),
            layout.saor_response_surface_csv,
        ),
    ]


def _rsm_items(layout: ProjectLayout) -> list[dict[str, Any]]:
    shear_equation = layout.rsm_model_equation(RSM_SHEAR_NAME)
    saor_equation = layout.rsm_model_equation(RSM_SAOR_NAME)
    combined_directory = layout.rsm_output_directory(RSM_COMBINED_NAME)
    combined_files = sorted(combined_directory.glob("*.csv")) if combined_directory.is_dir() else []
    return [
        _item("せん断モデル式", _file_status(shear_equation), shear_equation),
        _item("安息角モデル式", _file_status(saor_equation), saor_equation),
        _item(
            "重ね合わせ(交点)",
            STATUS_COMPLETED if combined_files else STATUS_PENDING,
            combined_directory,
        ),
    ]


def _phase2_items(
    layout: ProjectLayout, loads_kpa: tuple[float, ...], condition_count: int
) -> list[dict[str, Any]]:
    items = [
        _item(
            "条件表Excel",
            _file_status(layout.wall_friction_workbook),
            layout.wall_friction_workbook,
        ),
        _item(
            "充填(3条件共通)",
            _step_status(layout.wall_friction_fill_directory),
            layout.wall_friction_fill_directory,
        ),
    ]
    for condition_id in range(1, condition_count + 1):
        directory = layout.wall_friction_condition_directory(condition_id)
        if not directory.is_dir():
            items.append(_item(f"条件{condition_id}", STATUS_PENDING, directory))
            continue
        steps = {"pre_shear": _step_status(directory / "pre_shear")}
        for load in loads_kpa:
            steps[f"shear_{load:g}kpa"] = _step_status(directory / f"shear_{load:g}kpa")
        done = sum(1 for value in steps.values() if value == STATUS_COMPLETED)
        status = (
            STATUS_COMPLETED
            if done == len(steps)
            else (STATUS_FAILED if STATUS_FAILED in steps.values() else "running" if done else STATUS_PENDING)
        )
        items.append(
            _item(
                f"条件{condition_id}",
                status,
                ", ".join(f"{name}={_STATUS_MARK.get(value, value)}" for name, value in steps.items()),
            )
        )
    return items


def _pipeline_items(layout: ProjectLayout) -> list[dict[str, Any]]:
    """通し実行(``run_pipeline.py``)の工程別状態を返す。"""
    directory = layout.project_directory / PIPELINE_DIRECTORY_NAME
    if not directory.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for stage_directory in sorted(directory.iterdir()):
        status = _read_status(stage_directory)
        if status is None:
            continue
        items.append(
            _item(
                status.get("title") or stage_directory.name,
                str(status.get("status") or STATUS_PENDING),
                status.get("error") or stage_directory.name,
            )
        )
    return items


def collect_failures(layout: ProjectLayout) -> list[dict[str, Any]]:
    """プロジェクト配下の失敗した``status.json``をすべて集める。"""
    project_directory = layout.project_directory
    failures: list[dict[str, Any]] = []
    for status_path in sorted(project_directory.rglob(STATUS_FILENAME)):
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(status, dict) or status.get("status") != STATUS_FAILED:
            continue
        failures.append(
            {
                "location": str(status_path.parent.relative_to(project_directory)),
                "status_json": str(status_path),
                "title": status.get("title") or status.get("step") or status.get("stage"),
                "error": status.get("error"),
                "log": status.get("log"),
                "excerpt": status.get("error_excerpt") or [],
                "finished_at": status.get("finished_at"),
            }
        )
    return failures


def format_failures(failures: list[dict[str, Any]]) -> str:
    """失敗一覧を端末表示用へ整形する。"""
    if not failures:
        return "失敗した工程はありません。"
    lines = [f"失敗した工程: {len(failures)}件", "=" * 72]
    for failure in failures:
        lines.append(f"■ {failure['location']}")
        if failure.get("title"):
            lines.append(f"    工程  : {failure['title']}")
        lines.append(f"    エラー: {failure.get('error') or '(status.jsonにerrorなし)'}")
        lines.append(f"    状態  : {failure['status_json']}")
        if failure.get("log"):
            lines.append(f"    ログ  : {failure['log']}")
        for line in failure.get("excerpt") or []:
            lines.append(f"      | {line}")
        lines.append("")
    return "\n".join(lines)


def build_report(
    layout: ProjectLayout,
    *,
    loads_kpa: tuple[float, ...] = DEFAULT_SHEAR_LOADS,
    shear_condition_count: int = DEFAULT_SHEAR_CONDITION_COUNT,
    wall_condition_count: int = DEFAULT_WALL_CONDITION_COUNT,
) -> dict[str, Any]:
    """プロジェクトの進捗レポートを組み立てる。"""
    project_directory = layout.project_directory
    if not project_directory.is_dir():
        raise FileNotFoundError(f"プロジェクトフォルダが見つかりません: {project_directory}")

    shear_rows = _shear_condition_rows(layout, loads_kpa, shear_condition_count)
    pipeline_items = _pipeline_items(layout)
    phases = [
        {"phase": "phase0", "title": "フェーズ0: 粒度分布・粒子発生", "items": _phase0_items(layout)},
        {
            "phase": "phase1_shear",
            "title": "フェーズ1: せん断試験",
            "items": _phase1_shear_items(layout, shear_rows),
        },
        {"phase": "phase1_saor", "title": "フェーズ1: 安息角試験", "items": _phase1_saor_items(layout)},
        {"phase": "phase1_rsm", "title": "フェーズ1: 応答曲面・パラメータ決定", "items": _rsm_items(layout)},
        {
            "phase": "phase2",
            "title": "フェーズ2: 壁面摩擦試験",
            "items": _phase2_items(layout, loads_kpa, wall_condition_count),
        },
    ]
    if pipeline_items:
        phases.append(
            {"phase": "pipeline", "title": "通し実行(run_pipeline.py)の工程", "items": pipeline_items}
        )

    return {
        "project_id": layout.project_id,
        "project_directory": str(project_directory.resolve()),
        "progress": read_progress(project_directory),
        "identified_parameters": load_identified_parameters(project_directory),
        "shear_conditions": shear_rows,
        "failures": collect_failures(layout),
        "phases": phases,
    }


def format_report(report: dict[str, Any], *, verbose: bool = False) -> str:
    """進捗レポートを端末表示用の文字列へ整形する。"""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"プロジェクト: {report['project_id']}  ({report['project_directory']})")

    progress = report.get("progress")
    current = (progress or {}).get("current")
    if current:
        scope = "/".join(part for part in (current.get("phase"), current.get("step")) if part)
        lines.append(
            f"実行中: {current.get('message') or scope or '-'}"
            + (f"  [{scope}]" if scope else "")
            + (f"  開始 {current.get('started_at')}" if current.get("started_at") else "")
        )
    elif progress:
        lines.append(f"実行中の処理はありません (最終更新: {progress.get('updated_at', '-')})")
    else:
        lines.append("実行中の処理はありません (progress.json 未作成)")
    lines.append("=" * 72)

    for phase in report["phases"]:
        lines.append("")
        lines.append(f"■ {phase['title']}")
        for item in phase["items"]:
            mark = _STATUS_MARK.get(item["status"], item["status"])
            line = f"    [{mark:^5}] {item['name']}"
            if item.get("detail"):
                line += f" : {item['detail']}"
            lines.append(line)

    if verbose:
        lines.append("")
        lines.append("■ せん断9条件の工程別状況")
        for row in report["shear_conditions"]:
            steps = row["steps"]
            detail = (
                ", ".join(
                    f"{name}={_STATUS_MARK.get(value, value)}" for name, value in steps.items()
                )
                or "未着手"
            )
            lines.append(
                f"    条件{row['condition_id']:>2} [{_STATUS_MARK.get(row['status'], row['status']):^5}] {detail}"
            )

    lines.append("")
    lines.append("■ 同定値")
    for line in format_identified_parameters(report["identified_parameters"]).splitlines():
        lines.append(f"    {line}")

    failures = report.get("failures") or []
    if failures:
        lines.append("")
        lines.append(f"■ 失敗した工程: {len(failures)}件 (詳細は poscap errors)")
        for failure in failures:
            lines.append(f"    {failure['location']}: {failure.get('error') or '-'}")
    lines.append("")
    return "\n".join(lines)
