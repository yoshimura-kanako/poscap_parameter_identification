# POSCAP DEMパラメータ同定 Rocky操作仕様

- 文書版: Draft 0.1
- 作成日: 2026-08-17
- 参照文書: `requirements.md`
- 業務フロー: `workflow.md`
- 対応バージョン: Ansys Rocky 2025 R2(第1版はこのバージョンのみ)

## 1. 目的

本書は、POSCAP DEMパラメータ同定自動化システムにおいて、Ansys RockyおよびPyRockyで実行する具体的な操作を定義する。

業務上の処理順序および判断条件は `Work_Flow.md` に記載し、本書ではRocky固有の以下の内容を扱う。

- Rockyプロジェクトの操作
- パラメータの設定先
- Particle Custom Inletの設定
- シミュレーション実行
- Cross PlotおよびTime Plotからの結果取得
- Geometry位置の取得および設定
- Rockyバージョン差
- 保存、終了およびエラー処理

---

## 2. 基本方針

### 2.1 テンプレート保護

- Rockyテンプレート原本を直接編集しない。
- 案件および条件ごとにテンプレートをコピーして使用する。
- 既存結果を明示的な許可なしに削除しない。
- 作業用プロジェクトはローカルフォルダに配置する。
- OneDriveまたはSharePointへの保存は計算完了後に行う。

### 2.2 プロジェクト命名規則

```text
{案件ID}_{試験}_{条件番号}_{工程}_{荷重}
```

例:

```text
POSCAP001_SHEAR_GENERATE
POSCAP001_SHEAR_C01_FILL
POSCAP001_SHEAR_C01_PRE
POSCAP001_SHEAR_C01_TEST_3KPA
POSCAP001_SHEAR_C01_TEST_5KPA
POSCAP001_SHEAR_C01_TEST_7KPA
POSCAP001_SAOR_C01
POSCAP001_WALL_C01_PRE
POSCAP001_WALL_C01_TEST_3KPA
```

粒子発生は粒度分布単位で1回のみ実行するため条件番号を含めない。充填以降は条件ごとに実行するため条件番号を含める。

### 2.3 自動化レベル

以下の3区分で管理する。

- `CONFIRMED`: PyRockyでの操作方法を実機確認済み
- `UNCONFIRMED`: 操作対象は明確だがPyRocky APIを未確認
- `MANUAL`: 現時点では手動操作とする

未確認のPyRocky APIを推測して実装しない。

---

## 3. Rocky起動および接続

### 3.1 Rocky実行ファイル

設定ファイルからRocky.exeのパスを取得する。

```yaml
rocky:
  version: "2025R2"
  executable_path: "C:/Program Files/ANSYS Inc/v252/rocky/bin/Rocky.exe"
```

### 3.2 PyRocky接続情報

- Host: `127.0.0.1`
- Port: 設定ファイルで指定する
- Rocky実行ユーザーとPython実行ユーザーを一致させる
- 接続後にRockyバージョンを確認する

### 3.3 起動前確認

- Rocky.exeが存在する
- 作業フォルダに書込み権限がある
- 指定ポートが使用可能である
- 同じポートで別のRockyが稼働していない
- ライセンスが使用可能である
- テンプレートが存在する

### 3.4 接続失敗時

以下をログに保存する。

- Rocky.exeのパス
- 起動コマンド
- Host
- Port
- RockyプロセスID
- RockyとPythonの実行ユーザー
- 使用バージョン
- 例外メッセージ
- スタックトレース

自動再試行回数は設定ファイルで管理する。

---

## 4. 共通DEM設定

### 4.1 Physics

| 設定項目 | 値 |
|---|---|
| Gravity Y | -9.81 m/s² |
| Normal Force | Hysteretic Linear Spring |
| Tangential Force | Linear Spring Coulomb Limit |
| Adhesive Force | None |
| Rolling Resistance Model | Type C: Linear Spring Rolling Limit |
| Numerical Softening Factor | 1 |

### 4.2 Particle

| 設定項目 | 値 |
|---|---|
| Shape | Sphere |
| Size Type | Sieve Size |
| Enable Rotations | True |
| Density | 案件入力データを使用(下記は参考値: 2.9 g/cm³) |
| Young's Modulus | 1.07E+06 |
| Poisson's Ratio | 0.3 |

粒度分布および密度は案件の入力データを使用する。Young's ModulusおよびPoisson's Ratioは粉体に依らない共通値として扱う。

### 4.3 設定値の検証

