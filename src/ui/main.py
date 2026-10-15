"""Texpipe desktop application entry point.

Development:
    python -m src.ui.main

Frozen-build verification:
    Texpipe.exe --smoke-test
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Keep direct ``python src/ui/main.py`` execution useful during development.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if not getattr(sys, "frozen", False) and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app_info import (  # noqa: E402
    APP_DISPLAY_NAME,
    APP_ID,
    APP_NAME,
    APP_VERSION,
    ORGANIZATION_NAME,
)


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=f"{APP_DISPLAY_NAME} desktop application",
    )
    parser.add_argument(
        "--offscreen",
        action="store_true",
        help="use Qt's offscreen backend (for automated checks)",
    )
    parser.add_argument(
        "--smoke",
        "--smoke-test",
        dest="smoke_test",
        action="store_true",
        help="initialize the bundled GUI and image codecs, then exit",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {APP_VERSION}",
    )
    return parser


def _set_windows_app_id() -> None:
    """Give taskbar shortcuts a stable identity without requiring Windows."""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        # This is cosmetic and must never prevent startup (for example on Wine).
        pass


def _verify_bundled_codecs() -> None:
    """Import modules loaded lazily by the image readers and writers."""
    import OpenEXR  # noqa: F401
    import png  # noqa: F401
    import tifffile  # noqa: F401


def _run_smoke(app) -> int:
    """Construct the real main window and exercise every bundled codec."""
    import tempfile

    import numpy as np

    from src.core.output_spec import OutputSpec, SizePreset
    from src.io.loader import load_image
    from src.io.saver import save_image
    from src.ui.app import MainWindow
    from src.ui.preview_widget import PreviewWidget

    _verify_bundled_codecs()

    # Imports alone do not prove that native codec binaries can be loaded.
    # Perform tiny high-precision round trips in the system temp directory.
    with tempfile.TemporaryDirectory(prefix="texpipe-smoke-") as temp_dir:
        temp_root = Path(temp_dir)
        uint16_pixels = np.arange(64, dtype=np.uint16).reshape(8, 8) * 1024
        float_pixels = np.linspace(
            0.0, 2.0, 64, dtype=np.float32
        ).reshape(8, 8)
        for filename, pixels in (
            ("precision.png", uint16_pixels),
            ("precision.tiff", uint16_pixels),
            ("precision.exr", float_pixels),
        ):
            target = temp_root / filename
            save_image(pixels, target)
            restored = load_image(target)
            assert restored.shape == pixels.shape
            assert restored.dtype == pixels.dtype
            assert np.allclose(restored, pixels, rtol=1e-3, atol=1e-3)

    window = MainWindow()
    try:
        assert set(window.channel_grid.slot_widgets) == {"R", "G", "B", "A"}
        semantic_count = (
            window.channel_grid.slot_widgets["R"].semantic_combo.count()
        )
        assert semantic_count >= 14
        assert isinstance(window.preview, PreviewWidget)
        tab_titles = [
            window.tabs.tabText(index)
            for index in range(window.tabs.count())
        ]
        assert "Skybox Noise" in tab_titles

        spec = OutputSpec(size_preset=SizePreset.P1K)
        window.output_spec.set_spec(spec)
        assert window.channel_grid.get_spec().size_preset is SizePreset.P1K

        window.channel_grid._schedule_rebuild()
        window.channel_grid._debounce.stop()

        pixels = np.zeros((64, 64, 4), dtype=np.uint8)
        pixels[..., 0] = 255
        window.transcode_panel._src_arr = pixels
        window.transcode_panel._refresh()
        assert window.transcode_panel.src_fmt.count() >= 5
        assert window.transcode_panel.dst_fmt.count() >= 5

        # The frozen build deliberately treats numba as optional. Constructing
        # the plugin tab proves all dynamically discovered Skybox/node modules
        # were collected and the NumPy fallback remains available.
        skybox_index = tab_titles.index("Skybox Noise")
        skybox_widget = window.tabs.widget(skybox_index)
        assert skybox_widget is not None
        assert hasattr(skybox_widget, "node_graph")
        app.processEvents()
    finally:
        window.close()
        app.processEvents()
    return 0


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    args, qt_args = _build_argparser().parse_known_args(raw_args)

    if args.offscreen or args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    _set_windows_app_id()

    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication

    QCoreApplication.setOrganizationName(ORGANIZATION_NAME)
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(APP_VERSION)

    application_args = [sys.argv[0], *qt_args]
    app = QApplication.instance() or QApplication(application_args)

    from src.ui import i18n
    i18n.init()

    if args.smoke_test:
        return _run_smoke(app)

    from src.ui.app import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
