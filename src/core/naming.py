"""
naming — 输出资产名规则(对齐 UEToolbox 的 derive_output_asset_name)。

工作流:
    源文件名 "T_Floor_RMA.png" + preset.suffix "_ORM" → "T_Floor_ORM.png"
    overwrite=True 时 → "T_Floor_RMA.png" (覆盖源)

支持识别 + 替换的已知后缀:见 core.presets.KNOWN_PACKED_SUFFIXES。
"""
from __future__ import annotations

import re
from pathlib import Path

from .presets import KNOWN_PACKED_SUFFIXES


def validate_output_suffix(suffix: str) -> str:
    """校验 / 标准化输出后缀(必须以 _ 开头,只含字母数字下划线)。"""
    value = str(suffix or "").strip()
    if not value:
        raise ValueError("输出后缀不能为空。")
    if not value.startswith("_"):
        value = "_" + value
    if not re.fullmatch(r"_[A-Za-z0-9_]+", value):
        raise ValueError("输出后缀只能包含英文字母、数字和下划线。")
    return value


def derive_output_name(
    source_name: str,
    suffix: str = "_ORM",
    overwrite_source: bool = False,
) -> str:
    """根据源名 + 预设后缀推导输出名。

    Args:
        source_name: 源文件 stem(不带扩展名)
        suffix: 输出后缀(自动校验)
        overwrite_source: True → 返回原名(覆盖源)
    """
    source = str(source_name).strip()
    if overwrite_source:
        return source
    suffix = validate_output_suffix(suffix)

    stem = source
    lower = source.lower()
    for known in sorted(KNOWN_PACKED_SUFFIXES, key=len, reverse=True):
        if lower.endswith(known.lower()):
            stem = source[: -len(known)]
            break
    candidate = stem + suffix
    if candidate.lower() == source.lower():
        candidate += "_Converted"
    return candidate


def derive_output_path(
    source_path: Path,
    suffix: str = "_ORM",
    overwrite_source: bool = False,
) -> Path:
    """对完整文件路径推导输出路径(保留目录和扩展名)。"""
    p = Path(source_path)
    if overwrite_source:
        return p
    new_stem = derive_output_name(p.stem, suffix, overwrite_source=False)
    return p.with_name(new_stem + p.suffix)
