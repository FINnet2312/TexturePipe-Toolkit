"""
CLI 入口 — 命令行跑通 core(对齐 UEToolbox 的能力)。

子命令:
  pack       4 张灰度 → 1 张 RGB/RGBA(用 token 列表)
  unpack     1 张 RGBA → 4 张灰度
  reorder    RGBA 通道重排
  drop       把某通道清成 0/255
  invert     通道取反(用 invert 工具,token 模型在 transcode 里)
  transcode  按 preset 互转(13 个内置预设)
  batch      批处理:遍历一文件夹,每张按 preset 转,产出 CSV 报告
"""
import argparse
import csv
import sys
from pathlib import Path
from typing import Iterable

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import (  # noqa: E402
    ChannelMap, ChannelSlot, ChannelToken, Semantic, ColorSpace,
    OutputSpec, SizePreset,
    pack_rgba, unpack_rgba, reorder_rgba, drop_channel, invert_rgba,
    compose_token_mappings, transcode_rgba, transcode_between_presets,
    PRESETS, get_preset, derive_output_path,
)
from src.io.loader import load_image, load_slot  # noqa: E402
from src.io.saver import save_rgba, save_grayscale, save_map_rgba  # noqa: E402
from src.core.output_spec import PotStrategy, ResizeMode, ResizeFilter  # noqa: E402
from src.core.pixels import full_scale  # noqa: E402
from src.io.loader import SUPPORTED_IMAGE_EXTS  # noqa: E402


# 旧 NAMED_FORMATS(简短别名) → preset id
ALIAS: dict[str, str] = {
    "ORM": "orm", "RMA": "rma", "MRA": "mra", "ROM": "rom",
    "ARM": "orm",  # ARM = ORM
    "ORMH": "ormh", "RMAH": "rmah", "MRAH": "mrah",
    "GLTF": "gltf", "GLTF_NO_AO": "gltf_no_ao",
    "UNITY_MASK": "unity_mask", "UNITY_STANDARD": "unity_standard",
    "ORDP": "ordp", "CUSTOM": "custom",
}


def _ensure_rgba(arr: np.ndarray) -> np.ndarray:
    if arr.ndim == 2:
        rgba = np.zeros(arr.shape + (4,), dtype=arr.dtype)
        rgba[..., 0] = arr
        rgba[..., 3] = full_scale(arr.dtype)
        return rgba
    if arr.shape[-1] == 3:
        rgba = np.zeros(arr.shape[:2] + (4,), dtype=arr.dtype)
        rgba[..., :3] = arr
        rgba[..., 3] = full_scale(arr.dtype)
        return rgba
    return arr


def parse_tokens(s: str) -> list[ChannelToken]:
    """'R,G,INV_A,BLACK' → [R, G, INV_A, BLACK]"""
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError(f"token 序列必须 4 项,got {len(parts)}: {s!r}")
    return [ChannelToken.from_str(p) for p in parts]


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------
def cmd_pack(args):
    spec = OutputSpec(
        size_preset=SizePreset(args.size) if args.size != "custom" else SizePreset.CUSTOM,
        width=args.width, height=args.height,
        resize_mode=ResizeMode(args.resize),
        resize_filter=ResizeFilter(args.filter),
        force_pot=args.pot,
        pot_strategy=PotStrategy(args.pot_strategy),
    )
    cm = ChannelMap()
    for name, path, token in [
        ("R", args.r, args.rt), ("G", args.g, args.gt),
        ("B", args.b, args.bt), ("A", args.a, args.at),
    ]:
        if path is None:
            continue
        slot = ChannelSlot.from_file(path, token=ChannelToken.from_str(token))
        setattr(cm, name, slot)
        load_slot(getattr(cm, name), spec)
    if args.remove_alpha:
        save_rgba(pack_rgba(cm)[..., :3], args.out)
    else:
        save_map_rgba(cm, args.out)
    print(f"[pack] {args.out}")


def cmd_unpack(args):
    arr = _ensure_rgba(load_image(args.src))
    cm = unpack_rgba(arr, color_space=ColorSpace(args.colorspace))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    suffix = ".exr" if arr.dtype.kind == "f" else ".png"
    for name, slot in cm.slots():
        if slot.data is None:
            continue
        save_grayscale(slot.data, out_dir / f"{Path(args.src).stem}_{name}{suffix}")
        n += 1
    print(f"[unpack] {n} channels -> {out_dir}")


