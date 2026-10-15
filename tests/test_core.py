"""
core 算法单测 — v2 token 模型。

跑法:
    cd 贴图转换
    python -m unittest tests.test_core -v
"""
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from src.core import (
    ChannelMap, ChannelSlot, ChannelToken, Semantic, ColorSpace, SourceType,
    OutputSpec, SizePreset, PotStrategy, ResizeMode, ResizeFilter,
    pack_rgba, unpack_rgba, reorder_rgba, drop_channel, invert_rgba,
    compose_token_mappings, transcode_between_presets, transcode_rgba,
    PRESETS, get_preset, derive_output_name, derive_output_path,
    colorspace,
)
from src.core.file_cache import FileCache
from src.core.resize import resize_to
from src.core.transform import rotate_image
from src.io.loader import load_image, load_slot
from src.io.saver import save_image


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------
class TestSlot(unittest.TestCase):
    def test_serialize_round_trip(self):
        s = ChannelSlot(
            semantic=Semantic.ROUGHNESS,
            display_name="粗糙度",
            source_type=SourceType.FILE,
            token=ChannelToken.INV_R,
            color_space=ColorSpace.LINEAR,
        )
        d = s.to_dict()
        s2 = ChannelSlot.from_dict(d)
        self.assertEqual(s.semantic, s2.semantic)
        self.assertEqual(s.display_name, s2.display_name)
        self.assertEqual(s.token, s2.token)
        self.assertEqual(s.color_space, s2.color_space)
        self.assertEqual(s.source_type, s2.source_type)

    def test_from_solid(self):
        s = ChannelSlot.from_solid(128, semantic=Semantic.HEIGHT)
        self.assertEqual(s.source_type, SourceType.SOLID)
        self.assertEqual(s.solid_value, 128)
        self.assertIsNotNone(s.data)
        self.assertEqual(int(s.data[0, 0]), 128)


class TestChannelToken(unittest.TestCase):
    def test_inverted(self):
        self.assertTrue(ChannelToken.INV_R.is_inverted())
        self.assertFalse(ChannelToken.R.is_inverted())
        self.assertTrue(ChannelToken.BLACK.is_solid())
        self.assertTrue(ChannelToken.WHITE.is_solid())
        self.assertFalse(ChannelToken.R.is_solid())

    def test_base_channel(self):
        self.assertEqual(ChannelToken.R.base_channel(), "R")
        self.assertEqual(ChannelToken.INV_G.base_channel(), "G")
        self.assertIsNone(ChannelToken.BLACK.base_channel())

    def test_from_str(self):
        self.assertEqual(ChannelToken.from_str("r"), ChannelToken.R)
        self.assertEqual(ChannelToken.from_str("INV_A"), ChannelToken.INV_A)
        with self.assertRaises(ValueError):
            ChannelToken.from_str("XYZ")


class TestOutputSpec(unittest.TestCase):
    def test_preset_2k(self):
        s = OutputSpec(size_preset=SizePreset.P2K)
        self.assertEqual(s.effective_size(), (2048, 2048))

    def test_custom_size(self):
        s = OutputSpec(width=1500, height=2000, size_preset=SizePreset.CUSTOM)
        self.assertEqual(s.effective_size(), (1500, 2000))

    def test_non_square_loader_uses_width_height_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gray.png"
            Image.fromarray(np.full((4, 2), 128, dtype=np.uint8), mode="L").save(path)
            slot = ChannelSlot.from_file(path, token=ChannelToken.R)
            spec = OutputSpec(
                width=3, height=5, size_preset=SizePreset.CUSTOM,
                resize_mode=ResizeMode.STRETCH,
            )
            load_slot(slot, spec)
            self.assertEqual(slot.data.shape, (5, 3))

    def test_pot_round_down(self):
        s = OutputSpec(width=1500, height=1500, force_pot=True, pot_strategy=PotStrategy.ROUND_DOWN)
        self.assertEqual(s.effective_size(), (1024, 1024))

    def test_pot_nearest(self):
        s = OutputSpec(width=1500, height=1500, force_pot=True, pot_strategy=PotStrategy.NEAREST)
        self.assertEqual(s.effective_size(), (1024, 1024))
        s = OutputSpec(width=1800, height=1800, force_pot=True, pot_strategy=PotStrategy.NEAREST)
        self.assertEqual(s.effective_size(), (2048, 2048))


