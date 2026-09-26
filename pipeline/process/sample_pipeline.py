"""
サンプルパイプライン: 複数のダミーラスタを生成し、COGに変換してカタログを書き出す。

実データが用意できたら、build_sample_raster() を実データの読み込み・
リサンプリング処理に差し替える。ラスタを追加するときは RASTER_DEFS に
1行足すだけで、COG生成・カタログ更新・フロントエンドへの反映まで揃う設計。
"""

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
RASTERS_DIR = PROCESSED_DIR / "rasters"

# 印旛沼流域周辺のおおよその範囲（今後、実データに合わせて調整する）
ORIGIN_LON = 140.20
ORIGIN_LAT = 35.85
PIXEL_SIZE = 0.0015  # 度単位（約150m相当）
GRID_SIZE = 400  # 400 x 400 セル -> 約60km四方をカバー

# ラスタ定義: id, 説明, 単位, 生成関数
RASTER_DEFS = [
    {
        "id": "elevation",
        "name": "標高（サンプル）",
        "unit": "m",
        "description": "ダミーの標高データ。実データ整備後はDEMに差し替える。",
        "generator": lambda size: _gradient(size, 0, 40),
    },
    {
        "id": "landuse_index",
        "name": "土地利用指数（サンプル）",
        "unit": "index(0-1)",
        "description": "ダミーの土地利用指数。値が高いほど市街地を想定。",
        "generator": lambda size: _blocky_pattern(size),
    },
    {
        "id": "rainfall",
        "name": "降水量（サンプル）",
        "unit": "mm",
        "description": "ダミーの降水量データ。実データ整備後は気象データに差し替える。",
        "generator": lambda size: _radial_pattern(size, 50, 200),
    },
]


def _gradient(size: int, low: float, high: float) -> np.ndarray:
    return np.linspace(low, high, size * size, dtype="float32").reshape(size, size)


def _blocky_pattern(size: int) -> np.ndarray:
    rng = np.random.default_rng(42)
    blocks = rng.random((size // 20, size // 20)).astype("float32")
    return np.kron(blocks, np.ones((20, 20), dtype="float32"))[:size, :size]


def _radial_pattern(size: int, low: float, high: float) -> np.ndarray:
    y, x = np.mgrid[0:size, 0:size]
    cy, cx = size / 2, size / 2
    dist = np.sqrt((y - cy) ** 2 + (x - cx) ** 2)
    normalized = 1 - (dist / dist.max())
    return (low + normalized * (high - low)).astype("float32")


def build_raster(path: Path, data: np.ndarray) -> None:
    transform = from_origin(ORIGIN_LON, ORIGIN_LAT, PIXEL_SIZE, PIXEL_SIZE)
    profile = {
        "driver": "GTiff",
        "height": data.shape[0],
        "width": data.shape[1],
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": transform,
        "nodata": -9999.0,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)


def to_cog(src_path: Path, dst_path: Path) -> None:
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    cog_translate(
        str(src_path),
        str(dst_path),
        cog_profiles.get("deflate"),
        in_memory=False,
        quiet=True,
    )


def merge_catalog(existing_path: Path, new_entries: list, key: str) -> None:
    """既存カタログに追記する（他のパイプラインが登録した項目を消さないため）。"""
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

    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    catalog = []

    for definition in RASTER_DEFS:
        raw_path = RAW_DIR / f"{definition['id']}_raw.tif"
        cog_path = RASTERS_DIR / f"{definition['id']}.tif"

        data = definition["generator"](GRID_SIZE)
        build_raster(raw_path, data)
        to_cog(raw_path, cog_path)

        catalog.append(
            {
                "id": definition["id"],
                "name": definition["name"],
                "unit": definition["unit"],
                "description": definition["description"],
                "path": f"rasters/{definition['id']}.tif",
            }
        )
        print(f"生成完了: {cog_path}")

    catalog_path = PROCESSED_DIR / "catalog.json"
    merge_catalog(catalog_path, catalog, "rasters")
    print(f"カタログ更新完了: {catalog_path}")


if __name__ == "__main__":
    main()
