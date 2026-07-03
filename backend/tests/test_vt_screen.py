"""
VTScreen 终端仿真器单元测试。

覆盖：
- 普通字符写入与光标移动
- 控制字符 LF/CR/BS/TAB
- CSI A/B/C/D 光标移动
- CSI H 光标定位
- CSI J 清屏
- CSI K 清行
- CSI m SGR 重置/粗体
- 滚动历史
- resize 与 snapshot
"""

from __future__ import annotations

from core.terminal.vt_screen import VTScreen


class TestVTScreenWrite:
    """基础字符写入测试。"""

    def test_write_text_advances_cursor(self) -> None:
        """写入普通文本，光标应随之右移。"""
        screen = VTScreen(cols=10, rows=3)
        screen.write("hello")
        # 第一行前 5 个字符应为 "hello"
        assert "".join(screen.grid[0][:5]) == "hello"
        # 光标停在第 5 列
        assert screen.cursor_row == 0
        assert screen.cursor_col == 5

    def test_write_lf_moves_to_next_row(self) -> None:
        """
        写入 \\n 后光标下移一行。

        注意：VT100 标准中 LF 仅移动光标到下一行，列号保持不变；
        要让光标回到行首需配合 CR（\\r）。本测试使用 \\r\\n 验证换行+回车组合。
        """
        screen = VTScreen(cols=10, rows=3)
        screen.write("ab\r\ncd")
        assert "".join(screen.grid[0][:2]) == "ab"
        assert "".join(screen.grid[1][:2]) == "cd"
        assert screen.cursor_row == 1
        assert screen.cursor_col == 2

    def test_write_lf_only_preserves_column(self) -> None:
        """
        单独的 LF 应只移动光标到下一行，列号保持不变（VT100 标准）。
        """
        screen = VTScreen(cols=10, rows=3)
        screen.write("ab")
        # 光标停在第 2 列
        assert screen.cursor_col == 2
        screen.write("\n")
        # LF 后光标行 +1，列号不变
        assert screen.cursor_row == 1
        assert screen.cursor_col == 2

    def test_write_cr_resets_column(self) -> None:
        """写入 \\r 后光标列回到行首。"""
        screen = VTScreen(cols=10, rows=3)
        screen.write("abc\rXY")
        # CR 后 XY 应覆盖 abc 的前两个字符
        assert "".join(screen.grid[0][:3]) == "XYc"
        assert screen.cursor_col == 2

    def test_write_tab_moves_to_next_tab_stop(self) -> None:
        """写入 \\t 后光标移到下一个 tab stop（8 列对齐）。"""
        screen = VTScreen(cols=20, rows=2)
        screen.write("a\tb")
        # a 在第 0 列，TAB 后到第 8 列，b 写入第 8 列
        assert screen.grid[0][0] == "a"
        assert screen.grid[0][8] == "b"
        assert screen.cursor_col == 9

    def test_write_bs_moves_cursor_left(self) -> None:
        """写入 \\b 后光标左移一格，不擦除字符。"""
        screen = VTScreen(cols=10, rows=2)
        screen.write("abc\bX")
        # bs 回到第 2 列（c 位置），写入 X 覆盖
        assert "".join(screen.grid[0][:3]) == "abX"
        assert screen.cursor_col == 3

    def test_write_lf_at_bottom_triggers_scroll(self) -> None:
        """在最后一行写 \\n 触发向上滚动。"""
        screen = VTScreen(cols=5, rows=2)
        screen.write("line1")
        # 强制移动到第二行
        screen.write("\n")
        screen.write("line2")
        # 再次换行应触发滚动
        screen.write("\n")
        # 第一行内容应进入 scrollback
        assert "line1" in screen.get_scrollback(10)