class TestChannelMap(unittest.TestCase):
    def test_find_by_semantic(self):
        m = ChannelMap()
        m.R.semantic = Semantic.AO
        m.G.semantic = Semantic.ROUGHNESS
        m.B.semantic = Semantic.METALLIC
        hit = m.find_by_semantic(Semantic.METALLIC)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "B")

    def test_all_empty(self):
        m = ChannelMap()
        self.assertTrue(m.all_empty())


class TestColorSpace(unittest.TestCase):
    def test_srgb_linear_roundtrip(self):
        x = np.array([0, 64, 128, 192, 255], dtype=np.uint8)
        lin = colorspace.srgb_to_linear(x.copy())
        back = colorspace.linear_to_srgb(lin)
        back_u8 = (np.clip(back, 0, 1) * 255 + 0.5).astype(np.uint8)
        diff = np.abs(x.astype(int) - back_u8.astype(int))
        self.assertTrue(np.all(diff <= 1), f"roundtrip diff too large: {diff}")


class TestResize(unittest.TestCase):
    def test_stretch(self):
        a = np.zeros((100, 200), dtype=np.uint8)
        b = resize_to(a, 50, 100, ResizeMode.STRETCH, ResizeFilter.NEAREST)
        self.assertEqual(b.shape, (50, 100))

    def test_fit_covers(self):
        a = np.ones((100, 200), dtype=np.uint8) * 200
        b = resize_to(a, 50, 50, ResizeMode.FIT, ResizeFilter.NEAREST)
        self.assertEqual(b.shape, (50, 50))
        self.assertTrue(np.all(b == 200))

    def test_fill_pads(self):
        a = np.ones((100, 200), dtype=np.uint8) * 200
        b = resize_to(a, 200, 200, ResizeMode.FILL, ResizeFilter.NEAREST)
        self.assertEqual(b.shape, (200, 200))
        self.assertEqual(int(b[100, 100]), 200)
        self.assertEqual(int(b[0, 0]), 0)

    def test_none_mismatch_raises(self):
        a = np.zeros((100, 200), dtype=np.uint8)
        with self.assertRaises(ValueError):
            resize_to(a, 50, 50, ResizeMode.NONE, ResizeFilter.NEAREST)

    def test_uint16_resize_preserves_dtype_and_range(self):
        a = np.array([[0, 65535]], dtype=np.uint16)
        b = resize_to(a, 1, 4, ResizeMode.STRETCH, ResizeFilter.NEAREST)
        self.assertEqual(b.dtype, np.uint16)
        self.assertEqual(b.tolist(), [[0, 0, 65535, 65535]])


