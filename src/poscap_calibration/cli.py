"""CLIエントリポイント。実行状況・中間結果・同定値を確認する(``poscap``コマンド)。

シミュレーション本体は``scripts/``配下のスクリプトが実行する。本CLIは実行中/停止後を問わず
プロジェクトフォルダを読むだけなので、長時間バッチの裏で別ターミナルから使える。

実行例::

    poscap status                 # フェーズ別の進捗と中間結果の一覧
    poscap status --verbose       # せん断9条件の工程別状況も表示
    poscap journal --tail 30      # 直近イベントを時系列で表示
    poscap errors                 # 失敗した工程とエラーログの抜粋
    poscap results                # 通し実行の最終結果サマリ
    poscap params                 # 同定値(フェーズ1粉体/フェーズ2壁面摩擦)
    poscap record-params --phase phase2 wall_dynamic_friction=0.31
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from poscap_calibration.project_layout import (
    DEFAULT_PROJECT_ID,
    DEFAULT_PROJECT_ROOT,
    ProjectLayout,
)
from poscap_calibration.state.identified_parameters import (
    PHASE2,
    format_identified_parameters,
    load_identified_parameters,
    record_identified_parameters,
)
from poscap_calibration.state.progress_report import (
    PIPELINE_SUMMARY_FILENAME,
    build_report,
    collect_failures,
    format_failures,
    format_report,
)
from poscap_calibration.state.run_journal import read_journal


def _add_project_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="poscap",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="フェーズ別の進捗と中間結果を表示する")
    _add_project_arguments(status)
    status.add_argument("--verbose", action="store_true", help="条件ごとの工程状況も表示する")
    status.add_argument("--json", action="store_true", help="JSONで出力する")

    journal = subparsers.add_parser("journal", help="実行ジャーナル(時系列イベント)を表示する")
    _add_project_arguments(journal)
    journal.add_argument("--tail", type=int, default=30, help="表示する末尾イベント数(0で全件)")
    journal.add_argument("--json", action="store_true", help="JSON Linesのまま出力する")

    params = subparsers.add_parser("params", help="同定済みパラメータを表示する")
    _add_project_arguments(params)
    params.add_argument("--json", action="store_true", help="JSONで出力する")

    errors = subparsers.add_parser("errors", help="失敗した工程とエラーログを表示する")
    _add_project_arguments(errors)
    errors.add_argument("--json", action="store_true", help="JSONで出力する")

    results = subparsers.add_parser("results", help="通し実行の最終結果サマリを表示する")
    _add_project_arguments(results)
    results.add_argument("--json", action="store_true", help="JSONで出力する")

    record = subparsers.add_parser(
        "record-params",
        help="同定値を記録する(Excelで求めたフェーズ2の値など)",
    )
    _add_project_arguments(record)
    record.add_argument("--phase", default=PHASE2, help="phase1 または phase2")
    record.add_argument(
        "values", nargs="+", metavar="NAME=VALUE", help="例: wall_dynamic_friction=0.31"
    )
    record.add_argument("--source", default=None, help="取得元(Excelパス等)")
    record.add_argument("--notes", default=None, help="備考")

    return parser


def _layout(arguments: argparse.Namespace) -> ProjectLayout:
    return ProjectLayout(arguments.project_id, arguments.project_root)


def _command_status(arguments: argparse.Namespace) -> int:
    report = build_report(_layout(arguments))
    if arguments.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(format_report(report, verbose=arguments.verbose))
    return 0


def _command_journal(arguments: argparse.Namespace) -> int:
    directory = _layout(arguments).project_directory
    records = read_journal(directory, tail=arguments.tail or None)
    if not records:
        print(f"実行ジャーナルがありません: {directory}")
        return 0

    for record in records:
        if arguments.json:
            print(json.dumps(record, ensure_ascii=False, default=str))
            continue
        scope = "/".join(part for part in (record.get("phase"), record.get("step")) if part)
        line = f"{record.get('time', '-')} {record.get('kind', '-'):<12}"
        if scope:
            line += f" [{scope}]"
        if record.get("message"):
            line += f" {record['message']}"
        details = record.get("details")
        if details:
            line += f"  {json.dumps(details, ensure_ascii=False, default=str)}"
        print(line)
    return 0


def _command_params(arguments: argparse.Namespace) -> int:
    directory = _layout(arguments).project_directory
    document = load_identified_parameters(directory)
    if arguments.json:
        print(json.dumps(document, ensure_ascii=False, indent=2, default=str))
    else:
        print(format_identified_parameters(document))
    return 0


def _command_record_params(arguments: argparse.Namespace) -> int:
    values: dict[str, float] = {}
    for item in arguments.values:
        name, separator, raw = item.partition("=")
        if not separator:
            print(f"エラー: NAME=VALUE 形式で指定してください: {item}", file=sys.stderr)
            return 1
        try:
            values[name.strip()] = float(raw)
        except ValueError:
            print(f"エラー: 数値として読めません: {item}", file=sys.stderr)
            return 1

    path = record_identified_parameters(
        _layout(arguments).project_directory,
        arguments.phase,
        values,
        source=arguments.source,
        notes=arguments.notes,
    )
    print(f"同定値を記録しました: {path}")
    return 0


def _command_errors(arguments: argparse.Namespace) -> int:
    failures = collect_failures(_layout(arguments))
    if arguments.json:
        print(json.dumps(failures, ensure_ascii=False, indent=2, default=str))
    else:
        print(format_failures(failures))
    return 1 if failures else 0


def _command_results(arguments: argparse.Namespace) -> int:
    directory = _layout(arguments).project_directory
    summary_path = directory / PIPELINE_SUMMARY_FILENAME
    if not summary_path.is_file():
        print(f"通し実行のサマリがありません: {summary_path}")
        print("`python scripts/run_pipeline.py ...` を実行すると作成されます。")
        return 0

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if arguments.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return 0

    from poscap_calibration.workflows.pipeline import format_summary

    print(format_summary(summary))
    return 1 if summary.get("failed_stages") else 0


_COMMANDS = {
    "status": _command_status,
    "journal": _command_journal,
    "params": _command_params,
    "record-params": _command_record_params,
    "errors": _command_errors,
    "results": _command_results,
}


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        return _COMMANDS[arguments.command](arguments)
    except FileNotFoundError as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
