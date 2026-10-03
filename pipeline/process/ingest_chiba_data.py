"""
千葉県の実データ（Google Driveから取得したサンプル）を取り込むパイプライン。

- ラスタ: EPSG:4326に再投影し、COG(Cloud Optimized GeoTIFF)に変換
- ベクタ: EPSG:4326に変換し、GeoJSONとして書き出し（フロントで直接fetchできる）
- 生成物は data/processed/catalog.json (ラスタ) と
  data/processed/vectors_catalog.json (ベクタ) に登録される

RASTER_DEFS / VECTOR_DEFS にファイルを追加するだけで、
新しい千葉県データを取り込めるようにしてある。
"""

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.warp import Resampling, calculate_default_transform, reproject
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "chiba"
PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
RASTERS_DIR = PROCESSED_DIR / "rasters"
VECTORS_DIR = PROCESSED_DIR / "vectors"

DST_CRS = "EPSG:4326"

# id, 元ファイル名, 表示名, 単位, 説明, リサンプリング方法
RASTER_DEFS = [
    {
        "id": "chiba_paddy_ratio",
        "src": "05_水田の占有率_12_千葉県.tif",
        "name": "水田の占有率（千葉県）",
        "unit": "比率(0-1)",
        "description": "グリッド内における水田の占有割合。値が高いほど水田が多い。",
        "resampling": Resampling.bilinear,
    },
    {
        "id": "chiba_hand_rank",
        "src": "HANDランク_千葉県.tif",
        "name": "HANDランク（千葉県）",
        "unit": "ランク(1-5)",
        "description": "最近接水路との比高(HAND)による区分。値が大きいほど水路との比高が小さい(水路に近い)。",
        "resampling": Resampling.nearest,
    },
    {
        "id": "chiba_dev_pressure_2020_2024",
        "src": "開発圧v2_2020-2024_千葉県.tif",
        "name": "開発圧 2020-2024 v2（千葉県）",
        "unit": "区分(-1,0,+1)",
        "description": "2020年から2024年にかけての開発圧の変化区分(v2データ)。+1:都市化(開発圧増加) 0:変化なし -1:開発後退(緑地化等)。",
        "resampling": Resampling.nearest,
    },
    {
        "id": "chiba_dev_pressure_2011_2022",
        "src": "開発圧v2_2011-2022_千葉県.tif",
        "name": "開発圧 2011-2022 v2（千葉県）",
        "unit": "区分(-1,0,+1)",
        "description": "2011年から2022年にかけての開発圧の変化区分(v2データ)。+1:都市化(開発圧増加) 0:変化なし -1:開発後退(緑地化等)。",
        "resampling": Resampling.nearest,
    },
    {
        "id": "chiba_twi_rank",
        "src": "TWIランク_千葉県.tif",
        "name": "TWIランク（千葉県）",
        "unit": "ランク(1-5)",
        "description": "地形的湿潤度指数(TWI)に基づく浸水・湛水しやすさの目安ランク。値が大きいほど水が集まりやすい地形。",
        "resampling": Resampling.nearest,
    },
    {
        "id": "chiba_gi_terrain_score",
        "src": "GI地形スコア_千葉県.tif",
        "name": "GI地形スコア（千葉県）",
        "unit": "スコア(1.0-5.0)",
        "description": "地形条件から見たグリーンインフラ(GI)適性の統合スコア(連続値)。",
        "resampling": Resampling.bilinear,
        "uint8_scale": 10,  # 10倍してuint8化(小数点以下1桁の精度を保持)。frontendで10で割り戻す
    },
    # --- ここから、GI関連サンプル(千葉県)で追加されたESV(生態系サービス価値)系データ ---
    {
        "id": "chiba_esv_natural_veg_ratio",
        "src": "ESV11_農地周囲の自然植生割合_250m_千葉県.tif",
        "name": "農地周囲の自然植生割合（千葉県）",
        "unit": "比率(0-1)",
        "description": "250mグリッドにおける、農地周囲の自然植生の割合。値が高いほど農地周辺の自然植生が多い。",
        "resampling": Resampling.bilinear,
    },
    {
        "id": "chiba_esv_disaster_exposure_pop",
        "src": "ESV_防災_曝露人口_いずれかのハザード_250m_千葉県.tif",
        "name": "防災：曝露人口（いずれかのハザード）（千葉県）",
        "unit": "人",
        "description": "250mグリッドにおける、いずれかの災害ハザード(洪水・土砂等)の想定区域に居住する人口。",
        "resampling": Resampling.bilinear,
    },
    {
        "id": "chiba_esv_cooling_benefit_pop",
        "src": "ESV19_受益量_人x冷却量_250m_千葉県.tif",
        "name": "冷却効果の受益量（人×冷却量）（千葉県）",
        "unit": "人×冷却指数",
        "description": "250mグリッドにおける、緑地等による冷却効果と、その効果を受ける人口を掛け合わせた受益量の指標。",
        "resampling": Resampling.bilinear,
    },
    {
        "id": "chiba_esv_cooling_amount",
        "src": "ESV19_冷却量_250m_千葉県.tif",
        "name": "冷却量（千葉県）",
        "unit": "指数",
        "description": "250mグリッドにおける、緑地等による気温の冷却量の指標。値が高いほど冷却効果が大きい。",
        "resampling": Resampling.bilinear,
    },
    {
        "id": "chiba_esv_population",
        "src": "ESV_人口_250m_千葉県.tif",
        "name": "人口（250mグリッド）（千葉県）",
        "unit": "人",
        "description": "250mグリッドにおける人口分布。",
        "resampling": Resampling.bilinear,
    },
    {
        "id": "chiba_esv_soil_erodibility_k",
        "src": "ESV06_土壌侵食性K_千葉県.tif",
        "name": "土壌侵食性K（千葉県）",
        "unit": "係数",
        "description": "土壌そのものの侵食されやすさを示すUSLE/RUSLEのK因子。値が高いほど侵食されやすい土壌。",
        "resampling": Resampling.bilinear,
    },
    # --- 以下は元ファイルが10MBを超えるため、Google Driveからの自動取得が
    # できず、data/raw/chiba/raster/ に手動で配置してから有効になる
    # （詳細はREADME「千葉県 実データについて」参照）。---
    {
        "id": "chiba_landscape_diversity",
        "src": "04_自然的景観の多様度_12_千葉県.tif",
        "name": "自然的景観の多様度（千葉県）",
        "unit": "指数(0-1)",
        "description": "自然的景観の多様度を示す指数。値が高いほど景観の多様性が高い。",
        "resampling": Resampling.bilinear,
    },
    {
        "id": "chiba_landcover_2020",
        "src": "JAXA_HRLC土地被覆_2020_千葉県.tif",
        "name": "土地被覆区分 2020（JAXA HRLC・千葉県）",
        "unit": "区分",
        "description": "JAXA高解像度土地利用土地被覆図による土地被覆区分(カテゴリカル)。",
        "resampling": Resampling.nearest,
        "categorical": True,
    },
    {
        "id": "chiba_landcover_2024",
        "src": "JAXA_HRLC土地被覆_2024_千葉県.tif",
        "name": "土地被覆区分 2024（JAXA HRLC・千葉県）",
        "unit": "区分",
        "description": "JAXA高解像度土地利用土地被覆図による土地被覆区分(カテゴリカル)。",
        "resampling": Resampling.nearest,
        "categorical": True,
    },
    {
        "id": "chiba_esv_landcover_change",
        "src": "ESV_土地被覆変化_2020-2024_千葉県.tif",
        "name": "土地被覆変化 2020-2024（千葉県）",
        "unit": "変化区分",
        "description": "2020年から2024年にかけての土地被覆の変化を示す区分値(0-4の少数区分、"
        "大部分は0)。区分の詳細な定義は別途確認が必要。",
        "resampling": Resampling.nearest,
        "categorical": True,
        # 元ファイルにnodataタグが無く、値0が全体の大半(変化なし/背景)を
        # 占めるため、0をnodata相当として透明化する。
        "nodata_override": 0,
    },
    {
        "id": "chiba_esv_cooling_capacity",
        "src": "ESV19_冷却能力CC_千葉県.tif",
        "name": "冷却能力CC（千葉県）",
        "unit": "指数",
        "description": "緑地等による冷却能力(Cooling Capacity)の指標。ファイルサイズが大きい(約48MB)ため読み込みがやや重い。",
        "resampling": Resampling.bilinear,
    },
    {
        "id": "chiba_esv_sediment_export_sdr",
        "src": "ESV06_土砂輸出量_SDR_千葉県.tif",
        "name": "土砂輸出量SDR（千葉県）",
        "unit": "t/ha/year相当",
        "description": "土砂輸送比(SDR)モデルによる土砂輸出量の推定値。ファイルサイズが大きい(約53MB)ため読み込みがやや重い。",
        "resampling": Resampling.bilinear,
    },
    # 「ESV12_生息地質指数_4脅威_千葉県.tif」(約570MB)は、本サイトの
    # 「ブラウザが全ファイルを丸ごとfetchする」設計では配信が現実的でない
    # サイズのため、意図的にRASTER_DEFSに含めていない。ダウンサンプリング
    # 等で軽量化してから別途追加を検討すること。
]