class TestHighPrecisionIO(unittest.TestCase):
    def test_uint16_rgba_png_roundtrip(self):
        arr = np.array(
            [
                [[0, 1, 32768, 65535], [65535, 40000, 20000, 1234]],
                [[5, 1024, 4096, 16384], [60000, 50000, 30000, 10000]],
            ],
            dtype=np.uint16,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rgba16.png"
            save_image(arr, path)
            loaded = load_image(path)
        self.assertEqual(loaded.dtype, np.uint16)
        self.assertTrue(np.array_equal(loaded, arr))

    def test_uint16_tiff_roundtrip(self):
        arr = np.arange(3 * 4 * 3, dtype=np.uint16).reshape(3, 4, 3) * 1777
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rgb16.tiff"
            save_image(arr, path)
            loaded = load_image(path)
        self.assertEqual(loaded.dtype, np.uint16)
        self.assertTrue(np.array_equal(loaded, arr))

    def test_planar_uint16_tiff_is_converted_to_hwc(self):
        import tifffile

        planar = np.arange(3 * 5 * 7, dtype=np.uint16).reshape(3, 5, 7)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "planar_rgb16.tiff"
            tifffile.imwrite(
                path,
                planar,
                photometric="rgb",
                planarconfig="separate",
            )
            loaded = load_image(path)
        self.assertEqual(loaded.shape, (5, 7, 3))
        self.assertEqual(loaded.dtype, np.uint16)
        self.assertTrue(np.array_equal(loaded, np.moveaxis(planar, 0, -1)))

    def test_float_exr_roundtrip_preserves_hdr(self):
        arr = np.array(
            [
                [[0.0, 0.5, 1.0, 2.0], [4.0, -0.25, 0.125, 1.0]],
                [[1.5, 2.5, 3.5, 0.0], [0.1, 0.2, 0.3, 0.4]],
            ],
            dtype=np.float32,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rgba.exr"
            save_image(arr, path)
            loaded = load_image(path)
        self.assertEqual(loaded.dtype, np.float32)
        self.assertTrue(np.array_equal(loaded, arr))


class TestTransform(unittest.TestCase):
    def test_rotate_90_is_exact_and_preserves_uint16(self):
        arr = np.arange(6, dtype=np.uint16).reshape(2, 3) * 10000
        rotated = rotate_image(arr, 90)
        self.assertEqual(rotated.dtype, np.uint16)
        self.assertTrue(np.array_equal(rotated, np.rot90(arr)))

    def test_arbitrary_rotation_expands_canvas_and_preserves_float(self):
        arr = np.ones((2, 4), dtype=np.float32) * 2.0
        rotated = rotate_image(arr, 45)
        self.assertEqual(rotated.dtype, np.float32)
        self.assertGreater(rotated.shape[0], arr.shape[0])
        self.assertGreater(rotated.shape[1], arr.shape[1])
        self.assertGreater(float(rotated.max()), 1.0)


# ---------------------------------------------------------------------------
# packer / unpacker
# ---------------------------------------------------------------------------
class TestPacker(unittest.TestCase):
    def test_pack_4_known_data(self):
        m = ChannelMap()
        m.R.data = np.full((4, 4), 10, dtype=np.uint8)
        m.G.data = np.full((4, 4), 20, dtype=np.uint8)
        m.B.data = np.full((4, 4), 30, dtype=np.uint8)
        m.A.data = np.full((4, 4), 40, dtype=np.uint8)
        rgba = pack_rgba(m)
        self.assertEqual(rgba.shape, (4, 4, 4))
        self.assertTrue(np.all(rgba[..., 0] == 10))
        self.assertTrue(np.all(rgba[..., 1] == 20))
        self.assertTrue(np.all(rgba[..., 2] == 30))
        self.assertTrue(np.all(rgba[..., 3] == 40))

    def test_pack_empty_fills_255(self):
        m = ChannelMap()
        m.R.data = np.full((2, 2), 1, dtype=np.uint8)
        rgba = pack_rgba(m)
        self.assertTrue(np.all(rgba[..., 0] == 1))
        self.assertTrue(np.all(rgba[..., 1] == 255))
        self.assertTrue(np.all(rgba[..., 2] == 255))
        self.assertTrue(np.all(rgba[..., 3] == 255))

    def test_pack_all_empty_raises(self):
        with self.assertRaises(ValueError):
            pack_rgba(ChannelMap())


# ---------------------------------------------------------------------------
# reorder / drop / invert(老工具,保留)
# ---------------------------------------------------------------------------
class TestReorder(unittest.TestCase):
    def test_abgr(self):
        rgba = np.zeros((2, 2, 4), dtype=np.uint8)
        rgba[..., 0] = 1
        rgba[..., 1] = 2
        rgba[..., 2] = 3
        rgba[..., 3] = 4
        out = reorder_rgba(rgba, "ABGR")
        self.assertTrue(np.all(out[..., 0] == 4))
        self.assertTrue(np.all(out[..., 1] == 3))
        self.assertTrue(np.all(out[..., 2] == 2))
        self.assertTrue(np.all(out[..., 3] == 1))

    def test_invalid_order(self):
        rgba = np.zeros((2, 2, 4), dtype=np.uint8)
        with self.assertRaises(ValueError):
            reorder_rgba(rgba, "RRGB")


class TestDrop(unittest.TestCase):
    def test_drop_to_255(self):
        rgba = np.full((2, 2, 4), 100, dtype=np.uint8)
        out = drop_channel(rgba, "A", fill=255)
        self.assertTrue(np.all(out[..., 3] == 255))
        self.assertTrue(np.all(out[..., 0] == 100))


class TestInvert(unittest.TestCase):
    def test_invert_all(self):
        rgba = np.array([[[0, 64, 128, 255]]], dtype=np.uint8)
        out = invert_rgba(rgba)
        self.assertTrue(np.all(out[..., 0] == 255))
        self.assertTrue(np.all(out[..., 1] == 191))
        self.assertTrue(np.all(out[..., 2] == 127))
        self.assertTrue(np.all(out[..., 3] == 0))


# ---------------------------------------------------------------------------
# transcoder(token 模型)
# ---------------------------------------------------------------------------
class TestTranscoder(unittest.TestCase):
    def test_identity(self):
        arr = np.zeros((4, 4, 4), dtype=np.uint8)
        arr[..., 0] = 11
        arr[..., 1] = 22
        arr[..., 2] = 33
        arr[..., 3] = 44
        out = transcode_rgba(
            arr,
            (ChannelToken.R, ChannelToken.G, ChannelToken.B, ChannelToken.A),
            remove_alpha=True,
        )
        self.assertEqual(out.shape, (4, 4, 3))
        self.assertTrue(np.all(out[..., 0] == 11))
        self.assertTrue(np.all(out[..., 1] == 22))
        self.assertTrue(np.all(out[..., 2] == 33))

    def test_invert_channel(self):
        arr = np.zeros((2, 2, 4), dtype=np.uint8)
        arr[..., 1] = 100  # G=100
        # 取 G 并 invert → 输出 R 应该是 155
        out = transcode_rgba(
            arr,
            (ChannelToken.INV_G, ChannelToken.R, ChannelToken.B, ChannelToken.A),
            remove_alpha=True,
        )
        self.assertTrue(np.all(out[..., 0] == 155))
        self.assertTrue(np.all(out[..., 1] == 0))  # 源 R=0

    def test_solid_tokens(self):
        arr = np.zeros((2, 2, 4), dtype=np.uint8)
        out = transcode_rgba(
            arr,
            (ChannelToken.BLACK, ChannelToken.WHITE, ChannelToken.A, ChannelToken.R),
            remove_alpha=True,
        )
        self.assertTrue(np.all(out[..., 0] == 0))
        self.assertTrue(np.all(out[..., 1] == 255))
        self.assertTrue(np.all(out[..., 2] == 0))  # 源 A=0
        # A 输出在 remove_alpha 时被丢弃

    def test_keep_alpha(self):
        arr = np.zeros((2, 2, 4), dtype=np.uint8)
        arr[..., 3] = 200
        out = transcode_rgba(
            arr,
            (ChannelToken.R, ChannelToken.G, ChannelToken.B, ChannelToken.A),
            remove_alpha=False,
        )
        self.assertEqual(out.shape, (2, 2, 4))
        self.assertTrue(np.all(out[..., 3] == 200))

    def test_orm_to_rma_preset(self):
        """源图是 ORM 排布(R=AO, G=Rough, B=Metal),目标用 RMA mapping 重打包。"""
        arr = np.zeros((4, 4, 4), dtype=np.uint8)
        arr[..., 0] = 11  # ORM R=AO
        arr[..., 1] = 22  # ORM G=Rough
        arr[..., 2] = 33  # ORM B=Metal
        rma = get_preset("rma")
        # RMA mapping = (G, B, R, A):目标 R=源 G, G=源 B, B=源 R
        out = transcode_rgba(arr, rma.mapping, remove_alpha=rma.remove_alpha)
        self.assertTrue(np.all(out[..., 0] == 22), "RMA R should be Rough (22)")
        self.assertTrue(np.all(out[..., 1] == 33), "RMA G should be Metal (33)")
        self.assertTrue(np.all(out[..., 2] == 11), "RMA B should be AO (11)")

    def test_rma_to_orm_composes_source_and_target(self):
        arr = np.zeros((1, 1, 4), dtype=np.uint8)
        arr[0, 0] = [22, 33, 11, 44]  # RMA:Rough,Metal,AO,Height
        out = transcode_between_presets(arr, get_preset("rma"), get_preset("ormh"))
        self.assertEqual(out[0, 0].tolist(), [11, 22, 33, 44])

    def test_same_preset_is_pixel_identity(self):
        arr = np.array([[[10, 20, 30, 40]]], dtype=np.uint8)
        out = transcode_between_presets(
            arr, get_preset("unity_mask"), get_preset("unity_mask"),
        )
        self.assertTrue(np.array_equal(out, arr))

    def test_unity_mask_preset_invert(self):
        """规范 ORMH → Unity HDRP MaskMap:R=Metal,G=AO,B=Detail,A=Smooth。"""
        arr = np.zeros((2, 2, 4), dtype=np.uint8)
        arr[..., 0] = 80   # AO
        arr[..., 1] = 205  # Roughness
        arr[..., 2] = 200  # Metallic
        arr[..., 3] = 100  # DetailMask
        unity = get_preset("unity_mask")
        out = transcode_rgba(arr, unity.mapping, remove_alpha=unity.remove_alpha)
        self.assertEqual(out.shape[-1], 4)
        self.assertTrue(np.all(out[..., 0] == 200), "R should be Metallic")
        self.assertTrue(np.all(out[..., 1] == 80), "G should be AO")
        self.assertTrue(np.all(out[..., 2] == 100), "B should be Detail")
        self.assertTrue(np.all(out[..., 3] == 50), "A should be Smoothness")


# ---------------------------------------------------------------------------
# presets
# ---------------------------------------------------------------------------
class TestPresets(unittest.TestCase):
    def test_count(self):
        self.assertEqual(len(PRESETS), 13)

    def test_get_preset(self):
        p = get_preset("orm")
        self.assertEqual(p.id, "orm")
        self.assertEqual(p.remove_alpha, True)
        self.assertEqual(p.suffix, "_ORM")

    def test_ormh_keeps_alpha(self):
        p = get_preset("ormh")
        self.assertEqual(p.remove_alpha, False)
        self.assertEqual(p.suffix, "_ORMH")

    def test_all_preset_suffixes_and_alpha(self):
        expected = {
            "orm": "_ORM", "rom": "_ROM", "rma": "_RMA", "mra": "_MRA",
            "unity_mask": "_MaskMap",
            "unity_standard": "_MetallicSmoothness",
            "gltf": "_ORM", "gltf_no_ao": "_MR",
            "ormh": "_ORMH", "rmah": "_RMAH", "mrah": "_MRAH",
            "ordp": "_ORDp", "custom": "_Packed",
        }
        self.assertEqual({p.id: p.suffix for p in PRESETS}, expected)
        self.assertFalse(get_preset("unity_mask").remove_alpha)
        self.assertFalse(get_preset("unity_standard").remove_alpha)

    def test_unknown_preset_raises(self):
        with self.assertRaises(ValueError):
            get_preset("nope")


# ---------------------------------------------------------------------------
# naming
# ---------------------------------------------------------------------------
class TestNaming(unittest.TestCase):
    def test_replace_known_suffix(self):
        self.assertEqual(derive_output_name("T_Floor_RMA", "_ORM"), "T_Floor_ORM")
        self.assertEqual(derive_output_name("T_Floor_MaskMap", "_ORM"), "T_Floor_ORM")
        self.assertEqual(derive_output_name("T_Floor_ORMH", "_ORM"), "T_Floor_ORM")
        # 不带已知后缀:直接加
        self.assertEqual(derive_output_name("T_Floor", "_ORM"), "T_Floor_ORM")

    def test_overwrite(self):
        self.assertEqual(derive_output_name("T_Floor", "_ORM", overwrite_source=True), "T_Floor")

    def test_same_suffix_avoid_clobber(self):
        # 已经是 _ORM,overwrite=False 时不会原地覆盖
        self.assertEqual(derive_output_name("T_Floor_ORM", "_ORM"), "T_Floor_ORM_Converted")

    def test_validate_suffix(self):
        from src.core.naming import validate_output_suffix
        self.assertEqual(validate_output_suffix("ORM"), "_ORM")
        self.assertEqual(validate_output_suffix("_ORM"), "_ORM")
        with self.assertRaises(ValueError):
            validate_output_suffix("_ORM-1")
        with self.assertRaises(ValueError):
            validate_output_suffix("")


class TestFileCache(unittest.TestCase):
    def test_resize_variant_is_part_of_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.png"
            path.write_bytes(b"x")
            cache = FileCache()
            value = np.ones((2, 2), dtype=np.uint8)
            cache.put(
                str(path), "R", 2, 2, value,
                variant=("fit", "lanczos"),
            )
            self.assertIsNotNone(
                cache.get(
                    str(path), "R", 2, 2,
                    variant=("fit", "lanczos"),
                )
            )
            self.assertIsNone(
                cache.get(
                    str(path), "R", 2, 2,
                    variant=("fill", "lanczos"),
                )
            )

    def test_byte_budget_evicts_old_entries_and_skips_oversized(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.bin"
            second = Path(tmp) / "second.bin"
            huge = Path(tmp) / "huge.bin"
            for path in (first, second, huge):
                path.write_bytes(b"x")
            cache = FileCache(max_size=10, max_bytes=8)
            cache.put(str(first), "R", 1, 4, np.ones(4, dtype=np.uint8))
            cache.put(str(second), "R", 1, 6, np.ones(6, dtype=np.uint8))
            self.assertIsNone(cache.get(str(first), "R", 1, 4))
            self.assertIsNotNone(cache.get(str(second), "R", 1, 6))
            self.assertLessEqual(cache.stats()["bytes"], 8)
            cache.put(str(huge), "R", 1, 9, np.ones(9, dtype=np.uint8))
            self.assertIsNone(cache.get(str(huge), "R", 1, 9))


class TestCLI(unittest.TestCase):
    def test_pack_defaults_use_valid_r_token(self):
        from src.cli.main import build_parser

        args = build_parser().parse_args(["pack", "--r", "a.png", "--out", "o.png"])
        self.assertEqual((args.rt, args.gt, args.bt, args.at), ("R", "R", "R", "R"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
