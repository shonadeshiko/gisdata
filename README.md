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
python process/sample_pipeline.py
```

これで `data/processed/rasters/*.tif`（COG）と `data/processed/catalog.json`
（ラスタ一覧）が生成される。ラスタを追加したいときは
`pipeline/process/sample_pipeline.py` の `RASTER_DEFS` に定義を1つ足すだけでよい。

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

## バッファ解析について

地図をクリックすると、その地点を中心とした指定半径のバッファ内で、
カタログに登録されている全ラスタの平均・最小・最大値をブラウザ内
（geotiff.js + turf.js）でオンデマンド計算する。サーバー計算は不要。

## 千葉県 実データについて

`pipeline/process/ingest_chiba_data.py` は、千葉県の実データ（水田占有率・
HANDランク・開発圧のラスタ、EcoDRR有効範囲・500mメッシュGI統合スコアの
ベクタ）を取り込み、EPSG:4326への再投影・COG化・GeoJSON化を行う。

元データは `data/raw/chiba/{raster,vector}/` に配置する想定（Git管理外）。
新しいファイルを追加する場合は、スクリプト内の `RASTER_DEFS` /
`VECTOR_DEFS` に定義を1つ追加するだけでよい。

現時点で未取込みのデータ（TWIランク、GI地形スコア、01/02/03/04番の
高解像度データ、143MBのTWI元データなど）は、Google Drive経由のダウンロード
サイズ制限（10MB）や一時的な不調により取り込めていない。今後は
GitHubへの直接pushやGit LFSでの取り込みを検討する。

```bash
python pipeline/process/ingest_chiba_data.py
```

## 今後のTODO

- [ ] 印旛沼流域の境界データ（GeoJSON）を `data/processed/` に配置
- [ ] DEM・土地利用データの取得スクリプトを `pipeline/raw/` に追加
- [ ] ポテンシャル計算ロジック（距離減衰モデル）の実装
- [ ] Cloudflare R2 / Pages への接続とデプロイ設定
- [ ] GitHub Actionsでパイプライン自動実行を有効化