# id, 元ファイル名, 表示名, 説明
VECTOR_DEFS = [
    {
        "id": "chiba_boundary_approx",
        "src": "千葉県域_EcoDRR有効範囲.gpkg",
        "name": "千葉県域（近似）",
        "description": "千葉県の県域を近似したポリゴン。特定の政策・事業(Eco-DRR等)の指定範囲を示すものではない。",
    },
    {
        "id": "chiba_mesh500m_gi",
        "src": "メッシュ500m_GI統合v2浸透込み優先度_千葉県.gpkg",
        "name": "500mメッシュ GI統合スコア（千葉県）",
        "description": "500mメッシュ単位のグリーンインフラ(GI)関連スコア・開発圧・土地被覆割合等の統合データ。"
        "雨水浸透機能を組み込んで優先度を再計算したv2版(主要な属性名は旧版と同じ)。",
    },
    # 人口(500mメッシュ)のベクタは、250mラスタ(chiba_esv_population)と
    # 内容が重複するため取り込み対象から外している
    # (元ファイルはdata/raw/chiba/vector/に残したままでよい)。
    {
        "id": "chiba_esv_rl_score",
        "src": "ESV15_RLスコア_1km_千葉県.gpkg",
        "name": "レッドリスト(RL)スコア 1kmメッシュ（千葉県）",
        "description": "1kmメッシュ単位の、レッドリスト掲載種の記録数・種数等に基づく指標(score_species_weighted等)。",
        "color_field": "score_species_weighted",
    },
    # --- 以下は元ファイルが10MBを超えるため、Google Driveからの自動取得が
    # できず、data/raw/chiba/vector/ に手動で配置してから有効になる
    # （詳細はREADME「千葉県 実データについて」参照）。---
    {
        "id": "chiba_infiltration_potential",
        "src": "03_地形・地質等から期待される雨水浸透機能_12_千葉県.shp",
        "name": "雨水浸透機能（千葉県）",
        "description": "地形・地質等から期待される雨水浸透機能の適地区分('result'列: "
        "01最適地/02適地/03不適地/05判定不能/06判定対象外/07除外区域)。",
        # 元のshpの属性(dbf)がlatin1として読めるUTF-8のバイト列になっている
        # (実際はUTF-8encodeなのにfiona/pyogrioがlatin1として復号している)ため、
        # 文字列列をlatin1で再エンコードしutf-8で読み直して文字化けを直す。
        "fix_mojibake": True,
        # 地形分類由来のポリゴンで頂点数が非常に多いため、0.0003度(約30m)まで
        # 単純化して軽量化する。
        "simplify_tolerance": 0.0003,
    },
    {
        "id": "chiba_esv_beneficiary_watershed_b",
        "src": "ESV_受益者_型B流域_千葉県.gpkg",
        "name": "ESV受益者（型B流域）（千葉県）",
        "description": "生態系サービスの受益者(型B流域)の範囲ポリゴン。下流で恩恵を受ける人口(pop_down)等を含む。",
        "color_field": "pop_down",
    },
    {
        "id": "chiba_esv_sdr_diff_watershed",
        "src": "ESV06_SDR差分_2020-2024_流域別_千葉県.gpkg",
        "name": "SDR差分 2020-2024（流域別）（千葉県）",
        "description": "2020年から2024年にかけての土砂輸出量(SDR)の変化を流域単位で集計したデータ。",
        "color_field": "sed_export_pct_raw",
    },
]