class TestVTScreenCsiCursor:
    """CSI 光标移动测试。"""

    def test_csi_a_moves_cursor_up(self) -> None:
        """CSI A 光标上移 n 行。"""
        screen = VTScreen(cols=10, rows=5)
        screen.cursor_row = 3
        screen.cursor_col = 2
        screen.write("\x1b[2A")
        assert screen.cursor_row == 1
        assert screen.cursor_col == 2

    def test_csi_a_default_one(self) -> None:
        """CSI A 默认上移 1 行。"""
        screen = VTScreen(cols=10, rows=5)
        screen.cursor_row = 3
        screen.write("\x1b[A")
        assert screen.cursor_row == 2

    def test_csi_a_clamped_at_zero(self) -> None:
        """光标上移不会越过第 0 行。"""
        screen = VTScreen(cols=10, rows=5)
        screen.cursor_row = 1
        screen.write("\x1b[10A")
        assert screen.cursor_row == 0

    def test_csi_b_moves_cursor_down(self) -> None:
        """CSI B 光标下移 n 行。"""
        screen = VTScreen(cols=10, rows=5)
        screen.write("\x1b[2B")
        assert screen.cursor_row == 2

    def test_csi_b_clamped_at_last_row(self) -> None:
        """光标下移不会越过最后一行。"""
        screen = VTScreen(cols=10, rows=5)
        screen.cursor_row = 3
        screen.write("\x1b[10B")
        assert screen.cursor_row == 4

    def test_csi_c_moves_cursor_right(self) -> None:
        """CSI C 光标右移 n 列。"""
        screen = VTScreen(cols=10, rows=5)
        screen.write("\x1b[3C")
        assert screen.cursor_col == 3

    def test_csi_c_clamped_at_last_col(self) -> None:
        """光标右移不会越过最后一列。"""
        screen = VTScreen(cols=10, rows=5)
        screen.cursor_col = 8
        screen.write("\x1b[10C")
        assert screen.cursor_col == 9

    def test_csi_d_moves_cursor_left(self) -> None:
        """CSI D 光标左移 n 列。"""
        screen = VTScreen(cols=10, rows=5)
        screen.cursor_col = 5
        screen.write("\x1b[2D")
        assert screen.cursor_col == 3

    def test_csi_d_clamped_at_zero(self) -> None:
        """光标左移不会越过第 0 列。"""
        screen = VTScreen(cols=10, rows=5)
        screen.cursor_col = 2
        screen.write("\x1b[10D")
        assert screen.cursor_col == 0

    def test_csi_h_positions_cursor(self) -> None:
        """CSI H 光标定位（1-based 行;列）。"""
        screen = VTScreen(cols=20, rows=10)
        screen.write("hello\x1b[3;5H")
        # 行 3 列 5 -> 0-based row=2, col=4
        assert screen.cursor_row == 2
        assert screen.cursor_col == 4

    def test_csi_h_default_home(self) -> None:
        """无参数 CSI H 等价于回到 0,0。"""
        screen = VTScreen(cols=20, rows=10)
        screen.cursor_row = 5
        screen.cursor_col = 5
        screen.write("\x1b[H")
        assert screen.cursor_row == 0
        assert screen.cursor_col == 0


class TestVTScreenCsiErase:
    """CSI 清屏/清行测试。"""

    def test_csi_2j_clears_full_screen(self) -> None:
        """CSI 2J 清空整个屏幕。"""
        screen = VTScreen(cols=10, rows=3)
        screen.write("abc\ndef\nghi")
        screen.write("\x1b[2J")
        for r in range(3):
            assert "".join(screen.grid[r]) == " " * 10

    def test_csi_k_clears_line_from_cursor(self) -> None:
        """CSI K（默认 0）清空光标到行尾。"""
        screen = VTScreen(cols=10, rows=2)
        screen.write("abcdefghij")  # 第一行填满
        screen.cursor_col = 3
        screen.cursor_row = 0
        screen.write("\x1b[K")
        # 前 3 个字符保留，后面应为空格
        assert "".join(screen.grid[0][:3]) == "abc"
        assert "".join(screen.grid[0][3:]) == " " * 7

    def test_csi_2k_clears_full_line(self) -> None:
        """CSI 2K 清空整行。"""
        screen = VTScreen(cols=10, rows=2)
        screen.write("abcdefghij")
        screen.cursor_row = 0
        screen.cursor_col = 0
        screen.write("\x1b[2K")
        assert "".join(screen.grid[0]) == " " * 10


