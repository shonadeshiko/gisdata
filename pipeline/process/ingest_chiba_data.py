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
        "description": "最近接水路からの比高(HAND)に基づく浸水リスクの目安ランク。値が小さいほど水路に近く低い。",
        "resampling": Resampling.nearest,
    },
    {
        "id": "chiba_dev_pressure",
        "src": "開発圧_2020-2024_千葉県.tif",
        "name": "開発圧 2020-2024（千葉県）",
        "unit": "区分(-1,0,1)",
        "description": "2020年から2024年にかけての開発圧の変化。-1:減少 0:変化なし 1:増加。",
        "resampling": Resampling.nearest,
    },
]

# id, 元ファイル名, 表示名, 説明
VECTOR_DEFS = [
    {
        "id": "chiba_ecodrr_boundary",
        "src": "千葉県域_EcoDRR有効範囲.gpkg",
        "name": "EcoDRR有効範囲（千葉県）",
        "description": "Eco-DRR(生態系を活用した防災減災)の観点で有効とされる範囲の境界。",
    },
    {
        "id": "chiba_mesh500m_gi",
        "src": "メッシュ500m_GI統合_千葉県.gpkg",
        "name": "500mメッシュ GI統合スコア（千葉県）",
        "description": "500mメッシュ単位のグリーンインフラ(GI)関連スコア・開発圧・土地被覆割合等の統合データ。",
    },
]


def reproject_to_cog(src_path: Path, dst_cog_path: Path, resampling: Resampling) -> None:
    with rasterio.open(src_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, DST_CRS, src.width, src.height, *src.bounds
        )
        kwargs = src.meta.copy()
        kwargs.update(
            {
                "crs": DST_CRS,
                "transform": transform,
                "width": width,
                "height": height,
            }
        )

        tmp_path = dst_cog_path.with_suffix(".reproj.tif")
        dst_cog_path.parent.mkdir(parents=True, exist_ok=True)

        with rasterio.open(tmp_path, "w", **kwargs) as dst:
            for band in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, band),
                    destination=rasterio.band(dst, band),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=DST_CRS,
                    resampling=resampling,
                )

    cog_translate(
        str(tmp_path),
        str(dst_cog_path),
        cog_profiles.get("deflate"),
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
        reproject_to_cog(src_path, dst_path, definition["resampling"])

        catalog.append(
            {
                "id": definition["id"],
                "name": definition["name"],
                "unit": definition["unit"],
                "description": definition["description"],
                "path": f"rasters/{definition['id']}.tif",
            }
        )
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
        if gdf.crs is not None and gdf.crs.to_string() != DST_CRS:
            gdf = gdf.to_crs(DST_CRS)

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(dst_path, driver="GeoJSON")

        catalog.append(
            {
                "id": definition["id"],
                "name": definition["name"],
                "description": definition["description"],
                "path": f"vectors/{definition['id']}.geojson",
                "feature_count": int(len(gdf)),
            }
        )
        print(f"完了: {dst_path} ({len(gdf)}件)")
    return catalog


def merge_catalog(existing_path: Path, new_entries: list[dict], key: str) -> None:
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

    existing_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    raster_entries = process_rasters()
    vector_entries = process_vectors()

    merge_catalog(PROCESSED_DIR / "catalog.json", raster_entries, "rasters")
    merge_catalog(PROCESSED_DIR / "vectors_catalog.json", vector_entries, "vectors")

    print("\nカタログ更新完了")


if __name__ == "__main__":
    main()
