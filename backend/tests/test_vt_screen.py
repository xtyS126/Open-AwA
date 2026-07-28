"""
PTYSession 与 pyte 终端仿真器集成测试。

原 test_vt_screen.py 测试的是自实现 VTScreen 的内部 API（grid/cursor_row/_current_attr 等）。
Task 7 用 pyte 库替换 VTScreen 后，本文件改为对 PTYSession 的 pyte 集成测试：
直接构造 PTYSession（不启动子进程），通过 _stream.feed() 模拟 PTY 输出，
验证 get_snapshot / get_scrollback / resize / 复杂 ANSI 序列解析行为。

覆盖：
- PTYSession 接口签名兼容性（get_snapshot 返回 List[List[str]]，get_scrollback 返回 List[str]）
- 普通字符写入与光标移动（pyte cursor.x / cursor.y）
- 控制字符 LF/CR/TAB
- CSI A/B/C/D 光标移动
- CSI H 光标定位
- CSI J 清屏 / CSI K 清行
- SGR 序列：粗体/重置/256色/真彩色不抛错
- DECSC/DECRC（保存/恢复光标）
- OSC 序列跳过
- 复杂 TUI 序列（vim/tmux 风格）不抛错
- 滚动历史与 get_scrollback limit 参数
- resize 后 columns/lines 更新与内容保留
- snapshot 返回深拷贝（修改不影响内部状态）
"""

from __future__ import annotations

from typing import List

from core.terminal.pty_session import PTYSession


# ----------------------------------------------------------------------
# 工具：构造不启动子进程的 PTYSession 用于直接驱动 pyte Stream
# ----------------------------------------------------------------------

def _make_session(cols: int = 80, rows: int = 24) -> PTYSession:
    """构造 PTYSession 但不 start，仅用于驱动 pyte Stream 解析。"""
    return PTYSession(
        command=["/bin/bash"],
        cwd=".",
        cols=cols,
        rows=rows,
    )


def _feed(session: PTYSession, data: str) -> None:
    """向 PTYSession 的 pyte Stream 喂入 ANSI 数据。"""
    session._stream.feed(data)


def _row(snapshot: List[List[str]], row: int) -> str:
    """从二维字符网格中取一行并 join 为字符串。"""
    return "".join(snapshot[row])


# ----------------------------------------------------------------------
# 测试：PTYSession 接口签名兼容性
# ----------------------------------------------------------------------

class TestPTYSessionPyteInterface:
    """PTYSession 在 pyte 替换后接口签名应保持兼容。"""

    def test_get_snapshot_returns_2d_list(self) -> None:
        """get_snapshot 返回 List[List[str]]，维度为 rows × cols。"""
        session = _make_session(cols=5, rows=3)
        _feed(session, "ab")
        snap = session.get_snapshot()
        assert isinstance(snap, list)
        assert len(snap) == 3
        for row in snap:
            assert isinstance(row, list)
            assert len(row) == 5

    def test_get_scrollback_returns_string_list(self) -> None:
        """get_scrollback 返回 List[str]，每行字符串。"""
        session = _make_session(cols=5, rows=1)
        _feed(session, "AAAAA\r\nBBBBB\r\nCCCCC")
        scrollback = session.get_scrollback(10)
        assert isinstance(scrollback, list)
        for line in scrollback:
            assert isinstance(line, str)

    def test_vt_screen_attribute_is_pyte_history_screen(self) -> None:
        """vt_screen 属性应为 pyte.HistoryScreen 实例（保留属性名以维持向后兼容）。"""
        import pyte
        session = _make_session()
        assert isinstance(session.vt_screen, pyte.HistoryScreen)

    def test_stream_attribute_is_pyte_stream(self) -> None:
        """_stream 属性应为 pyte.Stream 实例。"""
        import pyte
        session = _make_session()
        assert isinstance(session._stream, pyte.Stream)


# ----------------------------------------------------------------------
# 测试：基础字符写入与光标移动
# ----------------------------------------------------------------------

