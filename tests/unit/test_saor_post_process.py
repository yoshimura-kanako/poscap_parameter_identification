"""安息角ポスト処理ラッパーのユニットテスト(Rocky実機なし)。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from poscap_calibration.workflows.saor_post_process import (
    DEFAULT_SCRIPT_PATH,
    EXPECTED_OUTPUT_FILENAMES,
    SaorPostProcessError,
    _adapt_source,
    _load_script_namespace,
    run_saor_post_process,
)

SCRIPT_PATH = Path(__file__).parents[2] / DEFAULT_SCRIPT_PATH


def test_managed_script_exists_outside_tmp_folder() -> None:
    """一時フォルダではなく管理用フォルダのスクリプトを参照する。"""
    assert SCRIPT_PATH.is_file()
    assert "tmp" not in SCRIPT_PATH.parts


def test_load_script_namespace_exposes_functions_without_rocky_globals() -> None:
    """Rockyが注入する``app``が無くても関数定義を読み込める。"""
    namespace = _load_script_namespace(SCRIPT_PATH)

    assert callable(namespace["post_process"])
    assert callable(namespace["dump_to_file"])
    # 実行部を切り離しているため、Rocky専用のグローバルは評価されない。
    assert "app" not in namespace
    assert "project" not in namespace


def test_load_script_namespace_raises_when_script_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _load_script_namespace(tmp_path / "missing.py")


def test_load_script_namespace_raises_when_entry_point_missing(tmp_path: Path) -> None:
    script_path = tmp_path / "script.py"
    script_path.write_text("def post_process():\n    pass\n", encoding="utf-8")

    with pytest.raises(SaorPostProcessError):
        _load_script_namespace(script_path)


def test_adapt_source_replaces_numpy_time_step() -> None:
    """numpy.float64はPyro5で送れないため整数インデックスへ置き換える。"""
    source = "x = gf.GetArray(time_step=timeset[-1])\ndf.to_csv(p, line_terminator='\\n')\n"

    adapted = _adapt_source(source, Path("dummy.py"))

    assert "time_step=int(len(timeset) - 1)" in adapted
    assert "timeset[-1]" not in adapted


def test_adapt_source_replaces_pandas_line_terminator() -> None:
    """pandas 2.0では``lineterminator``でないとTypeErrorになる。"""
    source = "x = gf.GetArray(time_step=timeset[-1])\ndf.to_csv(p, line_terminator='\\n')\n"

    adapted = _adapt_source(source, Path("dummy.py"))

    assert "lineterminator=" in adapted
    assert "line_terminator=" not in adapted


def test_adapt_source_raises_when_pattern_missing() -> None:
    """元スクリプトが変わって適応対象が消えた場合は失敗させる。"""
    with pytest.raises(SaorPostProcessError):
        _adapt_source("x = 1\n", Path("dummy.py"))


def test_managed_script_has_no_numpy_time_step_after_adaptation() -> None:
    namespace = _load_script_namespace(SCRIPT_PATH)

    assert callable(namespace["post_process"])


def _create_stub_script(tmp_path: Path) -> Path:
    """元スクリプトと同じ関数構成・出力ファイル名を持つスタブ。"""
    script_path = tmp_path / "stub_script.py"
    script_path.write_text(
        """
import json
import os

import numpy as np
import pandas as pd


def post_process(project, results_folder):
    project.GetStudy()
    timeset = [0.0, 1.0]
    _ = 'time_step=timeset[-1] line_terminator='
    data = np.array([[0.0, 0.1, 0.2, 0.15, 0.3, 0.4]])
    return data, 31.5, 28.25


def dump_to_file(data, top_angle, bottom_angle, results_folder):
    header = ['x_coord', 'min_y', 'max_y', 'avg_y', 'fit_top', 'fit_bottom']
    pd.DataFrame(data).to_csv(
        os.path.join(results_folder, 'experiment_data_points.csv'),
        header=header, index=False
    )
    with open(os.path.join(results_folder, 'angles.json'), 'w') as handle:
        json.dump({'SAOR_from_top': top_angle, 'SAOR_from_bottom': bottom_angle}, handle)
    with open(os.path.join(results_folder, 'Experiment_saor.png'), 'wb') as handle:
        handle.write(b'png')


project = app.GetProject()
""",
        encoding="utf-8",
    )
    return script_path


class _StubProject:
    def GetStudy(self) -> object:  # noqa: N802 - Rocky APIの命名に合わせる
        return object()


def test_run_saor_post_process_writes_expected_outputs(tmp_path: Path) -> None:
    script_path = _create_stub_script(tmp_path)
    output_directory = tmp_path / "Results" / "saor"

    result = run_saor_post_process(
        _StubProject(), output_directory, script_path=script_path
    )

    assert result["saor_from_top_deg"] == pytest.approx(31.5)
    assert result["saor_from_bottom_deg"] == pytest.approx(28.25)
    assert result["row_count"] == 1
    assert set(result["outputs"]) == set(EXPECTED_OUTPUT_FILENAMES)

    for filename in EXPECTED_OUTPUT_FILENAMES:
        file_path = output_directory / filename
        assert file_path.is_file()
        assert file_path.stat().st_size > 0

    angles = json.loads((output_directory / "angles.json").read_text(encoding="utf-8"))
    assert angles["SAOR_from_top"] == pytest.approx(31.5)


def test_run_saor_post_process_detects_missing_required_output(tmp_path: Path) -> None:
    script_path = tmp_path / "incomplete.py"
    script_path.write_text(
        """
import numpy as np


def post_process(project, results_folder):
    _ = 'time_step=timeset[-1] line_terminator='
    return np.array([[0.0]]), 30.0, 25.0


def dump_to_file(data, top_angle, bottom_angle, results_folder):
    pass


project = app.GetProject()
""",
        encoding="utf-8",
    )

    with pytest.raises(SaorPostProcessError):
        run_saor_post_process(_StubProject(), tmp_path / "out", script_path=script_path)


def test_run_saor_post_process_detects_empty_output(tmp_path: Path) -> None:
    script_path = tmp_path / "empty_output.py"
    script_path.write_text(
        """
import os

import numpy as np


def post_process(project, results_folder):
    _ = 'time_step=timeset[-1] line_terminator='
    return np.array([[0.0]]), 30.0, 25.0


def dump_to_file(data, top_angle, bottom_angle, results_folder):
    for name in ('angles.json', 'experiment_data_points.csv'):
        open(os.path.join(results_folder, name), 'w').close()


project = app.GetProject()
""",
        encoding="utf-8",
    )

    with pytest.raises(SaorPostProcessError):
        run_saor_post_process(_StubProject(), tmp_path / "out", script_path=script_path)
