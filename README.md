# POSCAP DEMパラメータ同定自動化システム

Ansys Rocky 2025 R2とPyRockyを用いて、POSCAP素子成形シミュレーション向けのDEMパラメータを同定するシステムです。

粒度分布の準備から、せん断試験・安息角試験・応答曲面による粉体パラメータ同定、壁面摩擦試験までを実行します。長時間実行を前提として、工程単位の再開、進捗確認、中間結果保存、エラーログ保存に対応しています。

## 対象フェーズ

1. **フェーズ0: 粒度分布・粒子発生**
	 - せん断試験条件表の作成
	 - 粒子発生シミュレーション
	 - Particle Custom Inlet用データの作成
2. **フェーズ1: 粉体特性の同定**
	 - 9条件のせん断試験（充填、プリせん断、本せん断3/5/7 kPa）
	 - 安息角シミュレーションとポスト処理
	 - せん断・安息角の応答曲面作成
	 - 応答曲面の重ね合わせによる転がり抵抗・動摩擦・静止摩擦の同定
3. **フェーズ2: 壁面摩擦特性の同定**
	 - 壁面摩擦3条件の充填、プリせん断、本せん断
	 - 壁面摩擦係数の評価

## 動作環境

- Windows 10/11
- Python 3.11以上
- Ansys Rocky 2025 R2
- Microsoft Excel
	- Excelブックの数式再計算を伴う工程で使用します。
- Python依存パッケージ
	- pandas
	- numpy
	- scipy
	- matplotlib
	- openpyxl
	- PyYAML
- PyRocky（RockyのPython環境または利用可能なPython環境に設定済みであること）

Rockyの既定実行ファイルは次のパスを使用します。

```text
C:\Program Files\ANSYS Inc\v252\Rocky\bin\Rocky.exe
```

## セットアップ

PowerShellでリポジトリ直下へ移動し、編集可能モードでインストールします。

```powershell
python -m pip install -e .
```

これにより、実行状況を確認する`poscap`コマンドが利用可能になります。

```powershell
poscap --help
```

## フォルダ構成

```text
parameter_identification_2/
├─ config/
│  ├─ default.yaml                 # 案件・同定条件の既定設定
│  └─ rocky_2025r2.yaml            # Rockyオブジェクト名・テンプレート設定
├─ docs/
│  ├─ requirements.md              # 要件定義
│  ├─ workflow.md                  # 業務フロー
│  └─ Rocky.md                     # Rocky/PyRocky操作仕様
├─ input/
│  ├─ experimental/                # 実験データ
│  └─ particle_distribution/       # 入力粒度分布CSV
├─ projects/
│  └─ {project_id}/                # 案件ごとの実行結果・中間結果
│     ├─ shear_test/               # せん断試験
│     ├─ saor_test/                # 安息角試験
│     ├─ wall_friction_test/       # 壁面摩擦試験
│     ├─ rsm/                      # 応答曲面と重ね合わせ結果
│     ├─ pipeline/                 # 通し実行の工程別状態・ログ
│     ├─ logs/                     # ラン全体のログ
│     ├─ progress.json             # 現在実行中のフェーズ・工程
│     ├─ run_journal.jsonl         # 時系列の実行イベント
│     ├─ identified_parameters.json # 同定値と履歴
│     └─ pipeline_summary.json      # 通し実行の最終サマリ
├─ scripts/
│  ├─ run_pipeline.py              # フェーズ0〜2の通し実行
│  ├─ run_all_conditions.py        # せん断9条件のバッチ実行
│  ├─ run_saor.py                  # 安息角シミュレーション
│  ├─ run_wall_friction_*.py       # 壁面摩擦試験の各工程
│  ├─ export_*response_surface.py  # 応答曲面用データ出力
│  ├─ rsm_cubic_polynomial_*.py    # 3次多項式応答曲面
│  └─ overlay_targets.py           # 応答曲面の重ね合わせ・同定値記録
├─ src/poscap_calibration/
│  ├─ rocky/                       # PyRocky操作・シミュレーション実行
│  ├─ workflows/                   # フェーズ別ワークフローとパイプライン
│  ├─ state/                       # 状態、進捗、同定値、レポート管理
│  ├─ analysis/                    # 解析処理
│  ├─ experimental/                # 実験データ処理
│  ├─ particle_distribution/       # 粒度分布処理
│  ├─ reporting/                   # レポート処理
│  ├─ validation/                  # 入力・結果検証
│  ├─ cli.py                       # poscapコマンド
│  └─ project_layout.py            # 案件フォルダ構成の定義
├─ templates/
│  ├─ excel/                       # 解析Excelテンプレート
│  └─ rocky/                       # Rockyプロジェクトテンプレート
├─ tests/
│  ├─ unit/                        # 単体テスト
│  ├─ integration/                 # 結合テスト
│  └─ reference_data/              # テスト用参照データ
├─ pyproject.toml
└─ README.md
```

## 通し実行

実験データから得たピーク比、せん断定常傾き、安息角を指定して実行します。

```powershell
python scripts/run_pipeline.py `
	--project-id 0 `
	--peak-ratio 1.05 `
	--shear-target 0.69898 `
	--saor-target 42.9 `
	--show-gui
