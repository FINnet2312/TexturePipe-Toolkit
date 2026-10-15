"""图像文件加载与 ChannelSlot 数据填充。

位深策略:
- 常规8-bit格式由 Pillow 读取
- 16-bit PNG 由 PyPNG 读取，避免 Pillow 将多通道PNG降为8-bit
- 16-bit/float TIFF 由 tifffile 读取
- EXR 由官方 OpenEXR Python 3.3+ API读取
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import numpy as np
from PIL import Image

from ..core.file_cache import FileCache
from ..core.output_spec import OutputSpec
from ..core.pixels import full_scale, invert_values, validate_pixel_array, white_array
from ..core.resize import resize_to
from ..core.slot import ChannelSlot, SourceType


SUPPORTED_8BIT_MODES = ("RGB", "RGBA", "L", "LA", "P")
SUPPORTED_IMAGE_EXTS = {
    ".png", ".tif", ".tiff", ".exr",
    ".jpg", ".jpeg", ".tga", ".bmp", ".webp",
}
IMAGE_OPEN_FILTER = (
    "Images (*.png *.tif *.tiff *.exr *.jpg *.jpeg *.tga *.bmp *.webp);;"
    "High precision (*.png *.tif *.tiff *.exr);;All files (*.*)"
)


def _normalize_loaded_array(arr: np.ndarray, source_name: str) -> np.ndarray:
    arr = np.asarray(arr)
    if arr.dtype.byteorder not in ("=", "|"):
        arr = arr.astype(arr.dtype.newbyteorder("="))
    if arr.dtype == np.float64:
        arr = arr.astype(np.float32)
    if arr.dtype == np.float16:
        # 内部计算用float32，半精度值可无损提升。
        arr = arr.astype(np.float32)
    validate_pixel_array(arr)
    if arr.ndim == 2:
        return np.ascontiguousarray(arr)
    if arr.ndim != 3:
        raise ValueError(f"{source_name} 的图像维度 {arr.shape} 不受支持")
    channels = arr.shape[-1]
    if channels == 1:
        return np.ascontiguousarray(arr[..., 0])
    if channels == 2:
        # 灰度 + Alpha → RGBA
        lum = arr[..., 0]
        return np.ascontiguousarray(
            np.stack((lum, lum, lum, arr[..., 1]), axis=-1)
        )
    if channels in (3, 4):
        return np.ascontiguousarray(arr)
    raise ValueError(f"{source_name} 的通道数 {channels} 不受支持（需要1/2/3/4）")


def _png_bit_depth(path: Path) -> int:
    with path.open("rb") as stream:
        header = stream.read(25)
    if len(header) >= 25 and header[:8] == b"\x89PNG\r\n\x1a\n" and header[12:16] == b"IHDR":
        return int(header[24])
    raise ValueError(f"{path.name} 不是有效PNG")


def _load_png16(path: Path) -> np.ndarray:
    try:
        import png
    except ImportError as exc:
        raise RuntimeError("读取16-bit PNG需要安装 pypng（pip install pypng）") from exc
    with path.open("rb") as stream:
        width, height, rows, info = png.Reader(file=stream).read()
        planes = int(info["planes"])
        dtype = np.uint16 if int(info["bitdepth"]) > 8 else np.uint8
        flat = np.vstack([np.asarray(row, dtype=dtype) for row in rows])
    if planes == 1:
        return flat.reshape(height, width)
    return flat.reshape(height, width, planes)


def _load_tiff(path: Path) -> np.ndarray:
    try:
        import tifffile
    except ImportError as exc:
        raise RuntimeError("读取高位深TIFF需要安装 tifffile") from exc
    with tifffile.TiffFile(str(path)) as tiff:
        array = np.asarray(tiff.asarray())
        axes = tiff.series[0].axes if tiff.series else ""

    # DCC/渲染器经常把 RGB TIFF 写成 planar separate，此时 tifffile
    # 返回 S×H×W（axes="SYX"），而应用内部统一使用 H×W×C。只依据
    # TIFF 的显式 sample/channel axis 转置，避免把多页灰度 TIFF 误当 RGB。
    if array.ndim == 3:
        for channel_axis_name in ("S", "C"):
            if channel_axis_name not in axes:
                continue
            channel_axis = axes.index(channel_axis_name)
            if array.shape[channel_axis] in (1, 2, 3, 4):
                array = np.moveaxis(array, channel_axis, -1)
            break
    return array


def _load_exr(path: Path) -> np.ndarray:
    try:
        import OpenEXR
    except ImportError as exc:
        raise RuntimeError("读取EXR需要安装官方 OpenEXR Python模块") from exc
    with OpenEXR.File(str(path)) as exr:
        if len(exr.parts) != 1:
            raise ValueError(f"暂不支持多Part EXR: {path.name}")
        channels = exr.channels()
        for key in ("RGBA", "RGB", "Y"):
            if key in channels:
                pixels = np.asarray(channels[key].pixels)
                break
        else:
            if len(channels) == 1:
                pixels = np.asarray(next(iter(channels.values())).pixels)
            else:
                raise ValueError(
                    f"EXR没有可识别的 RGB/RGBA/Y 通道: {list(channels)}"
                )
    if pixels.dtype == object:
        raise ValueError("暂不支持 Deep EXR")
    return pixels


def load_image(path: Union[str, Path]) -> np.ndarray:
    """读取图像并保留 uint8、uint16 或 float32 精度。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"贴图文件不存在: {p}")
    suffix = p.suffix.lower()
    if suffix not in SUPPORTED_IMAGE_EXTS:
        raise ValueError(f"不支持的贴图格式: {suffix or '(无扩展名)'}")

    if suffix == ".exr":
        arr = _load_exr(p)
    elif suffix in {".tif", ".tiff"}:
        arr = _load_tiff(p)
    elif suffix == ".png" and _png_bit_depth(p) == 16:
        arr = _load_png16(p)
    else:
        with Image.open(p) as img:
            mode = str(img.mode)
            if mode not in SUPPORTED_8BIT_MODES:
                raise ValueError(
                    f"源贴图 {p.name} 的模式 {mode!r} 不受支持"
                )
            if img.mode not in ("RGB", "RGBA", "L"):
                img = img.convert("RGBA")
            arr = np.asarray(img)
    return _normalize_loaded_array(arr, p.name)


