"""
サンプルパイプライン: ラスタ処理からCOG生成までの最小構成例。

実際のDEM/土地利用データが用意できたら、load部分を差し替えて使う。
これは「パイプラインの型」を示すためのダミー実行可能スクリプト。
"""

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"


def build_sample_raster(path: Path, size: int = 256) -> None:
    """ダミーのラスタ(例: 標高っぽい勾配データ)を生成する。"""
    data = np.linspace(0, 100, size * size, dtype="float32").reshape(size, size)
    transform = from_origin(140.20, 35.78, 0.0005, 0.0005)  # 印旛沼周辺のおおよその原点

    profile = {
        "driver": "GTiff",
        "height": size,
        "width": size,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": transform,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)


def to_cog(src_path: Path, dst_path: Path) -> None:
    """通常のGeoTIFFをCloud Optimized GeoTIFF (COG) に変換する。"""
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    cog_translate(
        str(src_path),
        str(dst_path),
        cog_profiles.get("deflate"),
        in_memory=False,
        quiet=True,
    )


def main() -> None:
    raw_tif = RAW_DIR / "sample_raw.tif"
    cog_tif = PROCESSED_DIR / "sample_cog.tif"

    build_sample_raster(raw_tif)
    to_cog(raw_tif, cog_tif)

    print(f"生成完了: {cog_tif}")


if __name__ == "__main__":
    main()