class TestPyteBasicWrite:
    """基础字符写入测试（pyte 行为）。"""

    def test_write_text_advances_cursor(self) -> None:
        """写入普通文本，光标应随之右移。"""
        session = _make_session(cols=10, rows=3)
        _feed(session, "hello")
        snap = session.get_snapshot()
        assert _row(snap, 0)[:5] == "hello"
        # pyte cursor.x 是列号（0-based）
        assert session.vt_screen.cursor.x == 5
        assert session.vt_screen.cursor.y == 0

    def test_write_crlf_moves_to_next_row(self) -> None:
        """写入 \\r\\n 后光标回到下一行行首。"""
        session = _make_session(cols=10, rows=3)
        _feed(session, "ab\r\ncd")
        snap = session.get_snapshot()
        assert _row(snap, 0)[:2] == "ab"
        assert _row(snap, 1)[:2] == "cd"
        assert session.vt_screen.cursor.y == 1
        assert session.vt_screen.cursor.x == 2

    def test_write_cr_resets_column(self) -> None:
        """写入 \\r 后光标列回到行首。"""
        session = _make_session(cols=10, rows=3)
        _feed(session, "abc\rXY")
        snap = session.get_snapshot()
        # CR 后 XY 应覆盖 abc 的前两个字符
        assert _row(snap, 0)[:3] == "XYc"
        assert session.vt_screen.cursor.x == 2

    def test_write_tab_moves_to_next_tab_stop(self) -> None:
        """写入 \\t 后光标移到下一个 tab stop（8 列对齐）。"""
        session = _make_session(cols=20, rows=2)
        _feed(session, "a\tb")
        snap = session.get_snapshot()
        assert snap[0][0] == "a"
        assert snap[0][8] == "b"
        assert session.vt_screen.cursor.x == 9


# ----------------------------------------------------------------------
# 测试：CSI 光标移动
# ----------------------------------------------------------------------

class TestPyteCsiCursor:
    """CSI 光标移动测试（pyte 行为）。"""

    def test_csi_a_moves_cursor_up(self) -> None:
        """CSI A 光标上移 n 行。"""
        session = _make_session(cols=10, rows=5)
        _feed(session, "\x1b[3;1H")  # 先定位到 (col=0, row=2)
        _feed(session, "\x1b[2A")
        assert session.vt_screen.cursor.y == 0

    def test_csi_b_moves_cursor_down(self) -> None:
        """CSI B 光标下移 n 行。"""
        session = _make_session(cols=10, rows=5)
        _feed(session, "\x1b[2B")
        assert session.vt_screen.cursor.y == 2

    def test_csi_c_moves_cursor_right(self) -> None:
        """CSI C 光标右移 n 列。"""
        session = _make_session(cols=10, rows=5)
        _feed(session, "\x1b[3C")
        assert session.vt_screen.cursor.x == 3

    def test_csi_d_moves_cursor_left(self) -> None:
        """CSI D 光标左移 n 列。"""
        session = _make_session(cols=10, rows=5)
        _feed(session, "\x1b[5C")
        _feed(session, "\x1b[2D")
        assert session.vt_screen.cursor.x == 3

    def test_csi_h_positions_cursor(self) -> None:
        """CSI H 光标定位（1-based 行;列）。"""
        session = _make_session(cols=20, rows=10)
        _feed(session, "hello\x1b[3;5H")
        # 行 3 列 5 -> 0-based row=2, col=4
        assert session.vt_screen.cursor.y == 2
        assert session.vt_screen.cursor.x == 4

    def test_csi_h_default_home(self) -> None:
        """无参数 CSI H 等价于回到 (0,0)。"""
        session = _make_session(cols=20, rows=10)
        _feed(session, "\x1b[5;5H")
        _feed(session, "\x1b[H")
        assert session.vt_screen.cursor.y == 0
        assert session.vt_screen.cursor.x == 0


# ----------------------------------------------------------------------
# 测试：CSI 清屏/清行
# ----------------------------------------------------------------------

