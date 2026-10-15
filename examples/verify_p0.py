"""verify_p0 — 验证所有 P0 修复:

P0-1: advanced_editor 保留彩色 H×W×3 输入 + 输出
P0-2: channel_grid FILE 缓存 (path+mtime+token+size)
P0-3: SlotWidget 槽边框 + 标题色(R/G/B/A 各色)
P0-4: 预览图点击放大(4 通道 + RGBA)
P0-5: set_map 区分 new_baseline(工作区加载清 undo,导入不清)
"""
from __future__ import annotations

import os
import sys
import time
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

from PySide6.QtCore import QPointF, QEvent, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from src.core.file_cache import FileCache  # noqa: E402
from src.core.map import ChannelMap  # noqa: E402
from src.core.output_spec import OutputSpec, SizePreset  # noqa: E402
from src.core.slot import ChannelSlot, ChannelToken, SourceType  # noqa: E402
from src.io.loader import load_slot  # noqa: E402
from src.ui.advanced_editor import AdvancedEditorDialog  # noqa: E402
from src.ui.app import MainWindow  # noqa: E402
from src.ui.channel_grid import ChannelGridWidget  # noqa: E402
from src.ui.preview_widget import ImageViewDialog  # noqa: E402
from src.ui.slot_widget import SlotWidget  # noqa: E402


# ===========================================================================
# P0-1: advanced_editor 保留彩色
# ===========================================================================
def test_p0_1_color_preserved():
    print("\n[P0-1] advanced_editor 接受 H×W×3 输入,输出 H×W×3(保留彩色)")
    # 1) 灰度输入 → 灰度输出
    gray = np.full((32, 32), 100, dtype=np.uint8)
    dlg = AdvancedEditorDialog(initial=gray)
    assert dlg._original.ndim == 2, f"灰度输入应保留 H×W,实际 ndim={dlg._original.ndim}"
    assert not dlg._is_color
    out = dlg._current_computed()
    assert out.ndim == 2, f"灰度输出应是 H×W,实际 ndim={out.ndim}"
    print(f"  ✓ 灰度输入 → 灰度输出 (shape={out.shape})")

    # 2) RGB 输入 → RGB 输出
    rgb = np.zeros((32, 32, 3), dtype=np.uint8)
    rgb[..., 0] = 200  # R
    rgb[..., 1] = 100  # G
    rgb[..., 2] = 50   # B
    dlg2 = AdvancedEditorDialog(initial=rgb)
    assert dlg2._original.ndim == 3, f"RGB 输入应保留 H×W×3,实际 ndim={dlg2._original.ndim}"
    assert dlg2._is_color
    out2 = dlg2._current_computed()
    assert out2.ndim == 3, f"RGB 输出应是 H×W×3,实际 ndim={out2.ndim}"
    assert out2.shape == (32, 32, 3), f"shape 应是 (32,32,3),实际 {out2.shape}"
    print(f"  ✓ RGB 输入 → RGB 输出 (shape={out2.shape})")

    # 3) RGBA 输入 → RGB 输出(A 被丢)
    rgba = np.zeros((16, 16, 4), dtype=np.uint8)
    rgba[..., 0] = 200
    rgba[..., 1] = 100
    rgba[..., 2] = 50
    rgba[..., 3] = 255
    dlg3 = AdvancedEditorDialog(initial=rgba)
    assert dlg3._is_color
    assert dlg3._original.shape == (16, 16, 3), f"RGBA 应丢 A,实际 shape={dlg3._original.shape}"
    print(f"  ✓ RGBA 输入 → RGB 输出(A 通道被丢,shape={dlg3._original.shape})")

    # 4) 彩色模式下,亮度调整作用到 3 通道
    dlg2._bright_slider.setValue(50)
    out3 = dlg2._current_computed()
    # R 通道基线 200 + 50 = 250(钳到 255);G 100+50=150;B 50+50=100
    assert 240 < out3[0, 0, 0] <= 255, f"R 应被提亮到 ~250,实际 {out3[0, 0, 0]}"
    assert 140 < out3[0, 0, 1] <= 160, f"G 应到 ~150,实际 {out3[0, 0, 1]}"
    assert 90 < out3[0, 0, 2] <= 110, f"B 应到 ~100,实际 {out3[0, 0, 2]}"
    print(f"  ✓ 彩色模式亮度 +50 作用到 3 通道:R={out3[0,0,0]} G={out3[0,0,1]} B={out3[0,0,2]}")

    # 5) 饱和度调整(只对 H×W×3 生效)
    dlg2._bright_slider.setValue(0)
    dlg2._saturation_slider.setValue(0)  # 0 = 灰
    out4 = dlg2._current_computed()
    # 灰度化:所有通道 = (200+100+50)/3 = 116
    expected_gray = int(0.299 * 200 + 0.587 * 100 + 0.114 * 50)
    for ch in range(3):
        diff = abs(int(out4[0, 0, ch]) - expected_gray)
        assert diff < 5, f"饱和度 0 后通道 {ch} 应接近灰度 {expected_gray},实际 {out4[0, 0, ch]}"
    print(f"  ✓ 饱和度 0 → 3 通道接近灰度(≈{expected_gray})")