Rockyへ値を設定した後、可能な場合は同じ値を再取得し、設定値と一致することを確認する。

---

## 5. 粒子発生操作

### 5.1 使用テンプレート

```text
templates/shear/generate/
```

実際のテンプレートファイル名は設定ファイルで指定する。

### 5.2 設定項目

- DEM用粒度分布
- Solver設定
- 出力先
- CGM Scale Factor
- シミュレーション終了時刻

### 5.3 シミュレーション条件

- 周期境界: なし
- 粒子発生方式: Volumetric Inlet
- シミュレーション時間: 1マイクロ秒
- Output Time Interval: 1e-6秒

### 5.4 結果取得 [UNCONFIRMED]

以下の設定済みオブジェクトを使用する。

- Cross Plot: `Cross Plot <04>`
- User Process: `First_20deg`
- 対象時刻: 0秒
- 出力内容:
  - X座標
  - Y座標
  - Z座標
  - 粒子径

### 5.5 出力

```text
particle_generation/
├─ raw/
│  └─ first_20deg_raw.csv
└─ converted/
   └─ particle_custom_inlet.csv
```

### 5.6 完了条件

- Rocky計算が正常終了している
- 出力CSVが存在する
- CSVのファイルサイズが0ではない
- 粒子数が0ではない
- X、Y、Z、Particle Size列が存在する
- Particle Custom Inlet変換が成功している

---

## 6. Particle Custom Inlet CSV

### 6.1 出力形式

```csv
x,y,z,size
0.000599,0.032000,0.002970,0.0000879
```

### 6.2 変換項目

| Rocky出力 | Particle Custom Inlet |
|---|---|
| Coordinate X | x |
| Coordinate Y | y |
| Coordinate Z | z |
| Particle Size | size |

### 6.3 粗視化倍率

粒子径へ粗視化倍率を適用するかどうかは設定ファイルで管理する。

```yaml
particle_custom_inlet:
  size_scale_mode: "unconfirmed"
  size_scale_factor: 1.5
```

実際のRocky出力に粗視化後の粒子径が含まれるかを実機で確認してから設定を確定する。

粗視化倍率の二重適用を防ぐため、変換前後の最小径、最大径、平均径をログへ保存する。

### 6.4 検証 [UNCONFIRMED]

- 必須列が存在する
- 欠損値がない
- すべて数値である
- x、y、zの単位がmである
- sizeが正である
- 粒子数が0でない
- 変換前後の粒子数が一致する

---

## 7. 充填操作

### 7.1 使用テンプレート

```text
templates/shear/fill/
```

### 7.2 粉体パラメータ

条件ごとに以下を設定する。

- Rolling Resistance
- Particles-Particles Dynamic Friction
- Particles-Particles Static Friction

```text
Static Friction
= Dynamic Friction × 実験ピーク比
```

### 7.3 Particle Custom Inlet

粒子発生結果のParticle Custom Inlet CSVを設定する。

設定後、以下を確認する。

- ファイルパスが正しい
- CSVを読み込める
- 読込み粒子数が0ではない
- 粒子径に異常値がない

### 7.4 シミュレーション条件

- 周期境界: Cylindrical
- Number of Divisions: 18
- シミュレーション時間: 0.5秒
- Output Time Interval: 0.01秒
- CGM Scale Factor: 1.5

### 7.5 結果取得 [UNCONFIRMED]

- Cross Plot: `coords_size_cross_id`
- User Process: `Split`
- 対象時刻: 最終時刻
- 対象範囲: 底から1 ml
- 出力内容:
  - X座標
  - Y座標
  - Z座標
  - 粒子径

### 7.6 出力

```text
condition_01/fill/
├─ project/
├─ raw/
│  └─ particles_1ml_raw.csv
├─ converted/
│  └─ particles_1ml_inlet.csv
└─ status.json
```

---

## 8. プリせん断操作

### 8.1 使用テンプレート

```text
templates/shear/pre_shear/
```

### 8.2 設定項目

- Rolling Resistance
- Particles-Particles Dynamic Friction
- Particles-Particles Static Friction
- 充填結果のParticle Custom Inlet CSV
- Solver設定

### 8.3 シミュレーション条件

- プリせん断荷重: 9 kPa
- シミュレーション時間: 0.75秒
- Output Time Interval: 0.001秒
- 周期境界分割数: 18

### 8.4 せん断セル高さ取得 [UNCONFIRMED]

- Geometry名: `FT4_ShearCell2_5deg_mm`
- 取得値: Geometryの最大Y座標
- Time Plot: `Lid_Height`
- 対象時刻: 最終時刻