def cmd_reorder(args):
    arr = _ensure_rgba(load_image(args.src))
    out = reorder_rgba(arr, args.order)
    save_rgba(out, args.out)
    print(f"[reorder] {args.src} -> {args.out} (order={args.order})")


def cmd_drop(args):
    arr = _ensure_rgba(load_image(args.src))
    out = drop_channel(arr, args.drop, fill=args.fill)
    save_rgba(out, args.out)
    print(f"[drop] {args.src} -> {args.out} (drop={args.drop}, fill={args.fill})")


def cmd_invert(args):
    arr = _ensure_rgba(load_image(args.src))
    out = invert_rgba(arr, channels=args.channels)
    save_rgba(out, args.out)
    print(f"[invert] {args.src} -> {args.out} (channels={args.channels})")


def cmd_transcode(args):
    arr = _ensure_rgba(load_image(args.input))
    if args.src_tokens:
        # 显式描述"规范→源格式"与"规范→目标格式",再组合成物理源图映射。
        src_tokens = parse_tokens(args.src_tokens)
        dst_tokens = parse_tokens(args.dst_tokens) if args.dst_tokens else src_tokens
        mapping = compose_token_mappings(src_tokens, dst_tokens)
        remove_alpha = args.remove_alpha
    else:
        # 用 preset id。源默认 ORM,目标默认与源相同。
        src_preset = get_preset(args.src_preset or "orm")
        dst_preset = get_preset(args.dst_preset) if args.dst_preset else src_preset
        mapping = compose_token_mappings(src_preset.mapping, dst_preset.mapping)
        remove_alpha = dst_preset.remove_alpha
    out = transcode_rgba(arr, mapping, remove_alpha=remove_alpha)
    save_rgba(out, args.out)
    suffix_hint = ""
    if args.src_tokens is None and args.dst_preset is None:
        suffix_hint = " (presets identical, no change)"
    print(f"[transcode] {args.input} -> {args.out}{suffix_hint}")