# ===========================================================================
# P0-2: FILE 缓存
# ===========================================================================
def test_p0_2_file_cache():
    print("\n[P0-2] FileCache + load_slot 缓存命中")
    # 准备 3 张测试图(用绝对路径,确保 mtime 可读)
    src_dir = ROOT / "examples" / "out_p0"
    src_dir.mkdir(parents=True, exist_ok=True)
    arr = np.full((16, 16, 3), 200, dtype=np.uint8)
    p_a = src_dir / "a.png"
    p_b = src_dir / "b.png"
    p_c = src_dir / "c.png"
    Image.fromarray(arr, mode="RGB").save(p_a)
    Image.fromarray(arr, mode="RGB").save(p_b)
    Image.fromarray(arr, mode="RGB").save(p_c)

    # 1) 基础缓存:put/get 命中(用绝对路径)
    cache = FileCache(max_size=4)
    cache.put(str(p_a), "R", 8, 8, arr)
    got = cache.get(str(p_a), "R", 8, 8)
    assert got is not None, f"应命中,但 got={got}"
    assert np.array_equal(got, arr)
    assert cache.stats()["hits"] == 1
    print(f"  ✓ 缓存命中: hits=1, misses=0")

    # 2) 容量限制
    cache2 = FileCache(max_size=2)
    cache2.put(str(p_a), "R", 8, 8, arr)
    cache2.put(str(p_b), "R", 8, 8, arr)
    cache2.put(str(p_c), "R", 8, 8, arr)  # 触发 LRU 淘汰
    assert cache2.stats()["size"] == 2, f"应限制 2 项,实际 {cache2.stats()['size']}"
    assert cache2.get(str(p_a), "R", 8, 8) is None, "最久的应被淘汰"
    assert cache2.get(str(p_c), "R", 8, 8) is not None, "最近应保留"
    print(f"  ✓ LRU 容量限制: 写 3 项只保留 2 项")

    # 3) 端到端:load_slot 走 cache
    # 准备一张测试图
    src = np.full((16, 16, 3), 200, dtype=np.uint8)
    src_p = ROOT / "examples" / "out_p0" / "test_cache.png"
    src_p.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(src, mode="RGB").save(src_p)
    spec = OutputSpec(size_preset=SizePreset.P1K, width=16, height=16)

    cache3 = FileCache(max_size=8)
    slot = ChannelSlot(source_type=SourceType.FILE, file_path=src_p, token=ChannelToken.R)
    # 第一次加载:miss
    load_slot(slot, spec, file_cache=cache3)
    assert cache3.stats()["misses"] == 1
    print(f"  ✓ 第一次加载: misses=1")

    # 第二次加载(同 token,同 size):hit
    slot2 = ChannelSlot(source_type=SourceType.FILE, file_path=src_p, token=ChannelToken.R)
    load_slot(slot2, spec, file_cache=cache3)
    assert cache3.stats()["hits"] == 1, f"应命中 1 次,实际 {cache3.stats()['hits']}"
    assert np.array_equal(slot.data, slot2.data), "缓存命中后应给同样数据"
    print(f"  ✓ 第二次加载: hits=1, 数据一致")

    # 4) 不同 token 不会命中
    slot3 = ChannelSlot(source_type=SourceType.FILE, file_path=src_p, token=ChannelToken.G)
    load_slot(slot3, spec, file_cache=cache3)
    assert cache3.stats()["misses"] == 2, f"不同 token 应 miss,实际 {cache3.stats()['misses']}"
    print(f"  ✓ 不同 token → miss (G 通道)")

    # 5) 文件 mtime 变化 → 失效
    time.sleep(1.1)  # mtime 精度(Windows FAT/NTFS 通常 1 秒以上)
    Image.fromarray(src, mode="RGB").save(src_p)  # 覆盖写
    slot4 = ChannelSlot(source_type=SourceType.FILE, file_path=src_p, token=ChannelToken.R)
    load_slot(slot4, spec, file_cache=cache3)
    assert cache3.stats()["misses"] == 3, f"mtime 变化应 miss,实际 {cache3.stats()['misses']}"
    print(f"  ✓ 文件 mtime 变化 → 缓存失效")

    # 清理
    try:
        src_p.unlink()
        src_p.parent.rmdir()
    except OSError:
        pass