def extract_by_token(arr_hwc: np.ndarray, token) -> np.ndarray:
    """按 token 提取通道，保持输入 dtype/位深。"""
    from ..core.slot import ChannelToken
    from ..core.transcoder import _channel_from_token

    if arr_hwc.ndim == 2:
        if token is ChannelToken.BLACK:
            return np.zeros(arr_hwc.shape, dtype=arr_hwc.dtype)
        if token is ChannelToken.WHITE:
            return white_array(arr_hwc.shape, arr_hwc.dtype)
        ch = arr_hwc
        if token.is_inverted():
            ch = invert_values(ch)
        return ch.copy()

    if arr_hwc.shape[-1] == 3:
        rgba = np.zeros(arr_hwc.shape[:2] + (4,), dtype=arr_hwc.dtype)
        rgba[..., :3] = arr_hwc
        rgba[..., 3] = full_scale(arr_hwc.dtype)
    elif arr_hwc.shape[-1] == 4:
        rgba = arr_hwc
    else:
        raise ValueError(f"不支持的通道数: {arr_hwc.shape[-1]}")
    return _channel_from_token(rgba, token)


def load_slot(
    slot: ChannelSlot,
    spec: OutputSpec,
    file_cache: Optional[FileCache] = None,
) -> ChannelSlot:
    """读取、提取并按输出规格缩放一个槽，保留源位深。"""
    if slot.source_type is SourceType.EMPTY:
        slot.source_data = None
        slot.data = None
        return slot
    if slot.source_type is SourceType.SOLID:
        w, h = spec.effective_size()
        slot.source_data = np.full(
            (h, w), int(slot.solid_value), dtype=np.uint8,
        )
        slot.apply_post()
        return slot

    if slot.source_type is SourceType.EXTRACTED:
        source = slot.source_data if slot.source_data is not None else slot.data
        if source is not None:
            target_w, target_h = spec.effective_size()
            slot.data = (
                source.copy()
                if source.shape == (target_h, target_w)
                else resize_to(
                    source, target_h, target_w,
                    mode=spec.resize_mode, flt=spec.resize_filter,
                )
            )
            return slot
        if slot.file_path is None:
            slot.data = None
            return slot

    if slot.file_path is None:
        raise ValueError(f"槽 {slot.semantic} 标 FILE 但没有 file_path")
    path_str = str(slot.file_path)
    target_w, target_h = spec.effective_size()
    token_name = slot.token.name if hasattr(slot.token, "name") else str(slot.token)
    cache_variant = (spec.resize_mode.value, spec.resize_filter.value)

    if file_cache is not None:
        cached = file_cache.get(
            path_str, token_name, target_h, target_w, variant=cache_variant,
        )
        if cached is not None:
            slot.source_data = cached
            slot.apply_post()
            return slot

    arr = load_image(slot.file_path)
    chan = extract_by_token(arr, slot.token)
    if chan.shape != (target_h, target_w):
        chan = resize_to(
            chan, target_h, target_w,
            mode=spec.resize_mode, flt=spec.resize_filter,
        )
    slot.source_data = chan
    slot.apply_post()

    if file_cache is not None:
        file_cache.put(
            path_str, token_name, target_h, target_w, chan,
            variant=cache_variant,
        )
    return slot