class TestPyteCsiErase:
    """CSI 清屏/清行测试。"""

    def test_csi_2j_clears_full_screen(self) -> None:
        """CSI 2J 清空整个屏幕。"""
        session = _make_session(cols=10, rows=3)
        _feed(session, "abc\r\ndef\r\nghi")
        _feed(session, "\x1b[2J")
        snap = session.get_snapshot()
        for r in range(3):
            assert _row(snap, r) == " " * 10

    def test_csi_k_clears_line_from_cursor(self) -> None:
        """CSI K（默认 0）清空光标到行尾。"""
        session = _make_session(cols=10, rows=2)
        _feed(session, "abcdefghij")  # 第一行填满
        _feed(session, "\x1b[1;4H")  # 定位到 col=3, row=0
        _feed(session, "\x1b[K")
        snap = session.get_snapshot()
        # 前 3 个字符保留，后面应为空格
        assert _row(snap, 0)[:3] == "abc"
        assert _row(snap, 0)[3:] == " " * 7

    def test_csi_2k_clears_full_line(self) -> None:
        """CSI 2K 清空整行。"""
        session = _make_session(cols=10, rows=2)
        _feed(session, "abcdefghij")
        _feed(session, "\x1b[1;1H")  # 定位到行首
        _feed(session, "\x1b[2K")
        snap = session.get_snapshot()
        assert _row(snap, 0) == " " * 10


# ----------------------------------------------------------------------
# 测试：SGR 序列（粗体/重置/256色/真彩色）
# ----------------------------------------------------------------------

class TestPyteSGR:
    """SGR 序列测试：pyte 完整支持 256 色/真彩色，不抛错。"""

    def test_sgr_bold_and_reset(self) -> None:
        """SGR 1 开启粗体，SGR 0 重置。"""
        session = _make_session(cols=10, rows=2)
        _feed(session, "\x1b[1m")
        # pyte Char 有 bold 属性
        # 写入字符后检查其 bold 属性
        _feed(session, "A")
        char = session.vt_screen.buffer[0][0]
        assert char.bold is True
        _feed(session, "\x1b[0m")
        _feed(session, "B")
        char_b = session.vt_screen.buffer[0][1]
        assert char_b.bold is False

    def test_sgr_256_color_no_error(self) -> None:
        """256 色 SGR 序列（38;5;n / 48;5;n）应被正确解析，不抛错。"""
        session = _make_session(cols=10, rows=2)
        # 38;5;200 = 前景色 256 色第 200 号
        _feed(session, "\x1b[38;5;200mhello")
        snap = session.get_snapshot()
        assert _row(snap, 0)[:5] == "hello"
        # pyte 0.8.x 将 256 色索引转换为 hex 颜色字符串（如 'ff00d7'）
        char = session.vt_screen.buffer[0][0]
        assert char.fg != "default"
        assert isinstance(char.fg, str)

    def test_sgr_truecolor_no_error(self) -> None:
        """真彩色 SGR 序列（38;2;r;g;b）应被正确解析，不抛错。"""
        session = _make_session(cols=10, rows=2)
        # 38;2;255;0;0 = 红色真彩色前景
        _feed(session, "\x1b[38;2;255;0;0mhello")
        snap = session.get_snapshot()
        assert _row(snap, 0)[:5] == "hello"
        # pyte 0.8.x 将真彩色转为 hex 颜色字符串（'ff0000'）
        char = session.vt_screen.buffer[0][0]
        assert char.fg == "ff0000"

    def test_sgr_complex_sequence_no_error(self) -> None:
        """复杂 SGR 组合（粗体+斜体+下划线+反色+前景+背景）应被正确解析。"""
        session = _make_session(cols=10, rows=2)
        # 1=bold, 3=italics, 4=underscore, 7=reverse, 31=red fg, 42=green bg
        _feed(session, "\x1b[1;3;4;7;31;42mhello")
        snap = session.get_snapshot()
        assert _row(snap, 0)[:5] == "hello"


# ----------------------------------------------------------------------
# 测试：DECSC/DECRC 与 OSC
# ----------------------------------------------------------------------

