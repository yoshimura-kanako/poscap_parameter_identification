"""実行ジャーナル・同定値記録・進捗レポートの単体テスト。"""

from __future__ import annotations

import json

import pytest

from poscap_calibration.cli import main as cli_main
from poscap_calibration.project_layout import ProjectLayout
from poscap_calibration.state.identified_parameters import (
    PHASE1,
    load_identified_parameters,
    record_identified_parameters,
)
from poscap_calibration.state.progress_report import build_report, format_report
from poscap_calibration.state.run_journal import (
    RunJournal,
    get_journal,
    read_journal,
    read_progress,
    set_journal,
)
from poscap_calibration.state.state_manager import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    write_status,
)


@pytest.fixture
def journal(tmp_path):
    instance = RunJournal(tmp_path / "project", run_id="test_run")
    yield instance
    set_journal(None)


def test_phase_and_step_are_recorded(journal, tmp_path):
    directory = tmp_path / "project"
    with journal.phase("phase1", "フェーズ1"):
        with journal.step("condition_01", "条件1", index=1, total=9):
            journal.progress("充填を実行中")

    progress = read_progress(directory)
    assert progress["phases"]["phase1"]["status"] == STATUS_COMPLETED
    assert progress["phases"]["phase1"]["steps"]["condition_01"]["status"] == STATUS_COMPLETED
    # フェーズを抜けたら「実行中」は空になる。
    assert progress["current"] is None

    kinds = [record["kind"] for record in read_journal(directory)]
    assert kinds == ["phase_start", "step_start", "progress", "step_end", "phase_end"]


def test_failure_is_recorded_and_reraised(journal, tmp_path):
    with pytest.raises(RuntimeError):
        with journal.phase("phase1"):
            with journal.step("condition_01"):
                raise RuntimeError("シミュレーション失敗")

    progress = read_progress(tmp_path / "project")
    assert progress["phases"]["phase1"]["status"] == STATUS_FAILED
    assert "シミュレーション失敗" in progress["phases"]["phase1"]["error"]
    assert (
        progress["phases"]["phase1"]["steps"]["condition_01"]["status"] == STATUS_FAILED
    )


def test_progress_is_readable_while_running(journal, tmp_path):
    """途中で止まってもprogress.jsonから現在地が読める。"""
    with journal.phase("phase1", "フェーズ1"):
        with journal.step("condition_03", "条件3"):
            journal.progress("プリせん断を実行中")
            progress = read_progress(tmp_path / "project")

    assert progress["current"]["phase"] == "phase1"
    assert progress["current"]["step"] == "condition_03"
    assert progress["current"]["message"] == "プリせん断を実行中"


def test_journal_without_directory_is_noop():
    """未設定時はファイルを書かず、例外も出さない。"""
    set_journal(None)
    with get_journal().phase("phase1"):
        with get_journal().step("condition_01"):
            get_journal().progress("実行中")
            get_journal().record_result("value", 1.0)


def test_identified_parameters_keep_history(tmp_path):
    record_identified_parameters(
        tmp_path, PHASE1, {"rolling_resistance": 0.4}, source="first.csv"
    )
    path = record_identified_parameters(
        tmp_path, PHASE1, {"rolling_resistance": 0.44427}, source="second.csv"
    )

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["phases"][PHASE1]["values"]["rolling_resistance"] == 0.44427
    assert len(document["history"]) == 2
    assert load_identified_parameters(tmp_path)["phases"][PHASE1]["source"] == "second.csv"


def test_build_report_reflects_step_status(tmp_path):
    layout = ProjectLayout("0", tmp_path)
    condition_directory = layout.shear_condition_directory(1)
    write_status(condition_directory / "fill", {"status": STATUS_COMPLETED})
    write_status(condition_directory / "pre_shear", {"status": STATUS_FAILED})
    record_identified_parameters(
        layout.project_directory, PHASE1, {"dynamic_friction": 0.66867}
    )

    report = build_report(layout)
    condition = report["shear_conditions"][0]
    assert condition["steps"]["fill"] == STATUS_COMPLETED
    assert condition["status"] == STATUS_FAILED

    text = format_report(report, verbose=True)
    assert "フェーズ1: せん断試験" in text
    assert "dynamic_friction = 0.66867" in text


def test_cli_status_runs(tmp_path, capsys):
    layout = ProjectLayout("0", tmp_path)
    layout.project_directory.mkdir(parents=True)

    assert cli_main(["status", "--project-root", str(tmp_path), "--project-id", "0"]) == 0
    assert "フェーズ2: 壁面摩擦試験" in capsys.readouterr().out


def test_cli_record_params_round_trip(tmp_path, capsys):
    layout = ProjectLayout("0", tmp_path)
    layout.project_directory.mkdir(parents=True)
    arguments = ["--project-root", str(tmp_path), "--project-id", "0"]

    assert cli_main(["record-params", *arguments, "wall_dynamic_friction=0.31"]) == 0
    capsys.readouterr()

    assert cli_main(["params", *arguments]) == 0
    assert "wall_dynamic_friction = 0.31" in capsys.readouterr().out