def reproject_to_cog(
    src_path: Path,
    dst_cog_path: Path,
    resampling: Resampling,
    uint8_scale: float | None = None,
    nodata_override: float | None = None,
) -> None:
    """
    uint8_scale を指定すると、値をscale倍してuint8(0-255)に丸めて保存する
    (例: 1.0-5.0の連続値をscale=10で保存すると10-50のuint8になり、
    frontend側でscaleで割り戻すことで小数点以下1桁の精度を保ったまま軽量化できる)。
    整数ランクなど元々小さい整数値のデータは uint8_scale=1 を指定する。

    nodata_override を指定すると、元ファイルにnodataタグが無い(または
    誤っている)場合でも、その値をnodataとして扱う(frontendで透明化される)。
    """
    with rasterio.open(src_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, DST_CRS, src.width, src.height, *src.bounds
        )
        src_nodata = nodata_override if nodata_override is not None else src.nodata

        kwargs = src.meta.copy()
        kwargs.update(
            {
                "crs": DST_CRS,
                "transform": transform,
                "width": width,
                "height": height,
                "nodata": src_nodata,
            }
        )
        if uint8_scale is not None:
            kwargs["dtype"] = "float32"

        tmp_path = dst_cog_path.with_suffix(".reproj.tif")
        dst_cog_path.parent.mkdir(parents=True, exist_ok=True)

        with rasterio.open(tmp_path, "w", **kwargs) as dst:
            for band in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, band),
                    destination=rasterio.band(dst, band),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    src_nodata=src_nodata,
                    dst_transform=transform,
                    dst_crs=DST_CRS,
                    dst_nodata=src_nodata,
                    resampling=resampling,
                )

    if uint8_scale is not None:
        with rasterio.open(tmp_path) as src:
            data = src.read(1)
            nodata_mask = np.isnan(data) if src.nodata is None else (data == src.nodata)
            scaled = np.clip(np.round(data * uint8_scale), 0, 255).astype("uint8")
            scaled[nodata_mask] = 0

            uint8_profile = src.profile.copy()
            uint8_profile.update({"dtype": "uint8", "nodata": 0})
            uint8_path = dst_cog_path.with_suffix(".uint8.tif")
            with rasterio.open(uint8_path, "w", **uint8_profile) as dst:
                dst.write(scaled, 1)
        tmp_path.unlink()
        tmp_path = uint8_path

    # ブラウザ側はCOGを全体取得してから自前でウィンドウ読み込みする方式のため、
    # ズームレベル別のオーバービュー(ピラミッド)は使わない。生成すると
    # ファイルサイズが3割前後増えるだけなので、overview_level=0で無効化する。
    cog_translate(
        str(tmp_path),
        str(dst_cog_path),
        cog_profiles.get("deflate"),
        overview_level=0,
        in_memory=False,
        quiet=True,
    )
    tmp_path.unlink()


