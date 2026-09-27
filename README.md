# 印旛沼流域 GIS解析プラットフォーム（gisdata）

千葉県印旛沼流域を対象に、空間演算・ラスタ解析・ポテンシャル測定を行い、
結果を静的サイトとして公開するためのリポジトリです。

## 設計方針

- **原則として静的配信**。サーバーを常時起動させず、コストを最小化する
- **重い処理（ラスタ解析・流域解析など）は事前バッチで計算**し、結果を
  Cloud Optimized GeoTIFF（COG）/ PMTiles として書き出す
- **軽い計算（距離減衰ポテンシャルなど）はブラウザ内**（turf.js）で
  オンデマンド実行する
- データが継続的に増えても、パイプラインを再実行するだけで
  成果物を再生成できるようにする（メンテナンス性）

## 構成

```
gisdata/
├── pipeline/               # データ処理パイプライン（Python）
│   ├── raw/                # 元データ取得スクリプト（データ本体はGit管理外）
│   ├── process/            # 解析・COG/PMTiles変換スクリプト
│   └── requirements.txt
├── data/
│   ├── raw/                # ダウンロードした元データの置き場（.gitignore対象）
│   └── processed/          # 生成物（COG, PMTiles, GeoJSON）→ 将来的にR2等へ
├── web/                    # フロントエンド（MapLibre GL + turf.js）
│   └── index.html
├── .github/workflows/
│   └── pipeline.yml        # データ更新時の自動処理・公開の雛形
└── README.md
```

## 技術スタック（想定）

| レイヤー | 技術 |
|---|---|
| ラスタ/ベクタ処理 | Python（rasterio, geopandas, GDAL, pysheds） |
| データ形式 | COG（Cloud Optimized GeoTIFF）、PMTiles、GeoJSON |
| ストレージ | Cloudflare R2（無料枠、エグレス課金なし）※未接続、後日設定 |
| フロントエンド | MapLibre GL JS + turf.js + geotiff.js |
| 公開 | GitHub Pages（`web/` を配信） |
| 自動化 | GitHub Actions |

## セットアップ（ローカルでパイプラインを試す）

```bash
cd pipeline
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python process/ingest_chiba_data.py   # 元データが data/raw/chiba/ にある場合
```

これで `data/processed/rasters/*.tif`（COG）と `data/processed/catalog.json`
（ラスタ一覧）が生成される。ラスタを追加したいときは
`pipeline/process/ingest_chiba_data.py` の `RASTER_DEFS` に定義を1つ足すだけでよい。

## フロントエンドの確認

フロントエンドは `data/catalog.json` と `data/rasters/*.tif` を読みにいくため、
ローカルで動かす場合は生成物を `web/data/` にコピーしてから起動する。

```bash
mkdir -p web/data
cp -r data/processed/* web/data/
cd web
python -m http.server 8000
```

（GitHub Actionsでは、この処理が自動的に行われる）

## ベースマップについて

デフォルトは国土地理院の淡色地図（`gsi_pale`）。`web/index.html` 内の
`BASE_LAYERS` 配列にエントリを1つ追加すると、画面上部のセレクタに
選択肢が増える仕組みになっている。

旧版地形図など、タイルのURLがまだ決まっていないレイヤーは
`tiles: null` にしておけば「URL未設定」として選択肢には表示されるが
選択はできない状態になる。URLが決まったら該当エントリの `tiles` に
XYZタイルのURLテンプレート（例: `"https://.../{z}/{x}/{y}.png"`）を
設定するだけで有効化される。

```js
const BASE_LAYERS = [
  { id: "gsi_pale", name: "地理院地図(淡色)", tiles: ["https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png"], ... },
  { id: "old_topo", name: "旧版地形図（要設定）", tiles: null, ... }, // ← ここにURLを設定
];
```

## バッファ解析について

地図をクリックすると、その地点を中心とした指定半径のバッファ内で、
カタログに登録されている全ラスタの平均・最小・最大値をブラウザ内
（geotiff.js + turf.js）でオンデマンド計算する。サーバー計算は不要。

## 標高データ（国土地理院 標高タイル）について

`pipeline/process/ingest_gsi_elevation.py` は、国土地理院の標高タイル
(DEM10B, 10mメッシュ)を印旛沼流域周辺の範囲だけダウンロードし、
モザイク結合・EPSG:4326への再投影・COG化を行う。

外部ネットワークへの多数アクセスが必要で時間もかかるため、通常の
pushでは実行せず、GitHub Actionsの `Ingest GSI Elevation Data`
ワークフロー（手動実行 = workflow_dispatch）でのみ実行する。
実行結果（COGファイルとカタログ更新）はリポジトリにコミットされ、
以後は固定データとして配信される。対象範囲を変えたい場合は
スクリプト内の `BBOX` を変更して再実行する。

## 千葉県 実データについて

`pipeline/process/ingest_chiba_data.py` は、千葉県の実データ（水田占有率・
HANDランク・開発圧・TWIランク・GI地形スコアのラスタ、千葉県域(近似)・
500mメッシュGI統合スコアのベクタ）を取り込み、EPSG:4326への再投影・
COG化・GeoJSON化を行う。

元データは `data/raw/chiba/{raster,vector}/` に配置する想定（Git管理外）。
新しいファイルを追加する場合は、スクリプト内の `RASTER_DEFS` /
`VECTOR_DEFS` に定義を1つ追加するだけでよい。連続値のデータをuint8で
軽量化したい場合は `uint8_scale` を指定する（例: 10を指定すると
値を10倍してuint8(0-255)に丸めて保存し、frontend側で10で割り戻す）。

01/02/03/04番の高解像度データ、143MBのTWI元データなど、Google Drive
経由のダウンロードサイズ制限（10MB）で自動取得できないデータは、
GitHubへの直接pushで取り込む運用にしている。

### データの注意点（既知の未確認事項）

- **開発圧（chiba_dev_pressure）の符号の向き**：-1/0/+1のどちらが
  「増加」でどちらが「減少」かが未確認（D-381）。確認が取れるまで、
  説明文・凡例では「増加/減少」と断定しない。
- **千葉県域（近似）**：ファイル名に「EcoDRR」を含むが、Eco-DRR
  (生態系を活用した防災減災)の指定範囲などではなく、単なる県域の
  近似ポリゴン。

```bash
python pipeline/process/ingest_chiba_data.py
```

## 今後のTODO

- [ ] 開発圧の符号(+1/-1がそれぞれ何を意味するか)の確認
- [ ] Cloudflare R2 / Pages への接続とデプロイ設定
- [ ] GitHub Actionsでパイプライン自動実行を有効化（現状は元データが
      CI環境に無いため、data/processedの既存コミットをそのまま使用）
