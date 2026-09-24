"""安息角シミュレーションのポスト処理(Rocky同梱マクロ "Pana - Calibration 1: SAOR" の実行)。

元スクリプトはRockyのPre/Post Script環境が注入するグローバル変数``app``に依存するが、
処理本体は``project``経由の標準PyRocky APIのみを使うためPyRockyから実行できる。
本モジュールは元スクリプトを改変せずに読み込み、出力先を指定して実行するラッパー。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_SCRIPT_PATH = Path("templates/rocky/saor/scripts/script_kiso_calibration_SAOR_v242.py")
#: 元スクリプトが``results_folder``へ出力するファイル(script内の記述で確認済み)。
EXPECTED_OUTPUT_FILENAMES: tuple[str, ...] = (
    "angles.json",
    "experiment_data_points.csv",
    "Experiment_saor.png",
)
#: 図の生成に失敗しても処理は継続するため、必須とするのは数値データのみ。
REQUIRED_OUTPUT_FILENAMES: tuple[str, ...] = (
    "angles.json",
    "experiment_data_points.csv",
)

# 元スクリプト末尾の実行部。ここより後ろはRocky環境専用のため読み込み時に切り離す。
_ENTRY_POINT_MARKER = "project = app.GetProject()"
#: PyRocky経由で実行するためのソース適応(元ファイルは変更しない)。
#: Rocky内蔵環境では``GetTimeSet()[-1]``がITimeStepだが、PyRockyではnumpy配列の
#: 要素(numpy.float64)になりPyro5でシリアライズできないため、最終時刻の
#: インデックス(int)へ置き換える。
_SOURCE_ADAPTATIONS: tuple[tuple[str, str], ...] = (
    ("time_step=timeset[-1]", "time_step=int(len(timeset) - 1)"),
    # pandas 2.0で``line_terminator``は``lineterminator``へ改名された。
    ("line_terminator=", "lineterminator="),
)

class SaorPostProcessError(RuntimeError):
    """安息角ポスト処理に失敗した場合に送出する例外。"""


def _load_script_namespace(script_path: Path) -> dict[str, Any]:
    """元スクリプトを関数定義まで読み込み、名前空間を返す。

    末尾の``app.GetProject()``以降はRocky環境専用のため除外する。
    描画は``plt.show()``を含むため、非対話バックエンドを先に設定する。
    """
    if not script_path.is_file():
        raise FileNotFoundError(f"ポスト処理スクリプトが見つかりません: {script_path}")

    source = script_path.read_text(encoding="utf-8")
    marker_index = source.find(_ENTRY_POINT_MARKER)
    if marker_index == -1:
        raise SaorPostProcessError(
            f"スクリプトの実行部({_ENTRY_POINT_MARKER})が見つかりません: {script_path}"
        )

    source = _adapt_source(source[:marker_index], script_path)

    import matplotlib

    matplotlib.use("Agg", force=True)

    namespace: dict[str, Any] = {"__name__": "saor_macro", "__file__": str(script_path)}
    exec(compile(source, str(script_path), "exec"), namespace)  # noqa: S102

    for function_name in ("post_process", "dump_to_file"):
        if function_name not in namespace:
            raise SaorPostProcessError(
                f"スクリプトに関数 '{function_name}' がありません: {script_path}"
            )
    return namespace


def _adapt_source(source: str, script_path: Path) -> str:
    """PyRocky経由で実行できるようソースを適応させる。

    適応対象が見つからない場合は、元スクリプトが変わった可能性があるため失敗させる。
    """
    for pattern, replacement in _SOURCE_ADAPTATIONS:
        if pattern not in source:
            raise SaorPostProcessError(
                f"スクリプトの適応対象 {pattern!r} が見つかりません: {script_path}。"
                "元スクリプトの内容を確認してください。"
            )
        source = source.replace(pattern, replacement)
    return source


def run_saor_post_process(
    project: Any,
    output_directory: str | Path,
    *,
    script_path: str | Path = DEFAULT_SCRIPT_PATH,
) -> dict[str, Any]:
    """安息角のポスト処理を実行し、生成ファイルと角度を返す。

    ``project``はPyRockyのRAProject(``RockyClient.get_project()``で取得)。
    """
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)

    namespace = _load_script_namespace(Path(script_path))

    logger.info("saor post process start: output=%s script=%s", output_path, script_path)
    result_data, top_angle, bottom_angle = namespace["post_process"](
        project, str(output_path)
    )
    namespace["dump_to_file"](result_data, top_angle, bottom_angle, str(output_path))

    outputs = _verify_outputs(output_path)
    logger.info(
        "saor post process completed: top=%.3f deg bottom=%.3f deg outputs=%s",
        float(top_angle),
        float(bottom_angle),
        list(outputs),
    )

    return {
        "output_directory": str(output_path.resolve()),
        "script": str(Path(script_path).resolve()),
        "saor_from_top_deg": float(top_angle),
        "saor_from_bottom_deg": float(bottom_angle),
        "row_count": int(len(result_data)),
        "outputs": outputs,
    }


def _verify_outputs(output_path: Path) -> dict[str, str]:
    """必須ファイルが生成され、空でないことを確認する。"""
    missing: list[str] = []
    empty: list[str] = []
    outputs: dict[str, str] = {}

    for filename in EXPECTED_OUTPUT_FILENAMES:
        file_path = output_path / filename
        if not file_path.is_file():
            if filename in REQUIRED_OUTPUT_FILENAMES:
                missing.append(filename)
            continue
        if file_path.stat().st_size == 0:
            empty.append(filename)
            continue
        outputs[filename] = str(file_path.resolve())

    if missing or empty:
        raise SaorPostProcessError(
            f"ポスト処理の出力が不正です(未生成: {missing}、空ファイル: {empty})。"
            f"出力先: {output_path}"
        )
    return outputs
