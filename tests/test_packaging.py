from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from src.app_info import APP_NAME, APP_VERSION
from src.ui.main import _build_argparser, _set_windows_app_id


ROOT = Path(__file__).resolve().parents[1]


class PackagingContractTests(unittest.TestCase):
    def test_application_metadata_is_stable(self):
        self.assertEqual(APP_NAME, "Texpipe")
        self.assertEqual(APP_VERSION, "1.1.0")
        self.assertEqual((ROOT / "VERSION").read_text().strip(), APP_VERSION)

    def test_parser_supports_frozen_smoke_alias_and_version(self):
        args = _build_argparser().parse_args(["--smoke-test"])
        self.assertTrue(args.smoke_test)
        args = _build_argparser().parse_args(["--smoke"])
        self.assertTrue(args.smoke_test)

    def test_spec_and_version_resource_exist(self):
        spec_path = ROOT / "texpipe.spec"
        self.assertTrue(spec_path.is_file())
        self.assertTrue(
            (ROOT / "packaging" / "windows_version_info.txt").is_file()
        )
        spec_text = spec_path.read_text(encoding="utf-8")
        self.assertIn('collect_submodules("src.ui.skybox_noise")', spec_text)
        self.assertIn('"numba",', spec_text)

    def test_build_script_recreates_a_broken_virtual_environment(self):
        script = (ROOT / "build_exe.ps1").read_text(encoding="utf-8")
        self.assertIn("function Test-BuildPython", script)
        self.assertIn("if (-not (Test-BuildPython))", script)
        self.assertIn("recreating it", script)

    def test_windows_app_id_is_a_noop_off_windows(self):
        with patch.dict(os.environ, {}, clear=False):
            if os.name != "nt":
                _set_windows_app_id()


if __name__ == "__main__":
    unittest.main()
