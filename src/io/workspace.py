"""目录化工作区的保存、加载与旧 JSON 兼容。

工程目录布局::

    project.json
    assets/
      sources/   外部源贴图的可移动副本
      state/     当前槽像素的精确 NumPy 快照
    cache/       可重建缓存（预留）
    autosave/    崩溃恢复数据（预留）
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from src.core.map import ChannelMap
from src.core.output_spec import OutputSpec
from src.core.pixels import validate_pixel_array
from src.core.slot import ChannelToken, SourceType


PROJECT_FORMAT = "texpipe-project"
PROJECT_SCHEMA_VERSION = 1
PROJECT_FILENAME = "project.json"
RECOVERY_FILENAME = "recovery.json"


@dataclass(frozen=True)
class LoadedWorkspace:
    channel_map: ChannelMap
    output_spec: OutputSpec
    project_dir: Path
    manifest_path: Path
    legacy: bool = False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_array(array: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(repr(tuple(array.shape)).encode("ascii"))
    digest.update(np.ascontiguousarray(array).view(np.uint8))
    return digest.hexdigest()


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _atomic_save_array(path: Path, array: np.ndarray) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as stream:
        np.save(stream, np.ascontiguousarray(array), allow_pickle=False)
    os.replace(temporary, path)


def _atomic_copy(source: Path, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _safe_project_path(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError(f"工程资源路径越界: {relative_path}")
    return candidate


def _project_root(path: Path | str) -> Path:
    candidate = Path(path)
    if candidate.suffix.lower() == ".json":
        return candidate.parent
    return candidate


def save_project_directory(
    project_dir: Path | str,
    channel_map: ChannelMap,
    output_spec: OutputSpec,
    *,
    embed_sources: bool = True,
) -> Path:
    """保存可移动工程目录，返回 ``project.json`` 路径。

    每个非空槽都会保存当前像素快照。FILE 槽默认额外复制原始源贴图，
    因此工程移动后仍可按不同输出尺寸重新加载；EXTRACTED 槽由 NumPy
    快照恢复，精确保留 uint16/float/HDR。
    """
    root = _project_root(project_dir).resolve()
    assets = root / "assets"
    sources = assets / "sources"
    states = assets / "state"
    cache = root / "cache"
    autosave = root / "autosave"
    for directory in (root, assets, sources, states, cache, autosave):
        directory.mkdir(parents=True, exist_ok=True)

    map_data = channel_map.to_dict()
    embedded_by_hash: dict[str, Path] = {}
    for channel_name, slot in channel_map.slots():
        entry = map_data[channel_name]
        current = slot.source_data if slot.source_data is not None else slot.data
        if current is not None:
            validate_pixel_array(current)
            state_path = states / f"{channel_name}.npy"
            _atomic_save_array(state_path, current)
            entry["state_asset"] = {
                "path": _relative(state_path, root),
                "dtype": str(current.dtype),
                "shape": list(current.shape),
                "sha256": _sha256_array(current),
            }

        if (
            slot.source_type is SourceType.FILE
            and slot.file_path is not None
            and embed_sources
        ):
            source_path = slot.file_path.resolve()
            if not source_path.exists():
                entry["source_warning"] = "源文件保存时不存在，加载时将使用状态快照"
                continue
            source_hash = _sha256_file(source_path)
            try:
                source_path.relative_to(root)
                source_is_inside_project = True
            except ValueError:
                source_is_inside_project = False
            embedded_path = (
                source_path
                if source_is_inside_project
                else embedded_by_hash.get(source_hash)
            )
            if embedded_path is None:
                safe_name = "".join(
                    character
                    if character.isalnum() or character in "._-"
                    else "_"
                    for character in source_path.name
                )
                embedded_path = sources / f"{source_hash[:12]}_{safe_name}"
                if not embedded_path.exists() or _sha256_file(embedded_path) != source_hash:
                    _atomic_copy(source_path, embedded_path)
                embedded_by_hash[source_hash] = embedded_path
            entry["source"] = {
                "original_path": str(source_path),
                "sha256": source_hash,
                "embedded_path": _relative(embedded_path, root),
            }
            entry["file_path"] = _relative(embedded_path, root)

        if slot.source_type is SourceType.EXTRACTED and current is not None:
            entry["file_path"] = None
            entry["token"] = ChannelToken.R.value

    manifest = {
        "format": PROJECT_FORMAT,
        "schema_version": PROJECT_SCHEMA_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "map": map_data,
        "spec": output_spec.to_dict(),
        "directories": {
            "assets": "assets",
            "cache": "cache",
            "autosave": "autosave",
        },
    }
    manifest_path = root / PROJECT_FILENAME
    _atomic_write_json(manifest_path, manifest)
    save_recovery_snapshot(root, channel_map, output_spec, clean=True)
    return manifest_path


def save_recovery_snapshot(
    project_dir: Path | str,
    channel_map: ChannelMap,
    output_spec: OutputSpec,
    *,
    clean: bool = False,
) -> Path:
    """保存当前内存状态，用于异常退出后的恢复。

    恢复快照把所有当前槽数据转为 EXTRACTED NumPy 资产，不依赖外部文件；
    ``clean=True`` 表示它与正式 ``project.json`` 同步，无需提示恢复。
    """
    root = _project_root(project_dir).resolve()
    recovery_root = root / "autosave"
    recovery_assets = recovery_root / "assets"
    recovery_assets.mkdir(parents=True, exist_ok=True)
    map_data = channel_map.to_dict()
    for channel_name, slot in channel_map.slots():
        current = slot.source_data if slot.source_data is not None else slot.data
        if current is None:
            continue
        validate_pixel_array(current)
        asset_path = recovery_assets / f"{channel_name}.npy"
        _atomic_save_array(asset_path, current)
        entry = map_data[channel_name]
        entry["source_type"] = SourceType.EXTRACTED.value
        entry["file_path"] = None
        entry["token"] = ChannelToken.R.value
        entry["state_asset"] = {
            "path": f"assets/{channel_name}.npy",
            "dtype": str(current.dtype),
            "shape": list(current.shape),
            "sha256": _sha256_array(current),
        }
    manifest = {
        "format": PROJECT_FORMAT,
        "schema_version": PROJECT_SCHEMA_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "recovery": True,
        "clean": bool(clean),
        "map": map_data,
        "spec": output_spec.to_dict(),
    }
    recovery_path = recovery_root / RECOVERY_FILENAME
    _atomic_write_json(recovery_path, manifest)
    return recovery_path


def _load_state_asset(
    root: Path,
    entry: dict[str, Any],
) -> np.ndarray | None:
    metadata = entry.get("state_asset")
    if not isinstance(metadata, dict) or not metadata.get("path"):
        return None
    asset_path = _safe_project_path(root, str(metadata["path"]))
    if not asset_path.exists():
        return None
    array = np.load(asset_path, allow_pickle=False)
    validate_pixel_array(array)
    expected_shape = tuple(metadata.get("shape", array.shape))
    expected_dtype = str(metadata.get("dtype", array.dtype))
    if array.shape != expected_shape or str(array.dtype) != expected_dtype:
        raise ValueError(f"工作区像素快照元数据不匹配: {asset_path.name}")
    expected_hash = metadata.get("sha256")
    if expected_hash and _sha256_array(array) != expected_hash:
        raise ValueError(f"工作区像素快照校验失败: {asset_path.name}")
    return np.ascontiguousarray(array)


def _load_project_manifest(
    manifest_path: Path,
    data: dict[str, Any],
    *,
    project_dir: Path | None = None,
) -> LoadedWorkspace:
    version = int(data.get("schema_version", 0))
    if version > PROJECT_SCHEMA_VERSION:
        raise ValueError(
            f"工程版本 {version} 高于当前支持版本 {PROJECT_SCHEMA_VERSION}",
        )
    root = manifest_path.parent.resolve()
    map_data = data.get("map", {})
    channel_map = ChannelMap.from_dict(map_data)
    output_spec = OutputSpec.from_dict(data.get("spec", {}))

    for channel_name, slot in channel_map.slots():
        entry = map_data.get(channel_name, {})
        state = _load_state_asset(root, entry)
        if slot.file_path is not None and not slot.file_path.is_absolute():
            slot.file_path = _safe_project_path(root, str(slot.file_path))
        if slot.source_type is SourceType.EXTRACTED and state is not None:
            slot.source_data = state
            slot.data = state.copy()
        elif (
            slot.source_type is SourceType.FILE
            and (slot.file_path is None or not slot.file_path.exists())
            and state is not None
        ):
            # 内嵌源丢失时仍能恢复保存时的准确像素状态。
            slot.source_type = SourceType.EXTRACTED
            slot.file_path = None
            slot.token = ChannelToken.R
            slot.source_data = state
            slot.data = state.copy()
    return LoadedWorkspace(
        channel_map=channel_map,
        output_spec=output_spec,
        project_dir=(project_dir or root).resolve(),
        manifest_path=manifest_path,
    )


def _load_legacy_workspace(
    manifest_path: Path,
    data: dict[str, Any],
) -> LoadedWorkspace:
    channel_map = ChannelMap.from_dict(data.get("map", {}))
    output_spec = OutputSpec.from_dict(data.get("spec", {}))
    root = manifest_path.parent.resolve()
    for _channel_name, slot in channel_map.slots():
        if slot.file_path is not None and not slot.file_path.is_absolute():
            slot.file_path = (root / slot.file_path).resolve()
    return LoadedWorkspace(
        channel_map=channel_map,
        output_spec=output_spec,
        project_dir=root,
        manifest_path=manifest_path,
        legacy=True,
    )


def load_workspace(path: Path | str) -> LoadedWorkspace:
    """加载工程目录、其中的 ``project.json`` 或旧式工作区 JSON。"""
    candidate = Path(path)
    manifest_path = (
        candidate / PROJECT_FILENAME
        if candidate.is_dir() or not candidate.suffix
        else candidate
    )
    if not manifest_path.exists():
        raise FileNotFoundError(f"工作区清单不存在: {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("format") == PROJECT_FORMAT:
        return _load_project_manifest(manifest_path, data)
    return _load_legacy_workspace(manifest_path, data)


def recovery_snapshot_available(project_dir: Path | str) -> bool:
    """是否存在比正式保存更新、需要询问用户的恢复快照。"""
    root = _project_root(project_dir).resolve()
    recovery_path = root / "autosave" / RECOVERY_FILENAME
    if not recovery_path.exists():
        return False
    try:
        data = json.loads(recovery_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        data.get("format") == PROJECT_FORMAT
        and bool(data.get("recovery"))
        and not bool(data.get("clean"))
    )


def load_recovery_snapshot(project_dir: Path | str) -> LoadedWorkspace:
    """加载工程的异常恢复快照。"""
    root = _project_root(project_dir).resolve()
    recovery_path = root / "autosave" / RECOVERY_FILENAME
    if not recovery_path.exists():
        raise FileNotFoundError(f"恢复快照不存在: {recovery_path}")
    data = json.loads(recovery_path.read_text(encoding="utf-8"))
    if not data.get("recovery"):
        raise ValueError(f"不是有效的恢复快照: {recovery_path}")
    return _load_project_manifest(
        recovery_path,
        data,
        project_dir=root,
    )


__all__ = [
    "LoadedWorkspace",
    "PROJECT_FILENAME",
    "PROJECT_FORMAT",
    "PROJECT_SCHEMA_VERSION",
    "RECOVERY_FILENAME",
    "load_recovery_snapshot",
    "load_workspace",
    "recovery_snapshot_available",
    "save_recovery_snapshot",
    "save_project_directory",
]