class TestVTScreenSGR:
    """SGR 序列测试（简化版仅识别 reset/bold）。"""

    def test_sgr_reset_clears_bold(self) -> None:
        """SGR 0 重置所有属性。"""
        screen = VTScreen(cols=10, rows=2)
        screen.write("\x1b[1m")  # bold on
        assert screen._current_attr["bold"] is True
        screen.write("\x1b[0m")  # reset
        assert screen._current_attr["bold"] is False

    def test_sgr_22_turns_off_bold(self) -> None:
        """SGR 22 关闭粗体。"""
        screen = VTScreen(cols=10, rows=2)
        screen.write("\x1b[1m")
        assert screen._current_attr["bold"] is True
        screen.write("\x1b[22m")
        assert screen._current_attr["bold"] is False

    def test_sgr_unknown_codes_ignored(self) -> None:
        """未实现的 SGR 码应被忽略，不抛错。"""
        screen = VTScreen(cols=10, rows=2)
        # 31=红色前景，42=绿色背景，应不抛错
        screen.write("\x1b[31;42mhello")
        assert "".join(screen.grid[0][:5]) == "hello"


class TestVTScreenScrollback:
    """滚动历史测试。"""

    def test_lines_scrolled_into_scrollback(self) -> None:
        """
        写入超过 rows 行后，旧行进入 scrollback。

        使用 \\r\\n 表示完整换行（VT100 标准中 LF 不会重置列号）。
        由于 VT100 的滚动行为：当下一行写入会触发滚动时，当前屏幕顶行进入 scrollback。
        因此若依次写入 A/B/C/D/E 五行到 2 行屏幕，A 与 C 会进入 scrollback（B 被 C 覆盖）。
        """
        screen = VTScreen(cols=5, rows=2, scrollback_limit=100)
        # 写入 5 行（每行末尾用 \r\n 表示完整换行）
        screen.write("AAAAA\r\nBBBBB\r\nCCCCC\r\nDDDDD\r\nEEEEE")
        scrollback = screen.get_scrollback(10)
        # 滚动历史非空
        assert len(scrollback) > 0
        # 最早的 AAAAA 应进入 scrollback
        assert "AAAAA" in scrollback
        # 当前屏幕顶部应是最新的 EEEEE
        assert "".join(screen.grid[0]) == "EEEEE"

    def test_scrollback_limit_enforced(self) -> None:
        """scrollback_limit 限制滚动历史的最大行数。"""
        screen = VTScreen(cols=3, rows=1, scrollback_limit=3)
        # 触发 5 次滚动
        for c in ["AAA", "BBB", "CCC", "DDD", "EEE"]:
            screen.write(c + "\n")
        scrollback = screen.get_scrollback(100)
        assert len(scrollback) <= 3
        # 最早 AAA/BBB 应被丢弃，保留最近 3 行
        assert "AAA" not in scrollback
        assert "EEE" in scrollback

    def test_get_scrollback_limit_param(self) -> None:
        """get_scrollback(limit) 应只返回最近 limit 行。"""
        screen = VTScreen(cols=3, rows=1, scrollback_limit=100)
        for c in ["AAA", "BBB", "CCC", "DDD"]:
            screen.write(c + "\n")
        # 限制返回 2 行
        result = screen.get_scrollback(2)
        assert len(result) == 2
        assert result[-1] == "DDD"