def process_rasters() -> list[dict]:
    catalog = []
    for definition in RASTER_DEFS:
        src_path = RAW_DIR / "raster" / definition["src"]
        if not src_path.exists():
            print(f"スキップ（未取得）: {src_path}")
            continue

        dst_path = RASTERS_DIR / f"{definition['id']}.tif"
        print(f"処理中: {definition['src']} -> {dst_path.name}")
        uint8_scale = definition.get("uint8_scale")
        reproject_to_cog(
            src_path,
            dst_path,
            definition["resampling"],
            uint8_scale,
            definition.get("nodata_override"),
        )

        entry = {
            "id": definition["id"],
            "name": definition["name"],
            "unit": definition["unit"],
            "description": definition["description"],
            "path": f"rasters/{definition['id']}.tif",
        }
        if uint8_scale is not None:
            entry["scale"] = uint8_scale
        if definition.get("categorical"):
            entry["categorical"] = True
        catalog.append(entry)
        print(f"完了: {dst_path}")
    return catalog


def process_vectors() -> list[dict]:
    catalog = []
    for definition in VECTOR_DEFS:
        src_path = RAW_DIR / "vector" / definition["src"]
        if not src_path.exists():
            print(f"スキップ（未取得）: {src_path}")
            continue

        dst_path = VECTORS_DIR / f"{definition['id']}.geojson"
        print(f"処理中: {definition['src']} -> {dst_path.name}")

        gdf = gpd.read_file(src_path)
        if definition.get("fix_mojibake"):
            for col in gdf.select_dtypes(include=["object", "str"]).columns:
                if col == gdf.geometry.name:
                    continue
                gdf[col] = gdf[col].apply(
                    lambda v: v.encode("latin1").decode("utf-8") if isinstance(v, str) else v
                )

        if gdf.crs is not None and gdf.crs.to_string() != DST_CRS:
            gdf = gdf.to_crs(DST_CRS)

        simplify_tolerance = definition.get("simplify_tolerance")
        if simplify_tolerance:
            gdf.geometry = gdf.geometry.simplify(simplify_tolerance, preserve_topology=True)

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(dst_path, driver="GeoJSON")

        entry = {
            "id": definition["id"],
            "name": definition["name"],
            "description": definition["description"],
            "path": f"vectors/{definition['id']}.geojson",
            "feature_count": int(len(gdf)),
        }
        if definition.get("color_field"):
            entry["color_field"] = definition["color_field"]
        catalog.append(entry)
        print(f"完了: {dst_path} ({len(gdf)}件)")
    return catalog