class TestPyteEscapeSequences:
    """其他转义序列测试。"""

    def test_decsc_decrc_saves_restores_cursor(self) -> None:
        """ESC 7（DECSC）保存光标，ESC 8（DECRC）恢复光标。"""
        session = _make_session(cols=20, rows=10)
        _feed(session, "\x1b[5;5H")  # 定位到 (4, 4)
        _feed(session, "\x1b7")  # 保存
        _feed(session, "\x1b[1;1H")  # 移动到 (0, 0)
        _feed(session, "\x1b8")  # 恢复
        assert session.vt_screen.cursor.y == 4
        assert session.vt_screen.cursor.x == 4

    def test_osc_sequence_skipped(self) -> None:
        """OSC 序列（如设置标题）应被跳过，不影响屏幕内容。"""
        session = _make_session(cols=10, rows=2)
        _feed(session, "\x1b]0;my title\x07hello")
        snap = session.get_snapshot()
        # OSC 序列被吞掉，仅写入 hello
        assert _row(snap, 0)[:5] == "hello"

    def test_incomplete_csi_does_not_raise(self) -> None:
        """不完整的 CSI 序列应被安全忽略，不抛错。"""
        session = _make_session(cols=10, rows=2)
        # ESC [ 无 final 字节
        _feed(session, "\x1b[")
        # 再喂一个 final 字节使其完成（不抛错即可）
        _feed(session, "A")
        # 不抛错即通过

    def test_complex_vim_like_sequence_no_error(self) -> None:
        """模拟 vim 启动输出的复杂 ANSI 序列不应抛错。"""
        session = _make_session(cols=80, rows=24)
        # 包含光标定位、清屏、SGR、交替屏幕缓冲等序列
        complex_seq = (
            "\x1b[?1049h"  # 启用交替屏幕缓冲
            "\x1b[?1h\x1b="  # 应用键盘模式
            "\x1b[2J\x1b[H"  # 清屏并回到原点
            "\x1b[1;1H\x1b[37;44m"  # 定位 + 白字蓝底
            "  normal.txt  "
            "\x1b[0m"
            "\x1b[2;1H~\x1b[3;1H~\x1b[4;1H~"
            "\x1b[24;1H\x1b[7m-- INSERT --\x1b[0m"
            "\x1b[?25l"  # 隐藏光标
        )
        _feed(session, complex_seq)
        # 不抛错且屏幕上有内容即通过
        snap = session.get_snapshot()
        assert _row(snap, 0).startswith("  normal.txt")

    def test_tmux_like_sequence_no_error(self) -> None:
        """模拟 tmux 状态栏输出的复杂 ANSI 序列不应抛错。"""
        session = _make_session(cols=80, rows=24)
        tmux_seq = (
            "\x1b[2J\x1b[H"
            "\x1b[1;1H\x1b[34m[0] 0:bash*\x1b[0m"
            "\x1b[1;20H\"example\" (new session)"
            "\x1b[24;1H\x1b[32m12:34:56\x1b[0m"
            # 256 色状态栏
            "\x1b[1;40H\x1b[38;5;45m" + "mode" + "\x1b[0m"
        )
        _feed(session, tmux_seq)
        snap = session.get_snapshot()
        # 第一行应包含 bash 标识
        assert "bash" in _row(snap, 0)


# ----------------------------------------------------------------------
# 测试：滚动历史
# ----------------------------------------------------------------------

