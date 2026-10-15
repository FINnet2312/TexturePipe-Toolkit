# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for both the recommended folder build and one-file build.

Set TEXPIPE_BUNDLE_MODE=onefile to produce dist/Texpipe.exe.
The default produces dist/Texpipe/Texpipe.exe.
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_root = Path(SPECPATH).resolve()
bundle_mode = os.environ.get("TEXPIPE_BUNDLE_MODE", "onedir").strip().lower()
if bundle_mode not in {"onedir", "onefile"}:
    raise ValueError(
        "TEXPIPE_BUNDLE_MODE must be either 'onedir' or 'onefile'"
    )

# The editor and high-precision codecs are imported only when their feature is
# used. Listing them here keeps packaging independent of import-analysis details.
hidden_imports = [
    "OpenEXR",
    "Imath",
    "png",
    "tifffile",
    "src.ui.advanced_editor",
    "src.ui.advanced_editor_dialog",
    "src.ui.advanced_editor_components.adjustments",
    "src.ui.advanced_editor_components.blend_modes",
    "src.ui.advanced_editor_components.curves",
    "src.ui.advanced_editor_components.mapping",
    "src.ui.advanced_editor_components.preview",
] + collect_submodules("src.ui.skybox_noise")

analysis = Analysis(
    [str(project_root / "src" / "ui" / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # These optional packages can be present in a developer's global
    # environment but are not used by Texpipe. Excluding them keeps builds
    # reproducible and avoids silently bundling Tcl/Tk or XML tooling.
    # The release build uses the maintained NumPy implementation. Keeping
    # numba out makes the EXE deterministic and avoids shipping LLVM solely as
    # an optional accelerator; source installs may still use numba when present.
    excludes=[
        "tkinter",
        "_tkinter",
        "lxml",
        "charset_normalizer",
        "numba",
    ],
    noarchive=False,
    optimize=0,
)
python_archive = PYZ(analysis.pure)

common_exe_options = {
    "name": "Texpipe",
    "debug": False,
    "bootloader_ignore_signals": False,
    "strip": False,
    "upx": False,
    "console": False,
    "disable_windowed_traceback": False,
    "argv_emulation": False,
    "target_arch": None,
    "codesign_identity": None,
    "entitlements_file": None,
    "version": str(project_root / "packaging" / "windows_version_info.txt"),
}

if bundle_mode == "onefile":
    executable = EXE(
        python_archive,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        **common_exe_options,
    )
else:
    executable = EXE(
        python_archive,
        analysis.scripts,
        [],
        exclude_binaries=True,
        **common_exe_options,
    )
    bundle = COLLECT(
        executable,
        analysis.binaries,
        analysis.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="Texpipe",
    )