# ===========================================================================
# P0-3: SlotWidget 槽边框 + 标题色
# ===========================================================================
def test_p0_3_slot_color():
    print("\n[P0-3] SlotWidget 槽边框 + 标题色(R/G/B/A 各色)")
    expected_colors = {
        "R": "#ff5252",  # 红
        "G": "#4caf50",  # 绿
        "B": "#448aff",  # 蓝
        "A": "#ab47bc",  # 紫
    }
    for name, exp_color in expected_colors.items():
        sw = SlotWidget(name)
        # 检查标题颜色
        style = sw.title_label.styleSheet()
        assert exp_color in style, f"{name} 槽标题色应含 {exp_color},实际: {style}"
        # 检查边框色
        sw_style = sw.styleSheet()
        assert exp_color in sw_style, f"{name} 槽边框应含 {exp_color},实际: {sw_style}"
        print(f"  ✓ {name} 槽: 标题色={exp_color}, 边框色={exp_color}")


# ===========================================================================
# P0-4: 预览图点击放大
# ===========================================================================
def test_p0_4_preview_click():
    print("\n[P0-4] 预览图点击 → 弹 ImageViewDialog")
    w = MainWindow()
    w.show()
    app.processEvents()
    # 后面会临时 mock ImageViewDialog 为 __new__ 实例(没跑 __init__)
    # 跑完测试后,Python teardown 可能延迟触发信号,届时再调 dlg.exec() 会炸
    # 记下 signal 连接,测试结束前 disconnect
    _pvw = __import__("src.ui.preview_widget", fromlist=["PreviewWidget"])
    _pw = w.preview
    # _ChannelPreview.clicked → _pw._on_preview_clicked
    _conn = _pw._on_preview_clicked  # 保留引用,等下用 try/finally 断开

    # 模拟有数据后,点 4 通道其中一个缩略图
    arr = np.full((32, 32), 100, dtype=np.uint8)
    w.preview.previews["R"].set_array(arr)
    w.preview.previews["R"].set_title("R: roughness")

    # 拦截 dialog 弹出:用 mock 直接调 _on_preview_clicked,验证它创建了 dialog
    # 但 dialog.exec() 会阻塞,改为检查 _arr 和 _title
    # 用真正的 ImageViewDialog.__init__ 来初始化,避免 __new__ 跳过 __init__ 导致 teardown 时炸
    captured = {"arr": None, "title": None}
    def mock_dialog(arr_in, title, parent=None):
        captured["arr"] = arr_in
        captured["title"] = title
        d = ImageViewDialog.__new__(ImageViewDialog)
        ImageViewDialog.__init__(d, arr_in, title=title, parent=parent)
        # 把 exec 替换成 no-op,避免阻塞
        d.exec = lambda: 0
        return d
    import src.ui.preview_widget as pvw
    original = pvw.ImageViewDialog
    pvw.ImageViewDialog = mock_dialog
    try:
        # 模拟鼠标点击 R 槽缩略图
        w.preview.previews["R"]._on_click_simulate()
        assert captured["arr"] is not None, "点击应触发 _on_preview_clicked"
        assert np.array_equal(captured["arr"], arr), "传递的 arr 应一致"
        assert "R" in captured["title"], f"title 应含 'R',实际 {captured['title']}"
        print(f"  ✓ 点击 R 缩略图触发 dialog(arr 正确, title='{captured['title']}')")
    finally:
        pvw.ImageViewDialog = original

    # 验证 ImageViewDialog 自己能正常工作(不实际 exec)
    arr2 = np.full((64, 64, 3), 200, dtype=np.uint8)
    dlg = ImageViewDialog(arr2, title="test")
    assert dlg.windowTitle() == "test"
    print(f"  ✓ ImageViewDialog 可正常创建并显示 title")


