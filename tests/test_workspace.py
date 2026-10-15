"""目录化工程格式测试。"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from src.core.map import ChannelMap
from src.core.output_spec import OutputSpec, SizePreset
from src.core.slot import ChannelSlot, ChannelToken, Semantic, SourceType
from src.io.workspace import (
    load_recovery_snapshot,
    load_workspace,
    recovery_snapshot_available,
    save_project_directory,
    save_recovery_snapshot,
)


class TestWorkspaceDirectory(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="texpipe_project_"))

    def test_extracted_uint16_and_float_snapshots_roundtrip(self):
        channel_map = ChannelMap()
        red = ChannelSlot(
            semantic=Semantic.ROUGHNESS,
            source_type=SourceType.EXTRACTED,
            token=ChannelToken.R,
        )
        red.source_data = np.array(
            [[0, 1, 32768, 65535]],
            dtype=np.uint16,
        )
        red.data = red.source_data.copy()
        alpha = ChannelSlot(
            semantic=Semantic.HEIGHT,
            source_type=SourceType.EXTRACTED,
            token=ChannelToken.R,
        )
        alpha.source_data = np.array(
            [[-0.5, 0.0, 1.0, 4.0]],
            dtype=np.float32,
        )
        alpha.data = alpha.source_data.copy()
        channel_map.R = red
        channel_map.A = alpha

        project = self.temp / "project"
        manifest = save_project_directory(
            project,
            channel_map,
            OutputSpec(width=4, height=1, size_preset=SizePreset.CUSTOM),
        )
        loaded = load_workspace(manifest)

        self.assertEqual(loaded.channel_map.R.source_type, SourceType.EXTRACTED)
        self.assertEqual(loaded.channel_map.R.data.dtype, np.uint16)
        self.assertTrue(
            np.array_equal(loaded.channel_map.R.data, red.source_data),
        )
        self.assertEqual(loaded.channel_map.A.data.dtype, np.float32)
        self.assertTrue(
            np.array_equal(loaded.channel_map.A.data, alpha.source_data),
        )

    def test_embedded_source_survives_project_move(self):
        source = self.temp / "source.png"
        rgba = np.zeros((3, 5, 4), dtype=np.uint8)
        rgba[..., 0] = 91
        rgba[..., 3] = 255
        Image.fromarray(rgba, mode="RGBA").save(source)
        channel_map = ChannelMap()
        channel_map.R = ChannelSlot.from_file(
            source,
            token=ChannelToken.R,
            semantic=Semantic.ROUGHNESS,
        )

        original_project = self.temp / "original_project"
        save_project_directory(
            original_project,
            channel_map,
            OutputSpec(width=5, height=3, size_preset=SizePreset.CUSTOM),
        )
        moved_project = self.temp / "moved_project"
        shutil.copytree(original_project, moved_project)
        source.unlink()

        loaded = load_workspace(moved_project)
        embedded = loaded.channel_map.R.file_path
        self.assertIsNotNone(embedded)
        self.assertTrue(embedded.exists())
        self.assertEqual(moved_project.resolve(), embedded.parents[2])

    def test_repeated_save_does_not_duplicate_embedded_source(self):
        source = self.temp / "repeat.png"
        Image.fromarray(
            np.full((2, 2), 45, dtype=np.uint8),
            mode="L",
        ).save(source)
        channel_map = ChannelMap()
        channel_map.R = ChannelSlot.from_file(source, token=ChannelToken.R)
        project = self.temp / "repeat_project"
        spec = OutputSpec(
            width=2,
            height=2,
            size_preset=SizePreset.CUSTOM,
        )
        manifest = save_project_directory(project, channel_map, spec)
        loaded = load_workspace(manifest)
        save_project_directory(project, loaded.channel_map, loaded.output_spec)

        embedded_files = list((project / "assets" / "sources").iterdir())
        self.assertEqual(len(embedded_files), 1)

    def test_manifest_uses_relative_paths_and_expected_directories(self):
        channel_map = ChannelMap()
        slot = ChannelSlot(
            source_type=SourceType.EXTRACTED,
            token=ChannelToken.R,
        )
        slot.source_data = np.full((2, 2), 7, dtype=np.uint8)
        slot.data = slot.source_data.copy()
        channel_map.G = slot
        project = self.temp / "layout"
        manifest = save_project_directory(
            project,
            channel_map,
            OutputSpec(width=2, height=2, size_preset=SizePreset.CUSTOM),
        )
        data = json.loads(manifest.read_text(encoding="utf-8"))

        self.assertEqual(data["format"], "texpipe-project")
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(
            data["map"]["G"]["state_asset"]["path"],
            "assets/state/G.npy",
        )
        self.assertTrue((project / "cache").is_dir())
        self.assertTrue((project / "autosave").is_dir())

    def test_legacy_json_still_loads(self):
        legacy = self.temp / "legacy.json"
        channel_map = ChannelMap()
        channel_map.B = ChannelSlot.from_solid(
            123,
            semantic=Semantic.METALLIC,
        )
        legacy.write_text(
            json.dumps({
                "map": channel_map.to_dict(),
                "spec": OutputSpec().to_dict(),
            }),
            encoding="utf-8",
        )
        loaded = load_workspace(legacy)
        self.assertTrue(loaded.legacy)
        self.assertEqual(loaded.channel_map.B.solid_value, 123)

    def test_dirty_recovery_snapshot_restores_latest_pixels(self):
        channel_map = ChannelMap()
        slot = ChannelSlot(
            source_type=SourceType.EXTRACTED,
            token=ChannelToken.R,
        )
        slot.source_data = np.full((2, 3), 10, dtype=np.uint16)
        slot.data = slot.source_data.copy()
        channel_map.R = slot
        project = self.temp / "recovery_project"
        spec = OutputSpec(
            width=3,
            height=2,
            size_preset=SizePreset.CUSTOM,
        )
        save_project_directory(project, channel_map, spec)
        self.assertFalse(recovery_snapshot_available(project))

        slot.source_data = np.full((2, 3), 60000, dtype=np.uint16)
        slot.data = slot.source_data.copy()
        save_recovery_snapshot(project, channel_map, spec, clean=False)
        self.assertTrue(recovery_snapshot_available(project))

        recovered = load_recovery_snapshot(project)
        self.assertEqual(recovered.project_dir, project.resolve())
        self.assertEqual(recovered.channel_map.R.data.dtype, np.uint16)
        self.assertTrue(np.all(recovered.channel_map.R.data == 60000))


if __name__ == "__main__":
    unittest.main(verbosity=2)
