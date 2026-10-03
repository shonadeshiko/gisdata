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

## ラスタの表示について

「② ラスタの表示」でドロップダウンから選んだラスタを、地図上に
色分け画像として重ねて表示できる。geotiff.jsで全ピクセルを読み込み、
nodataを除いた実際のmin/maxに合わせてカラーランプ(青→緑→黄→赤の
4段階)で着色したcanvasを、MapLibreの`image`ソースとして地図に貼り付ける
方式（タイル化はしていない）。透過度スライダーで調整可能。

`catalog.json`のエントリに`"categorical": true`を付けたラスタ（JAXA土地
被覆など）は、連続値のグラデーションではなく区分ごとの色分け＋凡例
（`CATEGORICAL_RASTER_PALETTE`）で表示される。正式な区分名が未確認の
ため、現状は「クラスN」という汎用ラベル表示になっている。正式な凡例が
分かったら`web/index.html`の`CATEGORICAL_RASTER_LABELS`に
`{ ラスタid: { 区分値: "ラベル" } }`の形で追記すると、ラベルが反映される。

## 範囲分析について

地図をクリックするか、ポリゴンを描いて確定すると、その範囲内で
カタログの全ラスタの統計をブラウザ内（geotiff.js + turf.js）で
オンデマンド計算する。連続値のラスタは平均・最小・最大・集計セル数、
`categorical: true`のラスタは区分ごとの集計セル数（割合%つき）を表示する。
計算に使った範囲は地図上に薄い青で表示され、「分析範囲を消す」ボタンで
消せる。

## ベクタレイヤーの表示について

メッシュ・雨水浸透機能の2レイヤーは専用の色分け・凡例・クリックポップ
アップを持つ。それ以外のベクタ（ESV系データなど）は`vectors_catalog.json`
に登録するだけで、パネル内「① 表示するレイヤー」の下に表示切替
チェックボックス・透過度スライダー・クリックで全属性を表示するポップ
アップが自動的に追加される（`SPECIAL_VECTOR_IDS`に含まれないIDは
すべて汎用レイヤーとして扱われる）。新しいベクタを追加するときに
`web/index.html`側の編集が基本的に不要になる仕組み。

`VECTOR_DEFS`に`"color_field": "属性名"`を指定すると、単色塗りではなく
その属性の実際の値のmin/maxに応じた濃淡のグラデーション塗り分け＋凡例
（メッシュと同様のbar+min/maxラベル）になる（`chiba_esv_population_mesh`の
`pop`、`chiba_esv_rl_score`の`score_species_weighted`等で使用）。
frontendがGeoJSONを一度fetchしてmin/maxを計算するため、属性名の指定だけで
動く（domain設定が不要）。未指定のベクタは従来通り単色塗りのまま。

## 千葉県 実データについて

`pipeline/process/ingest_chiba_data.py` は、千葉県の実データ（GI関連
サンプル、Google Driveから取得）を取り込み、EPSG:4326への再投影・
COG化・GeoJSON化を行う。

元データは `data/raw/chiba/{raster,vector}/` に配置する想定（Git管理外）。
新しいファイルを追加する場合は、スクリプト内の `RASTER_DEFS` /
`VECTOR_DEFS` に定義を1つ追加するだけでよい。連続値のデータをuint8で
軽量化したい場合は `uint8_scale` を指定する（例: 10を指定すると
値を10倍してuint8(0-255)に丸めて保存し、frontend側で10で割り戻す）。
カテゴリカルなラスタ（土地被覆区分など）は `"categorical": True` を
指定する（上記「ラスタの表示について」参照）。

2回目以降にデータを追加する場合、過去に取り込んだ元データをすべて
手元に揃え直す必要はない。`process_rasters()`/`process_vectors()`は
`data/raw/chiba/`に実在するファイルだけを処理し、存在しないものは
自動的にスキップする。`merge_catalog()`が既存のカタログJSONをid単位で
マージするため、新しく追加したいデータ1件分だけを配置して実行すれば、
既存のデータはそのまま温存される。

### Google Driveからの自動取得について