取得した値は次の形式で保存する。

```json
{
  "geometry": "FT4_ShearCell2_5deg_mm",
  "time_s": 0.75,
  "maximum_y_m": null
}
```

### 8.5 粒子結果取得 [UNCONFIRMED]

- Cross Plot: `Cross Plot <01>`
- 対象時刻: 最終時刻
- 出力内容:
  - X座標
  - Y座標
  - Z座標
  - 粒子径

Particle Custom Inlet形式へ変換し、本せん断へ渡す。

### 8.6 出力

```text
condition_01/pre_shear/
├─ project/
├─ raw/
│  ├─ shear_cell_height.json
│  └─ particles_raw.csv
├─ converted/
│  └─ particles_inlet.csv
└─ status.json
```

---

## 9. 本せん断操作

### 9.1 使用テンプレート

- `templates/shear/shear_3kpa/`
- `templates/shear/shear_5kpa/`
- `templates/shear/shear_7kpa/`

### 9.2 共通設定

- Rolling Resistance
- Particles-Particles Dynamic Friction
- Particles-Particles Static Friction
- プリせん断結果のParticle Custom Inlet CSV
- プリせん断で取得したせん断セル高さ
- Solver設定

### 9.3 せん断セル位置設定

- Geometry名: `FT4_ShearCell2_5deg_mm`
- 設定箇所: Transform > Translation > Y
- 設定値: プリせん断最終時刻の最大Y座標

設定後、可能な場合は値を再取得して一致を確認する。

### 9.4 シミュレーション条件

- 荷重: 3、5、7 kPa
- シミュレーション時間: 0.55秒
- Output Time Interval: 0.001秒
- 周期境界分割数: 18

### 9.5 トルク取得 [UNCONFIRMED]

- Time Plot名: `Lid_Moment_Force`
- 対象: せん断セルにかかるトルク
- 出力: 時刻とトルクの時系列CSV

### 9.6 出力

```text
condition_01/
├─ shear_3kpa/
│  ├─ torque.csv
│  └─ status.json
├─ shear_5kpa/
│  ├─ torque.csv
│  └─ status.json
└─ shear_7kpa/
   ├─ torque.csv
   └─ status.json
```

---

## 10. せん断応力計算

### 10.1 入力

- トルクT
- セル寸法r
- 周期境界分割数n

使用する式は手順書および既存解析Excelの定義と一致させる。

> 注意: 手順書本文の式と変数説明について、rが半径か直径かを既存解析Excelと突合して確定する。確定するまでは計算定数をコードへ固定しない。

### 10.2 定常区間

```text
0.501秒以上、0.55秒以下
```

### 10.3 回帰

- 説明変数: 垂直荷重3、5、7 kPa
- 目的変数: 定常せん断応力
- 切片: 0固定
- 出力: 回帰傾き、確認用指標、グラフ

---

## 11. 安息角操作

### 11.1 使用テンプレート

```text
templates/saor/
```

### 11.2 設定項目

- 粒度分布
- Rolling Resistance
- Particles-Particles Dynamic Friction
- Particles-Particles Static Friction
- Solver設定

### 11.3 シミュレーション条件

- 流量: 0.7 g/s
- 粒子発生時間: 28.5714秒
- シミュレーション終了時刻: 30秒
- CGM Scale Factor: 7
- 周期境界: なし
- Output Time Interval: 1秒

### 11.4 Rockyバージョン別解析 [UNCONFIRMED]

| Rockyバージョン | 解析処理 |
|---|---|
| 2025 R2 | `Pana – Calibration 1: SAOR v242` |

### 11.5 出力

- `experiment_points.csv`
- 安息角
- 解析画像
- 実行ログ

Rocky内スクリプトをPyRockyから実行できるかは、実機で確認する。

---

## 12. 壁面摩擦操作

### 12.1 粉体パラメータ

フェーズ1で決定した以下を設定する。

- Rolling Resistance
- Particles-Particles Dynamic Friction
- Particles-Particles Static Friction

### 12.2 壁面摩擦パラメータ

- Particles-Dies Steel Dynamic Friction
- Particles-Dies Steel Static Friction

標準設定では静止摩擦係数と動摩擦係数を同値とする。

### 12.3 プリせん断 [UNCONFIRMED]

- 荷重: 9 kPa
- シミュレーション時間: 0.75秒
- Geometry名: `Wall_Friction_Disc_24mm_5deg`
- Time Plot名: `Lid_Height`
- Cross Plot名: `Cross Plot <01>`

