# AGENTS.md

このファイルは GitHub Copilot CLI などのコーディングエージェントが、本リポジトリで
POSCAP DEMパラメータ同定の一連の流れを安全に実行・監視するための指示書です。

## プロジェクト概要

Ansys Rocky 2025 R2 / PyRockyを用いて、POSCAP素子成形シミュレーション向けDEMパラメータ
(転がり抵抗・粉間動摩擦・粉間静止摩擦・壁面摩擦係数)を同定するシステムです。
詳細な業務フローは [docs/workflow.md](docs/workflow.md)、要件は
[docs/requirements.md](docs/requirements.md)、Rocky/PyRocky操作仕様は
[docs/Rocky.md](docs/Rocky.md)、セットアップ・コマンド一覧は [README.md](README.md) を参照してください。

## 動作環境の前提

- Windows + Ansys Rocky 2025 R2 (`C:\Program Files\ANSYS Inc\v252\rocky\bin\Rocky.exe`) が
  実機にインストールされていることが前提です。エージェント自身がRockyやライセンスを用意することはできません。
- 初回セットアップ: `python -m pip install -e .`（`poscap`コマンドが有効になる）
- 依存変更後は再インストールが必要: `pip install -e . --no-deps`

## 一連の流れを実行する

通し実行の実体は `scripts/run_pipeline.py`（phase0→1→2、全15工程）です。

パラメータ同定フローを開始する際は、他の作業より先に必ず以下をユーザーへ確認してください
（`--dry-run`の提示や実行より前に行うこと）。

1. DEM用粒度分布ファイル（csv）の場所
2. ピーク比（実験データ解析で得られた値。エージェントが推測・捏造してはいけない）

```powershell
python scripts/run_pipeline.py --project-id 0 --dry-run
```

まず `--dry-run` で実行予定/完了済み工程を確認し、その内容をユーザーへ提示して
承認を得てから実行してください（`config/default.yaml` の
`safety.require_confirmation_before_run: true` に対応。詳細は
docs/requirements.md の FR-14a・NFR-03）。

```powershell
python scripts/run_pipeline.py --project-id 0 `
    --peak-ratio <実験ピーク比> --shear-target <実験せん断定常傾き> --saor-target <実験安息角>
```

- `--peak-ratio` / `--shear-target` / `--saor-target` は実験データ解析で得られた値です。
  **エージェントが推測・捏造してはいけません。** 値が不明な場合はユーザーに確認するか、
  既存の実験データ解析結果（`projects/{id}/` 配下や解析Excel）から取得してください。
- `--phases phase2` や `--start-from <stage>` で部分実行・再開ができます（詳細はREADME）。
- `--force` （完了済み工程の再実行）や、テンプレート原本の変更、既存結果の上書き・削除は
  ユーザーの明示的な指示がない限り行わないでください。

## 長時間実行と監視

1回の通し実行は数十分〜数時間かかることがあります。フォアグラウンドで待機し続けず、
バックグラウンド実行にして、別ターミナルから状況確認コマンドで進捗を追ってください。

```powershell
poscap status --project-id 0 --verbose   # フェーズ・工程・条件ごとの状態
poscap journal --project-id 0 --tail 40  # 直近の実行イベント
poscap errors  --project-id 0            # 失敗工程とエラーログ抜粋
poscap results --project-id 0            # 通し実行の最終結果サマリ
poscap params  --project-id 0            # 同定済みパラメータ
```

工程の完了判定は `projects/{project_id}/pipeline/{stage}/status.json` が `completed` かつ
成果物が実在することです。中断後は同じコマンドを再実行すれば未完了工程から継続します。

## 人による確認が必要なポイント

以下は自動で先へ進めず、ユーザーに確認・承認を求めてください（docs/workflow.md 3章、
docs/requirements.md 11章）。

- フェーズ0で最大/最小粒子径を推定・追加した場合や微粉カットを行った場合
- フェーズ1の応答曲面・交点候補が複数ある場合（粉体パラメータの最終確定）
- フェーズ1結果確認後にフェーズ2へ進む判断
- 最終結果・レポート出力前の最終確認

## テスト

```powershell
python -m pytest tests/unit
python -m pytest tests/integration
```