def cmd_batch(args):
    """遍历输入文件夹,每张图按 preset 转码,产出 CSV 报告。"""
    in_dir = Path(args.input_dir)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    preset = get_preset(args.preset)
    src_preset = get_preset(args.src_preset)
    remove_alpha = args.remove_alpha if args.remove_alpha is not None else preset.remove_alpha
    mapping = compose_token_mappings(src_preset.mapping, preset.mapping)
    exts = SUPPORTED_IMAGE_EXTS

    rows: list[dict] = []
    claimed_targets: dict[str, Path] = {}
    n_ok = 0
    n_fail = 0
    for src_path in sorted(in_dir.iterdir()):
        if src_path.suffix.lower() not in exts:
            continue
        try:
            arr = _ensure_rgba(load_image(src_path))
            out_arr = transcode_rgba(arr, mapping, remove_alpha=remove_alpha)
            # 推导输出名(识别已知后缀替换)
            out_path = out_dir / (derive_output_path(src_path, suffix=preset.suffix).name)
            target_key = out_path.name.casefold()
            previous = claimed_targets.get(target_key)
            if previous is not None and previous != src_path:
                raise ValueError(
                    f"输出名冲突:{previous.name} 与 {src_path.name} "
                    f"都会写入 {out_path.name}"
                )
            claimed_targets[target_key] = src_path
            save_rgba(out_arr, out_path)
            rows.append({
                "SourceAsset": src_path.name,
                "TargetAsset": out_path.name,
                "PresetId": preset.id,
                "PresetLabel": preset.label,
                "OutputR": mapping[0].value,
                "OutputG": mapping[1].value,
                "OutputB": mapping[2].value,
                "OutputA": mapping[3].value,
                "RemoveAlpha": remove_alpha,
                "Status": "OK",
            })
            n_ok += 1
        except Exception as exc:  # noqa: BLE001
            rows.append({
                "SourceAsset": src_path.name,
                "TargetAsset": "",
                "PresetId": preset.id,
                "PresetLabel": preset.label,
                "OutputR": "", "OutputG": "", "OutputB": "", "OutputA": "",
                "RemoveAlpha": remove_alpha,
                "Status": f"FAIL: {exc}",
            })
            n_fail += 1

    # CSV 报告
    report_path = out_dir / (args.report_name or "batch_report.csv")
    fieldnames = [
        "SourceAsset", "TargetAsset", "PresetId", "PresetLabel",
        "OutputR", "OutputG", "OutputB", "OutputA",
        "RemoveAlpha", "Status",
    ]
    with report_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"[batch] {n_ok} ok, {n_fail} fail -> {report_path}")


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="texpipe", description="贴图通道转换工具 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("pack", help="4 张灰度 → 1 张 RGB/RGBA(token 描述)")
    sp.add_argument("--r"); sp.add_argument("--g"); sp.add_argument("--b"); sp.add_argument("--a")
    sp.add_argument("--rt", default="R", help="R 槽 token: R/G/B/A/INV_*/BLACK/WHITE")
    sp.add_argument("--gt", default="R")
    sp.add_argument("--bt", default="R")
    sp.add_argument("--at", default="R")
    sp.add_argument("--out", required=True)
    sp.add_argument("--size", default="custom", choices=[s.value for s in SizePreset])
    sp.add_argument("--width", type=int, default=2048)
    sp.add_argument("--height", type=int, default=2048)
    sp.add_argument("--resize", default="fit", choices=[m.value for m in ResizeMode])
    sp.add_argument("--filter", default="lanczos", choices=[f.value for f in ResizeFilter])
    sp.add_argument("--pot", action="store_true", help="把宽高对齐到 2 的幂")
    sp.add_argument(
        "--pot-strategy", default="round_up",
        choices=[p.value for p in PotStrategy],
    )
    sp.add_argument("--remove-alpha", action="store_true", help="输出 3 通道 RGB")
    sp.set_defaults(func=cmd_pack)

    sp = sub.add_parser("unpack", help="1 张 RGBA → 4 张灰度")
    sp.add_argument("src"); sp.add_argument("--out-dir", required=True)
    sp.add_argument("--colorspace", default="Linear")
    sp.set_defaults(func=cmd_unpack)

    sp = sub.add_parser("reorder", help="RGBA 通道重排")
    sp.add_argument("src"); sp.add_argument("--order", required=True); sp.add_argument("--out", required=True)
    sp.set_defaults(func=cmd_reorder)

    sp = sub.add_parser("drop", help="把某通道清成 0/255")
    sp.add_argument("src"); sp.add_argument("--drop", choices=["R", "G", "B", "A"], required=True)
    sp.add_argument("--fill", type=int, default=255); sp.add_argument("--out", required=True)
    sp.set_defaults(func=cmd_drop)

    sp = sub.add_parser("invert", help="通道取反(整图)")
    sp.add_argument("src"); sp.add_argument("--channels", default="RGBA"); sp.add_argument("--out", required=True)
    sp.set_defaults(func=cmd_invert)

    sp = sub.add_parser("transcode", help="格式互转(token 模型)")
    sp.add_argument("input", help="输入贴图（PNG/TIFF/EXR 等）")
    sp.add_argument("--src-tokens", help="源 4 token: 'R,G,INV_A,BLACK'")
    sp.add_argument("--dst-tokens", help="目标 4 token(默认与源相同)")
    sp.add_argument("--src-preset", help="源 preset id(13 个之一)")
    sp.add_argument("--dst-preset", help="目标 preset id(默认与源相同)")
    sp.add_argument("--remove-alpha", action="store_true")
    sp.add_argument("--out", required=True)
    sp.set_defaults(func=cmd_transcode)

    sp = sub.add_parser("batch", help="批处理 + CSV 报告")
    sp.add_argument("--input-dir", required=True)
    sp.add_argument("--output-dir", required=True)
    sp.add_argument("--src-preset", default="orm", help="源 preset id(默认 orm)")
    sp.add_argument("--preset", required=True, help="preset id")
    sp.add_argument("--remove-alpha", type=lambda s: s.lower() in ("1", "true", "yes"), default=None)
    sp.add_argument("--report-name", default="batch_report.csv")
    sp.set_defaults(func=cmd_batch)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