```

`--show-gui`を付けるとRocky GUIを表示して実行します。省略時はheadless実行です。

実行前に対象工程と完了済み工程を確認できます。

```powershell
python scripts/run_pipeline.py --project-id 0 --dry-run
```

### 一部のみ実行

```powershell
# フェーズ2のみ
python scripts/run_pipeline.py --project-id 0 --phases phase2 `
	--peak-ratio 1.05 --shear-target 0.69898 --show-gui

# 指定工程から再開
python scripts/run_pipeline.py --project-id 0 `
	--start-from phase1_rsm_shear `
	--peak-ratio 1.05 --shear-target 0.69898 --saor-target 42.9

# 完了済み工程も再実行
python scripts/run_pipeline.py --project-id 0 --force `
	--peak-ratio 1.05 --shear-target 0.69898 --saor-target 42.9 --show-gui
```

既定では工程が失敗した時点で停止します。後続工程も試行する場合は`--continue-on-error`を指定します。

## 長時間実行の監視

実行中に別のPowerShellを開き、以下のコマンドで確認します。

```powershell
# フェーズ、工程、条件ごとの状態
poscap status --project-id 0 --verbose

# 直近40件の実行イベント
poscap journal --project-id 0 --tail 40

# 失敗工程、例外、工程ログ末尾
poscap errors --project-id 0

# 通し実行の最終結果
poscap results --project-id 0

# 同定済みパラメータ
poscap params --project-id 0
```

## 再開と完了判定

通し実行では各工程の状態を次の場所へ保存します。

```text
projects/{project_id}/pipeline/{stage}/status.json
projects/{project_id}/pipeline/{stage}/stage.log
```

`status.json`が`completed`で、かつ工程の成果物が存在する場合、次回実行ではその工程を自動的にスキップします。成果物が削除されている場合は、状態が`completed`でも再実行します。

途中停止後は、同じコマンドを再実行することで未完了工程から継続できます。意図的にやり直す場合は`--force`、開始位置を限定する場合は`--start-from`を使用します。

## 主な成果物

### フェーズ1

```text
projects/{project_id}/shear_test/shear_analysis.xlsx
projects/{project_id}/shear_test/shear_response_surface_data.csv
projects/{project_id}/saor_test/saor_analysis.xlsx
projects/{project_id}/saor_test/saor_response_surface_data.csv
projects/{project_id}/rsm/phase1/shear/outputs/
projects/{project_id}/rsm/phase1/saor/outputs/
projects/{project_id}/rsm/phase1/combined/outputs/
```

重ね合わせ工程で決定した粉体パラメータは、次のファイルへ自動記録されます。

```text
projects/{project_id}/identified_parameters.json
```

### フェーズ2

```text
projects/{project_id}/wall_friction_test/wall_friction_analysis.xlsx
projects/{project_id}/wall_friction_test/fill/
projects/{project_id}/wall_friction_test/condition_01/
projects/{project_id}/wall_friction_test/condition_02/
projects/{project_id}/wall_friction_test/condition_03/
```

Excelなどで最終決定した壁面摩擦係数は、次のように記録できます。

```powershell
poscap record-params --project-id 0 --phase phase2 `
	wall_dynamic_friction=0.31 wall_static_friction=0.34 `
	--source projects/0/wall_friction_test/wall_friction_analysis.xlsx
```

## 個別工程の実行

調査や再試行のため、各工程を単独でも実行できます。

| スクリプト | 処理 |
|---|---|
| `scripts/run_generate_particle.py` | 粒子発生と粒子データ取得 |
| `scripts/run_prepare_filling.py` | Particle Custom Inlet用CSVと充填プロジェクトの作成 |
| `scripts/run_all_conditions.py` | せん断9条件の充填・プリせん断・本せん断 |
| `scripts/run_saor.py` | 安息角シミュレーションとポスト処理 |
| `scripts/run_wall_friction_filling.py` | 壁面摩擦試験の充填 |
| `scripts/run_wall_friction_pre_shear.py` | 壁面摩擦試験のプリせん断 |
| `scripts/run_wall_friction_shear_test.py` | 壁面摩擦試験の本せん断 |
| `scripts/export_response_surface.py` | せん断応答曲面用CSV出力 |
| `scripts/export_saor_response_surface.py` | 安息角応答曲面用CSV出力 |
| `scripts/rsm_cubic_polynomial_Shear.py` | せん断応答曲面作成 |
| `scripts/rsm_cubic_polynomial_SAOR.py` | 安息角応答曲面作成 |
| `scripts/overlay_targets.py` | 応答曲面の重ね合わせと粉体パラメータ同定 |

各スクリプトの引数は`--help`で確認できます。

```powershell
python scripts/run_wall_friction_pre_shear.py --help
```

## テスト

```powershell
python -m pytest tests/unit -q
```

Rockyを実際に起動する処理は、テンプレート、ライセンス、実行環境が必要です。単体テストではRocky本体を起動しません。

## 注意事項

- `projects/`配下は実行結果です。テンプレートは`templates/`配下を使用します。
- Rockyプロジェクトは`.rocky`と対応する`.rocky.files`を一組として扱います。
- GUIで実行内容を確認する場合は、通し実行に`--show-gui`を指定してください。
- OneDrive上では同期中のファイルロックによりRockyの保存が失敗することがあります。問題が続く場合は同期状態とファイル属性を確認してください。
- 同じ案件を複数プロセスから同時実行しないでください。`progress.json`やExcel、Rockyプロジェクトが競合する可能性があります。

## ドキュメント

- [要件定義](docs/requirements.md)
- [業務フロー](docs/workflow.md)
- [Rocky/PyRocky操作仕様](docs/Rocky.md)