class TestPyteScrollback:
    """滚动历史测试。"""

    def test_lines_scrolled_into_scrollback(self) -> None:
        """写入超过 rows 行后，旧行进入 scrollback。"""
        session = _make_session(cols=5, rows=2)
        # 写入 5 行（每行末尾用 \r\n 表示完整换行）
        _feed(session, "AAAAA\r\nBBBBB\r\nCCCCC\r\nDDDDD\r\nEEEEE")
        scrollback = session.get_scrollback(10)
        # 滚动历史非空
        assert len(scrollback) > 0
        # 最早的 AAAAA 应进入 scrollback
        assert any("AAAAA" in line for line in scrollback)
        # pyte 符合 VT100 标准（LNM off）：LF 在底部触发滚动，cursor.x 不重置
        # 因此 5 行写入 2 行屏幕后：scrollback=[AAAAA,BBBBB,CCCCC]，屏幕=[DDDDD,EEEEE]
        snap = session.get_snapshot()
        assert _row(snap, 0) == "DDDDD"
        assert _row(snap, 1) == "EEEEE"

    def test_get_scrollback_limit_param(self) -> None:
        """get_scrollback(limit) 应只返回最近 limit 行。"""
        session = _make_session(cols=3, rows=1)
        for c in ["AAA", "BBB", "CCC", "DDD"]:
            _feed(session, c + "\r\n")
        # 限制返回 2 行
        result = session.get_scrollback(2)
        assert len(result) == 2
        # 最后一行应为 DDD（最近滚出的行）
        assert "DDD" in result[-1]

    def test_get_scrollback_zero_limit_returns_empty(self) -> None:
        """get_scrollback(0) 应返回空列表。"""
        session = _make_session(cols=3, rows=1)
        _feed(session, "AAA\r\nBBB")
        assert session.get_scrollback(0) == []

    def test_scrollback_lines_padded_to_columns(self) -> None:
        """scrollback 每行字符串应 pad 到当前 columns 宽度。"""
        session = _make_session(cols=5, rows=1)
        _feed(session, "AB\r\nCD")
        scrollback = session.get_scrollback(10)
        # 每行长度应为 5（cols 宽度）
        for line in scrollback:
            assert len(line) == 5


# ----------------------------------------------------------------------
# 测试：resize
# ----------------------------------------------------------------------

class TestPyteResize:
    """resize 测试。"""

    def test_resize_updates_dimensions(self) -> None:
        """resize 后 cols/rows 与 pyte columns/lines 同步。"""
        import asyncio

        session = _make_session(cols=5, rows=2)
        asyncio.run(session.resize(cols=8, rows=3))
        assert session.cols == 8
        assert session.rows == 3
        assert session.vt_screen.columns == 8
        assert session.vt_screen.lines == 3

    def test_resize_grows_display(self) -> None:
        """resize 扩大后 display 行数与每行列数应更新。"""
        import asyncio

        session = _make_session(cols=5, rows=2)
        asyncio.run(session.resize(cols=8, rows=3))
        snap = session.get_snapshot()
        assert len(snap) == 3
        for row in snap:
            assert len(row) == 8

    def test_resize_preserves_content(self) -> None:
        """resize 扩大后原内容应保留。"""
        import asyncio

        session = _make_session(cols=5, rows=2)
        _feed(session, "abcde\r\nfghij")
        asyncio.run(session.resize(cols=8, rows=3))
        snap = session.get_snapshot()
        # 原内容保留（前 5 列）
        assert _row(snap, 0)[:5] == "abcde"
        # 第三行为新增空行
        assert _row(snap, 2) == " " * 8


# ----------------------------------------------------------------------
# 测试：snapshot 深拷贝
# ----------------------------------------------------------------------

class TestPyteSnapshotIndependence:
    """snapshot 返回深拷贝，修改不影响内部状态。"""

    def test_snapshot_is_independent_copy(self) -> None:
        """get_snapshot 返回二维列表的深拷贝。"""
        session = _make_session(cols=5, rows=2)
        _feed(session, "abcde")
        snap = session.get_snapshot()
        snap[0][0] = "X"
        # 内部 display 不应被影响
        snap2 = session.get_snapshot()
        assert snap2[0][0] == "a"

    def test_snapshot_reflects_latest_feed(self) -> None:
        """每次 get_snapshot 应反映最新的 feed 结果。"""
        session = _make_session(cols=5, rows=2)
        _feed(session, "ab")
        snap1 = session.get_snapshot()
        assert snap1[0][0] == "a"
        _feed(session, "c")
        snap2 = session.get_snapshot()
        assert snap2[0][2] == "c"
