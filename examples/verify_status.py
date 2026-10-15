"""verify_status — 验证状态栏 StatusBanner + 各组件 status_message 信号流。

测试:
1. StatusBanner 能 show 4 个级别(成功/信息/警告/错误)+ 文字
2. StatusBanner.timeout 后自动清空
3. ChannelGridWidget 有 status_message 信号
4. SlotWidget 触发 status_message → ChannelGridWidget 转发
5. AdvancedEditorDialog 触发 status_message → SlotWidget 转发
6. MainWindow 接住所有 status_message → StatusBanner 显示
7. "导入后先编辑" 勾选存在
8. _load_rgba_from_path 在先编辑勾选时,正确走编辑流程
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from src.ui.status_banner import StatusBanner, LEVEL_STYLES  # noqa: E402
from src.ui.app import MainWindow  # noqa: E402
from src.ui.channel_grid import ChannelGridWidget  # noqa: E402
from src.ui.slot_widget import SlotWidget  # noqa: E402
from src.ui.advanced_editor import AdvancedEditorDialog  # noqa: E402


# ---------------------------------------------------------------------------
# Part 1: StatusBanner
# ---------------------------------------------------------------------------
def test_status_banner_levels():
    print("\n[1] StatusBanner 4 个级别 + 显示文字")
    banner = StatusBanner()
    for level in ("info", "success", "warning", "error"):
        banner.show_message(level, f"测试 {level}")
        assert banner._msg_lbl.text() == f"测试 {level}", f"文字不对: {banner._msg_lbl.text()}"
        assert banner._level_lbl.text() == LEVEL_STYLES[level][2], f"emoji 不对: {banner._level_lbl.text()}"
    print(f"  ✓ info/success/warning/error 都正确显示")


def test_status_banner_clear():
    print("\n[2] StatusBanner.clear() 后文字为空")
    banner = StatusBanner()
    banner.show_message("info", "hello")
    assert banner._msg_lbl.text() == "hello"
    banner.clear()
    assert banner._msg_lbl.text() == "", f"clear 后应空,实际 {banner._msg_lbl.text()!r}"
    print("  ✓ clear 后文字为空")


def test_status_banner_timeout():
    print("\n[3] StatusBanner 短 timeout 自动清空")
    banner = StatusBanner()
    banner.show_message("info", "短消息", timeout=100)
    assert banner._msg_lbl.text() == "短消息"
    # 等 timeout
    loop_done = {"flag": False}
    def done():
        loop_done["flag"] = True
    QTimer.singleShot(300, done)
    # 用 processEvents 推进
    end = QTimer()
    end.setSingleShot(True)
    end.timeout.connect(app.quit)
    end.start(350)
    app.exec()
    assert banner._msg_lbl.text() == "", f"timeout 后应清空,实际 {banner._msg_lbl.text()!r}"
    print("  ✓ 100ms timeout 后自动清空")


# ---------------------------------------------------------------------------
# Part 2: ChannelGrid + SlotWidget 信号流
# ---------------------------------------------------------------------------
def test_channel_grid_signal():
    print("\n[4] ChannelGridWidget 有 status_message 信号")
    grid = ChannelGridWidget()
    captured = {"last": None}
    grid.status_message.connect(lambda lvl, msg: captured.__setitem__("last", (lvl, msg)))
    # 模拟 _load_rgba_from_path 失败(给个不存在的路径)
    # 用 channel_grid 直接 emit
    grid.status_message.emit("warning", "测试消息")
    assert captured["last"] == ("warning", "测试消息")
    print(f"  ✓ emit 后信号传递: {captured['last']}")


def test_slot_to_grid_signal():
    print("\n[5] SlotWidget 触发 → ChannelGridWidget 转发")
    grid = ChannelGridWidget()
    captured = {"msgs": []}
    grid.status_message.connect(lambda lvl, msg: captured["msgs"].append((lvl, msg)))
    # 让 R 槽的 _on_export 在没数据时 emit warning
    r_slot = grid.slot_widgets["R"]
    r_slot._on_export()
    assert any("为空" in m[1] for m in captured["msgs"]), f"应收到 R 槽导出警告,实际 {captured['msgs']}"
    print(f"  ✓ SlotWidget._on_export 没数据 → grid.status_message 收到 {captured['msgs'][-1]}")


def test_advanced_to_slot_signal():
    print("\n[6] AdvancedEditorDialog 触发 → SlotWidget 转发")
    grid = ChannelGridWidget()
    captured = {"msgs": []}
    grid.status_message.connect(lambda lvl, msg: captured["msgs"].append((lvl, msg)))
    # 直接构造 AdvancedEditorDialog 并 emit
    base = np.full((32, 32), 100, dtype=np.uint8)
    dlg = AdvancedEditorDialog(initial=base, title="test")
    r_slot = grid.slot_widgets["R"]
    dlg.status_message.connect(r_slot.status_message)
    dlg.status_message.emit("info", "测试")
    assert any(m == ("info", "测试") for m in captured["msgs"]), f"应收到 info:测试,实际 {captured['msgs']}"
    print(f"  ✓ AdvancedEditorDialog → SlotWidget → ChannelGrid")


def test_edit_before_import_toggle():
    print("\n[7] '导入后先编辑' 勾选存在")
    grid = ChannelGridWidget()
    assert hasattr(grid, "edit_before_import_check")
    assert isinstance(grid.edit_before_import_check, type(grid._rgba_checks["R"]))
    assert grid.edit_before_import_check.isChecked() is False, "默认应未勾选"
    grid.edit_before_import_check.setChecked(True)
    assert grid.edit_before_import_check.isChecked()
    print(f"  ✓ checkbox 存在,默认未勾选,可切换")


def test_load_with_edit_toggle():
    print("\n[8] _load_rgba_from_path 勾选后,准备一张图不会崩")
    # 因为 offscreen 没法弹文件对话框,但 _load_rgba_from_path 接受 Path 直接传
    # 用一个临时 RGBA 文件,模拟流程到弹 advanced_editor
    grid = ChannelGridWidget()
    grid.show()
    app.processEvents()
    src = np.zeros((16, 16, 4), dtype=np.uint8)
    src[..., 0] = 200
    src[..., 1] = 100
    src[..., 2] = 50
    src_p = ROOT / "examples" / "out_status" / "test_rgba.png"
    src_p.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(src, mode="RGBA").save(src_p)
    # 模拟"勾选先编辑" + 加载
    # 由于 dlg.exec() 会阻塞,改用 patch 让它自动 accept
    from src.ui import advanced_editor as ae_mod
    original_dialog = ae_mod.AdvancedEditorDialog
    class FakeDialog:
        def __init__(self, *args, **kwargs):
            self.result_data = np.full((16, 16), 128, dtype=np.uint8)
        def exec(self):
            return 1  # Accepted
    ae_mod.AdvancedEditorDialog = FakeDialog
    captured = {"msgs": []}
    grid.status_message.connect(lambda lvl, msg: captured["msgs"].append((lvl, msg)))
    try:
        grid.edit_before_import_check.setChecked(True)
        grid._load_rgba_from_path(src_p)
        app.processEvents()
        # 应有 "打开复杂编辑窗口" info 和 "预先编辑完成" success
        msgs_text = [m[1] for m in captured["msgs"]]
        assert any("打开复杂编辑窗口" in m for m in msgs_text), f"应有 '打开复杂编辑窗口' 消息,实际 {msgs_text}"
        assert any("预先编辑完成" in m for m in msgs_text), f"应有 '预先编辑完成' 消息,实际 {msgs_text}"
        # 4 槽都应有数据
        m = grid.get_map()
        for ch in ("R", "G", "B", "A"):
            assert getattr(m, ch).data is not None, f"{ch} 槽应有数据"
    finally:
        ae_mod.AdvancedEditorDialog = original_dialog
    print(f"  ✓ 先编辑流程跑通,4 槽都载入")


# ---------------------------------------------------------------------------
# Part 3: MainWindow 集成
# ---------------------------------------------------------------------------
def test_main_window_integration():
    print("\n[9] MainWindow 集成 status_message → StatusBanner")
    w = MainWindow()
    w.show()
    app.processEvents()
    assert hasattr(w, "_status_banner"), "应有 _status_banner"
    assert hasattr(w, "show_status"), "应有 show_status 方法"
    # 触发 channel_grid 的 status_message → main 转发到 banner
    w.channel_grid.status_message.emit("info", "集成测试消息")
    app.processEvents()
    assert w._status_banner._msg_lbl.text() == "集成测试消息", \
        f"banner 应显示 '集成测试消息',实际 {w._status_banner._msg_lbl.text()!r}"
    print(f"  ✓ MainWindow 收到 channel_grid 消息并显示在 banner: {w._status_banner._msg_lbl.text()!r}")


def test_main_window_show_status():
    print("\n[10] MainWindow.show_status() 4 个级别")
    w = MainWindow()
    for level in ("info", "success", "warning", "error"):
        w.show_status(level, f"级别 {level}")
        assert w._status_banner._msg_lbl.text() == f"级别 {level}"
        assert w._status_banner._level_lbl.text() == LEVEL_STYLES[level][2]
    print("  ✓ 4 个级别都正确显示")


if __name__ == "__main__":
    try:
        test_status_banner_levels()
        test_status_banner_clear()
        test_status_banner_timeout()
        test_channel_grid_signal()
        test_slot_to_grid_signal()
        test_advanced_to_slot_signal()
        test_edit_before_import_toggle()
        test_load_with_edit_toggle()
        test_main_window_integration()
        test_main_window_show_status()
        print("\n[OK] 状态栏 + 预先编辑 所有测试通过 ✓")
        raise SystemExit(0)
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