def merge_catalog(existing_path: Path, new_entries: list[dict], key: str, valid_ids: set[str]) -> None:
    """
    既存カタログをnew_entriesでid単位にマージする(追加/更新)。
    さらに、valid_ids(現在のRASTER_DEFS/VECTOR_DEFSのid集合)に無い
    "chiba_"始まりのエントリはカタログから取り除き、対応する生成物
    ファイルも削除する(RASTER_DEFS/VECTOR_DEFSからデータを削除した場合に、
    古いカタログエントリ・ファイルが残り続けないようにするため)。
    "chiba_"で始まらないエントリ(例: ingest_gsi_elevation.pyが生成する
    gsi_elevation)は、このスクリプトの管理対象外なので触らない。
    """
    if existing_path.exists():
        existing = json.loads(existing_path.read_text(encoding="utf-8"))
    else:
        existing = {key: []}

    existing_ids = {item["id"] for item in existing.get(key, [])}
    for entry in new_entries:
        if entry["id"] not in existing_ids:
            existing.setdefault(key, []).append(entry)
        else:
            existing[key] = [entry if item["id"] == entry["id"] else item for item in existing[key]]

    kept, removed = [], []
    for item in existing.get(key, []):
        is_ours = item["id"].startswith("chiba_")
        (removed if (is_ours and item["id"] not in valid_ids) else kept).append(item)
    existing[key] = kept

    for item in removed:
        print(f"カタログから削除(定義が無いため): {item['id']}")
        stale_file = PROCESSED_DIR / item["path"]
        if stale_file.exists():
            stale_file.unlink()

    existing_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    raster_entries = process_rasters()
    vector_entries = process_vectors()

    raster_ids = {d["id"] for d in RASTER_DEFS}
    vector_ids = {d["id"] for d in VECTOR_DEFS}

    merge_catalog(PROCESSED_DIR / "catalog.json", raster_entries, "rasters", raster_ids)
    merge_catalog(PROCESSED_DIR / "vectors_catalog.json", vector_entries, "vectors", vector_ids)

    print("\nカタログ更新完了")


if __name__ == "__main__":
    main()