このリポジトリを操作するAI（Claude等）がGoogle Drive連携で元データを
取得する場合、ファイルサイズに実務上の上限がある（API上の上限は10MBだが、
実際には概ね5MB前後を超えると転送エラーになることがある）。
**それを超えるファイルは自動取得できないため、人が直接 `git push` で
取り込む必要がある。**

また、GitHubのWeb UI（ブラウザでのドラッグ&ドロップアップロード）経由で
人が取り込む場合も、**1ファイルあたり25MBの上限**がある点に注意
（WSL環境から`git push`する場合はこの制限を受けない。手順書「Windows環境
での作業（WSL）について」参照）。

2026-10-03時点で、`chiba_landscape_diversity`・
`chiba_infiltration_potential`・`chiba_esv_beneficiary_watershed_b`・
`chiba_esv_sdr_diff_watershed`・メッシュv2（`chiba_mesh500m_gi`の新版）は
Web UI経由（25MB未満）で取り込み済み（`ESV_土地被覆変化_2020-2024_千葉県.tif`
も取得はしたが、不要と判断しRASTER_DEFSから外している）。以下はサイズの
都合で**まだ未取得**
（`RASTER_DEFS`には定義済みなので、ファイルを置いて
`python pipeline/process/ingest_chiba_data.py`を再実行すれば有効になる）：

**ラスタ（`data/raw/chiba/raster/`に配置、25MB超のためWSL経由のpushが必要）**
- `JAXA_HRLC土地被覆_2020_千葉県.tif` / `_2024_千葉県.tif`（約11.6〜11.7MB、categorical）※25MB未満だが未取り込み
- `ESV19_冷却能力CC_千葉県.tif`（約47.6MB、COG化後も重いので読み込みがやや遅い）
- `ESV06_土砂輸出量_SDR_千葉県.tif`（約53.2MB、同上）

**意図的に取り込みを見送っているファイル**
- `ESV12_生息地質指数_4脅威_千葉県.tif`（約570MB）：本サイトは
  「ブラウザがラスタを丸ごとfetchする」設計のため、このサイズは
  配信が現実的でない。ダウンサンプリング等で大幅に軽量化してから
  改めて追加を検討すること。

### データの注意点

- **開発圧（chiba_dev_pressure_2020_2024 / chiba_dev_pressure_2011_2022）の
  符号**：+1=都市化(開発圧増加)、0=変化なし、-1=開発後退(緑地化等)
  （2026-09-28確認、D-381解消）。
- **千葉県域（近似）**：ファイル名に「EcoDRR」を含むが、Eco-DRR
  (生態系を活用した防災減災)の指定範囲などではなく、単なる県域の
  近似ポリゴン。
- **メッシュv2（chiba_mesh500m_gi）**：浸透機能を組み込んで優先度を
  再計算したv2版に切り替え済み。`gi_conservation_score`/`gi_pressure_score`/
  `priority_rank`/`urban_frac`/`forest_frac`/`mesh4_code`は旧版と同じ
  属性名のまま残っているため`MESH_SCORES`はそのまま使える。新たに
  `infiltration_good_pct`（浸透適地率）・`dual_axis_group`（開発圧×浸透の
  分類）などが追加され、クリックポップアップに反映済み。

```bash
python pipeline/process/ingest_chiba_data.py
```

## 今後のTODO

- [ ] 上記「Google Driveからの自動取得について」に挙げた、サイズ制限で
      未取得のファイル(JAXA土地被覆2020/2024・冷却能力CC・SDR)を
      data/raw/chiba/に配置し、パイプラインを再実行する(WSL経由のpush推奨)
- [ ] JAXA土地被覆の正式な区分定義を確認し、`CATEGORICAL_RASTER_LABELS`に反映する
- [ ] 土砂流出抑制の受益人口・土砂流出量の変化の`color_field`が適切か
      （`pop_down`/`sed_export_pct_raw`）データの意味を確認する
- [ ] Cloudflare R2 / Pages への接続とデプロイ設定
- [ ] GitHub Actionsでパイプライン自動実行を有効化（現状は元データが
      CI環境に無いため、data/processedの既存コミットをそのまま使用）