def _on_click_simulate(self):
    """模拟点击 _ChannelPreview(用 _arr 和 _title 模拟)."""
    self.clicked.emit(self._arr, self._title)


# 给 _ChannelPreview 加这个测试用方法(monkey patch)
from src.ui.preview_widget import _ChannelPreview
_ChannelPreview._on_click_simulate = _on_click_simulate


# ===========================================================================
# P0-5: set_map new_baseline
# ===========================================================================
def test_p0_5_set_map_baseline():
    print("\n[P0-5] set_map 区分 new_baseline(工作区加载清 undo,导入不清)")
    grid = ChannelGridWidget()

    # 1) 模拟有 undo 历史
    grid._undo_stack.append({"old": 1})
    grid._last_snapshot = {"current": 1}
    assert grid.can_undo()
    print(f"  ✓ 初始有 undo 历史: undo_stack={len(grid._undo_stack)}")

    # 2) 模拟"导入图" (new_baseline=False):用 _in_undo_redo 让 _on_rebuild 不推 undo
    #    然后看 set_map 末尾的 new_baseline 行为
    grid._undo_stack.append({"another": 2})
    n_before = len(grid._undo_stack)
    grid._in_undo_redo = True  # _on_rebuild 只更新 _last_snapshot,不 push
    grid.set_map(ChannelMap(), new_baseline=False)
    grid._in_undo_redo = False
    n_after = len(grid._undo_stack)
    assert n_after == n_before, f"导入图应保留 undo,before={n_before} after={n_after}"
    print(f"  ✓ set_map(new_baseline=False) 保留 undo_stack={n_before} → {n_after}")

    # 3) 模拟"加载工作区" (new_baseline=True):清 undo
    grid._in_undo_redo = True
    grid.set_map(ChannelMap(), new_baseline=True)
    grid._in_undo_redo = False
    assert len(grid._undo_stack) == 0, f"加载工作区应清 undo,实际 {len(grid._undo_stack)}"
    print(f"  ✓ set_map(new_baseline=True) 清空 undo_stack")

    # 4) 默认参数(向后兼容):默认 True(清 undo)
    grid._undo_stack.append({"x": 1})
    grid._in_undo_redo = True
    grid.set_map(ChannelMap())  # 默认 new_baseline=True
    grid._in_undo_redo = False
    assert len(grid._undo_stack) == 0, "默认应是 True(清 undo),实际保留"
    print(f"  ✓ 默认参数(向后兼容)行为正确")

    # 5) 实际场景:加载工作区应传 new_baseline=True(直接走 load_workspace_path,
    #    或 _on_load_workspace 内部直接调 set_map 时传 True)
    import inspect
    src_load = inspect.getsource(grid._on_load_workspace)
    src_path = inspect.getsource(grid.load_workspace_path)
    assert (
        "new_baseline=True" in src_load or "new_baseline=True" in src_path
    ), "加载工作区路径中没传 new_baseline=True"
    print(f"  ✓ 加载工作区会传 new_baseline=True(通过 _on_load_workspace → load_workspace_path)")

    src2 = inspect.getsource(grid._load_rgba_from_path)
    assert "new_baseline=False" in src2, "_load_rgba_from_path 没传 new_baseline=False"
    print(f"  ✓ _load_rgba_from_path 传 new_baseline=False")


# ===========================================================================
# 跑
# ===========================================================================
if __name__ == "__main__":
    try:
        test_p0_1_color_preserved()
        test_p0_2_file_cache()
        test_p0_3_slot_color()
        test_p0_4_preview_click()
        test_p0_5_set_map_baseline()
        print("\n[OK] 所有 P0 修复测试通过 ✓")
        raise SystemExit(0)
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