最終時刻の壁面摩擦ディスク最大Y座標と粒子CSVを取得する。

### 12.4 本せん断 [UNCONFIRMED]

- 荷重: 3、5、7 kPa
- シミュレーション時間: 0.25秒
- GeometryのTranslation Yへプリせん断結果を設定する
- Time Plot `Lid_Moment_Force` からトルクを取得する

### 12.5 定常区間

```text
0.201秒以上、0.25秒以下
```

### 12.6 回帰

- 説明変数: 垂直荷重
- 目的変数: 定常せん断応力
- 切片: 固定しない
- 出力: 定常傾き

---

## 13. シミュレーション完了判定

以下をすべて満たした場合に完了とする。

- Rockyが異常終了していない
- 計算終了時刻へ到達している
- 必要な結果が生成されている
- CSVが存在する
- CSVのファイルサイズが0ではない
- 必須列が存在する
- 数値列に欠損がない
- 次工程へ渡すデータが生成されている

Rockyプロセスが終了しただけでは正常完了と判断しない。

---

## 14. 保存および終了

### 14.1 保存

- テンプレートとは別の作業用パスへ保存する
- 保存成功を確認してからRockyを終了する
- 保存先パスをログへ記録する
- 既存ファイルを無許可で上書きしない

### 14.2 Rocky終了

- 実行中の場合は終了しない
- 保存中の場合は終了しない
- 正常保存後にPyRocky接続を切断する
- 必要に応じてRockyプロセスを終了する

### 14.3 異常終了時

- Rockyプロセスを強制終了する前にログを保存する
- 作業中ファイルを削除しない
- 完了済み前工程の結果を保持する
- 再開対象工程を記録する

---

## 15. Rockyオブジェクト設定の外部化

Rocky 2025 R2向けのオブジェクト情報はコードへ直書きせず、単一の設定ファイルへ分離する。

```yaml
rocky:
  version: "2025R2"

objects:
  shear:
    fill_cross_plot: "coords_size_cross_id"
    pre_cross_plot: "Cross Plot <01>"
    lid_height_plot: "Lid_Height"
    torque_plot: "Lid_Moment_Force"
    shear_cell_geometry: "FT4_ShearCell2_5deg_mm"

  wall:
    lid_height_plot: "Lid_Height"
    torque_plot: "Lid_Moment_Force"
    wall_disc_geometry: "Wall_Friction_Disc_24mm_5deg"
```

2025 R2で確認する項目:

- 接続方法
- Rockyオブジェクト取得方法
- パラメータ設定方法
- 計算開始・完了確認方法
- Plotデータ取得方法
- Geometry座標取得方法
- Rockyスクリプト実行方法
- 保存方法
- 終了方法

---

## 16. PyRocky API確認表

| 操作 | 状態 | 確認内容 |
|---|---|---|
| Rockyへの接続 | 要確認 | バージョン別接続可否 |
| プロジェクトを開く | 要確認 | rcyとarchiveの扱い |
| 名前を付けて保存 | 要確認 | テンプレート保護 |
| 粒度分布設定 | 要確認 | Size Distribution API |
| 転がり抵抗設定 | 要確認 | 対象オブジェクト |
| 動摩擦係数設定 | 要確認 | Interaction API |
| 静止摩擦係数設定 | 要確認 | Interaction API |
| Custom Inlet CSV設定 | 要確認 | ファイルパス設定 |
| Geometry Translation設定 | 要確認 | Y座標設定 |
| シミュレーション開始 | 要確認 | 実行API |
| 完了状態取得 | 要確認 | Status API |
| Cross Plot出力 | 要確認 | CSV API |
| Time Plot出力 | 要確認 | CSV API |
| Rockyスクリプト実行 | 要確認 | 安息角解析 |
| プロジェクト終了 | 要確認 | 保存後終了 |

APIが確認できた項目から `CONFIRMED` へ変更し、使用したコード例を本書に追記する。

---

## 17. 実装時の禁止事項

- 存在を確認していないPyRocky APIを推測して呼び出さない
- テンプレート原本を編集しない
- 結果を無条件に削除しない
- Rocky計算終了前にプロセスを終了しない
- 粗視化倍率を複数箇所で適用しない
- Cross Plot名やGeometry名をコードへ複数箇所で直接記述しない
- 保存成功を確認せず次工程へ進まない
- 前工程の条件と異なるCSVを次工程へ渡さない