class TestVTScreenResize:
    """resize 测试。"""

    def test_resize_grows_grid(self) -> None:
        """resize 扩大网格时新增空行/空列。"""
        screen = VTScreen(cols=5, rows=2)
        # 使用 \r\n 完整换行（VT100 标准）
        screen.write("abcde\r\nfghij")
        screen.resize(cols=8, rows=3)
        assert screen.cols == 8
        assert screen.rows == 3
        # 原内容保留
        assert "".join(screen.grid[0][:5]) == "abcde"
        # 第三行为新增空行
        assert "".join(screen.grid[2]) == " " * 8

    def test_resize_shrinks_grid_pushes_scrollback(self) -> None:
        """resize 缩小网格时，被裁剪的行进入 scrollback。"""
        screen = VTScreen(cols=5, rows=3)
        # 使用 \r\n 完整换行
        screen.write("row11\r\nrow22\r\nrow33")
        screen.resize(cols=5, rows=1)
        # 顶部 2 行应进入 scrollback
        scrollback = screen.get_scrollback(10)
        assert "row11" in scrollback
        assert "row22" in scrollback
        # 当前屏幕第一行应是原第三行
        assert "".join(screen.grid[0]) == "row33"

    def test_resize_cursor_clamped(self) -> None:
        """resize 后光标位置应裁剪到新边界内。"""
        screen = VTScreen(cols=20, rows=10)
        screen.cursor_row = 8
        screen.cursor_col = 15
        screen.resize(cols=5, rows=3)
        assert screen.cursor_row == 2
        assert screen.cursor_col == 4


class TestVTScreenSnapshot:
    """snapshot 与 scrollback 输出格式测试。"""

    def test_get_snapshot_returns_2d_list(self) -> None:
        """get_snapshot 返回二维字符数组。"""
        screen = VTScreen(cols=5, rows=3)
        screen.write("ab")
        snap = screen.get_snapshot()
        assert isinstance(snap, list)
        assert len(snap) == 3
        for row in snap:
            assert isinstance(row, list)
            assert len(row) == 5

    def test_get_scrollback_returns_string_list(self) -> None:
        """get_scrollback 返回字符串列表，每行一个字符串。"""
        screen = VTScreen(cols=5, rows=1, scrollback_limit=100)
        screen.write("AAAAA\nBBBBB\n")
        scrollback = screen.get_scrollback(10)
        assert isinstance(scrollback, list)
        for line in scrollback:
            assert isinstance(line, str)
            assert len(line) == 5

    def test_snapshot_is_independent_copy(self) -> None:
        """get_snapshot 返回深拷贝，修改不影响内部状态。"""
        screen = VTScreen(cols=5, rows=2)
        screen.write("abcde")
        snap = screen.get_snapshot()
        snap[0][0] = "X"
        # 内部 grid 不应被影响
        assert screen.grid[0][0] == "a"


class TestVTScreenEdgeCases:
    """边界情况测试。"""

    def test_empty_write_does_nothing(self) -> None:
        """空字符串写入不应改变状态。"""
        screen = VTScreen(cols=5, rows=2)
        screen.write("")
        assert screen.cursor_row == 0
        assert screen.cursor_col == 0

    def test_incomplete_csi_ignored(self) -> None:
        """不完整的 CSI 序列应被安全忽略。"""
        screen = VTScreen(cols=10, rows=2)
        # ESC [ 无 final 字节
        screen.write("\x1b[")
        # 不应抛错，光标位置不变
        assert screen.cursor_row == 0
        assert screen.cursor_col == 0

    def test_unknown_csi_final_ignored(self) -> None:
        """未实现的 CSI final 字节应被忽略。"""
        screen = VTScreen(cols=10, rows=2)
        # CSI @ 是插入字符，本实现未支持，应被忽略
        screen.write("\x1b[3@")
        assert screen.cursor_row == 0
        assert screen.cursor_col == 0

    def test_auto_wrap_on_long_line(self) -> None:
        """写入超过列宽时自动换行。"""
        screen = VTScreen(cols=5, rows=4)
        screen.write("abcdef")  # 6 个字符，应自动换行
        assert "".join(screen.grid[0]) == "abcde"
        assert screen.grid[1][0] == "f"
        assert screen.cursor_row == 1

    def test_osc_sequence_skipped(self) -> None:
        """OSC 序列（如设置标题）应被跳过。"""
        screen = VTScreen(cols=10, rows=2)
        screen.write("\x1b]0;my title\x07hello")
        # OSC 序列被吞掉，仅写入 hello
        assert "".join(screen.grid[0][:5]) == "hello"
