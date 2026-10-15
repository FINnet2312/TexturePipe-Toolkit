"""uint8/uint16/float 图像与 ChannelMap 的无损写出。"""
from __future__ import annotations

from pathlib import Path
from typing import Union

import numpy as np
from PIL import Image

from ..core.map import ChannelMap
from ..core.packer import pack_rgba
from ..core.pixels import normalized_float, validate_pixel_array


IMAGE_SAVE_FILTER = (
    "PNG (*.png);;TIFF (*.tif *.tiff);;OpenEXR (*.exr);;"
    "8-bit Images (*.jpg *.jpeg *.tga *.bmp *.webp)"
)


def _save_png(arr: np.ndarray, path: Path) -> None:
    if arr.dtype == np.uint8:
        if arr.ndim == 2:
            Image.fromarray(arr, mode="L").save(path)
        else:
            mode = "RGB" if arr.shape[-1] == 3 else "RGBA"
            Image.fromarray(arr, mode=mode).save(path)
        return
    if arr.dtype != np.uint16:
        raise ValueError("PNG输出只支持 uint8/uint16；浮点数据请保存为EXR或TIFF")
    try:
        import png
    except ImportError as exc:
        raise RuntimeError("写16-bit PNG需要安装 pypng") from exc
    height, width = arr.shape[:2]
    channels = 1 if arr.ndim == 2 else arr.shape[-1]
    writer = png.Writer(
        width=width,
        height=height,
        greyscale=channels == 1,
        alpha=channels in (2, 4),
        bitdepth=16,
    )
    rows = (
        np.asarray(row, dtype=np.uint16).reshape(-1).tolist()
        for row in arr
    )
    with path.open("wb") as stream:
        writer.write(stream, rows)


def _save_tiff(arr: np.ndarray, path: Path) -> None:
    try:
        import tifffile
    except ImportError as exc:
        raise RuntimeError("写TIFF需要安装 tifffile") from exc
    kwargs = {"photometric": "rgb"} if arr.ndim == 3 and arr.shape[-1] in (3, 4) else {}
    tifffile.imwrite(str(path), arr, **kwargs)


def _save_exr(arr: np.ndarray, path: Path) -> None:
    try:
        import OpenEXR
    except ImportError as exc:
        raise RuntimeError("写EXR需要安装官方 OpenEXR Python模块") from exc
    if arr.dtype.kind == "u":
        pixels = normalized_float(arr).astype(np.float32)
    else:
        pixels = arr.astype(np.float32, copy=False)
    if pixels.ndim == 2:
        channels = {"Y": np.ascontiguousarray(pixels)}
    elif pixels.shape[-1] == 3:
        channels = {"RGB": np.ascontiguousarray(pixels)}
    else:
        channels = {"RGBA": np.ascontiguousarray(pixels)}
    header = {
        "compression": OpenEXR.ZIP_COMPRESSION,
        "type": OpenEXR.scanlineimage,
    }
    with OpenEXR.File(header, channels) as exr:
        exr.write(str(path))


def _validate_image_shape(arr: np.ndarray) -> None:
    if arr.ndim == 2:
        return
    if arr.ndim == 3 and arr.shape[-1] in (3, 4):
        return
    raise ValueError(f"图像必须为 H×W、H×W×3 或 H×W×4，收到 {arr.shape}")


def save_image(arr: np.ndarray, path: Union[str, Path]) -> Path:
    """按扩展名保存，并拒绝任何静默降位深。"""
    arr = np.ascontiguousarray(arr)
    _validate_image_shape(arr)
    validate_pixel_array(arr)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    suffix = p.suffix.lower()
    if suffix == ".png":
        _save_png(arr, p)
    elif suffix in {".tif", ".tiff"}:
        _save_tiff(arr, p)
    elif suffix == ".exr":
        _save_exr(arr, p)
    elif suffix in {".jpg", ".jpeg", ".tga", ".bmp", ".webp"}:
        if arr.dtype != np.uint8:
            raise ValueError(f"{suffix} 不支持当前 {arr.dtype} 位深，请改存PNG/TIFF/EXR")
        if arr.ndim != 3:
            Image.fromarray(arr, mode="L").save(p)
        else:
            mode = "RGB" if arr.shape[-1] == 3 else "RGBA"
            Image.fromarray(arr, mode=mode).save(p)
    else:
        raise ValueError(f"不支持的输出格式: {suffix or '(无扩展名)'}")
    return p


def save_grayscale(arr: np.ndarray, path: Union[str, Path]) -> Path:
    if arr.ndim != 2:
        raise ValueError(f"save_grayscale expects 2D, got {arr.shape}")
    return save_image(arr, path)


def save_rgba(arr: np.ndarray, path: Union[str, Path]) -> Path:
    if arr.ndim != 3 or arr.shape[-1] not in (3, 4):
        raise ValueError(f"save_rgba expects H×W×3 or H×W×4, got {arr.shape}")
    return save_image(arr, path)


def save_map_rgba(
    m: ChannelMap,
    path: Union[str, Path],
    remove_alpha: bool = False,
) -> Path:
    rgba = pack_rgba(m)
    return save_rgba(rgba[..., :3] if remove_alpha else rgba, path)
