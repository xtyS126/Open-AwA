"""
简化版 VTE 终端仿真器。

实现 VT100/ANSI 转义序列的最小子集，用于解析 PTY 输出并维护字符网格与滚动历史。
支持：
- 普通可打印字符写入与光标移动
- 控制字符：LF（\\n）/CR（\\r）/BS（\\b）/TAB（\\t）
- CSI 序列：A/B/C/D（光标移动）、H（光标定位）、J（清屏）、K（清行）、m（SGR）
- 其他不支持的转义序列：忽略，不抛错
"""

from __future__ import annotations

import collections
import re
from typing import Deque, Dict, List, Optional, Tuple


# 默认单元格属性：fg=默认前景色，bg=默认背景色，bold=False
_DEFAULT_ATTR: Dict[str, Optional[str]] = {"fg": None, "bg": None, "bold": False}

# 制表位间隔（每 8 列一个 tab stop）
_TAB_STOP_INTERVAL = 8


class VTScreen:
    """简化版 VTE 终端屏幕仿真器。"""

    def __init__(
        self,
        cols: int = 80,
        rows: int = 24,
        scrollback_limit: int = 1000,
    ) -> None:
        """
        初始化终端屏幕。

        Args:
            cols: 列数（必须为正整数）。
            rows: 行数（必须为正整数）。
            scrollback_limit: 滚动历史最大行数。
        """
        if cols <= 0 or rows <= 0:
            raise ValueError("cols/rows 必须为正整数")
        self.cols: int = cols
        self.rows: int = rows
        self.scrollback_limit: int = max(0, scrollback_limit)

        # 字符网格：rows × cols，初始化为空格
        self.grid: List[List[str]] = [
            [" " for _ in range(cols)] for _ in range(rows)
        ]
        # 每个单元格的属性（fg/bg/bold）
        self.attrs: List[List[Dict[str, Optional[str]]]] = [
            [dict(_DEFAULT_ATTR) for _ in range(cols)] for _ in range(rows)
        ]

        # 光标位置（0-based）
        self.cursor_row: int = 0
        self.cursor_col: int = 0

        # 滚动历史
        self.scrollback: Deque[str] = collections.deque(maxlen=self.scrollback_limit)

        # 当前 SGR 属性（写入字符时复制到单元格）
        self._current_attr: Dict[str, Optional[str]] = dict(_DEFAULT_ATTR)

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def write(self, data: str) -> None:
        """
        写入一段数据并解析 ANSI 转义序列。

        遇到 ESC 字符时尝试解析 CSI 或其他 ESC 序列；其余按可打印字符或控制字符处理。
        """
        if not data:
            return

        i = 0
        n = len(data)
        while i < n:
            ch = data[i]
            if ch == "\x1b":
                # ESC 序列：尝试解析
                consumed = self._consume_escape(data, i)
                if consumed <= 1:
                    # 仅 ESC 字符本身，跳过避免死循环
                    i += 1
                else:
                    i += consumed
            else:
                self._write_char(ch)
                i += 1

    def resize(self, cols: int, rows: int) -> None:
        """
        调整网格大小。

        缩小时多余的行进入 scrollback；放大时新增空白行/列。
        光标位置在缩小时会被裁剪到新边界内。
        """
        if cols <= 0 or rows <= 0:
            raise ValueError("cols/rows 必须为正整数")

        old_rows = self.rows
        old_cols = self.cols

        # 行数变化：缩小则把超出的旧行送入 scrollback
        if rows < old_rows:
            # 把超出的顶部行送入 scrollback
            drop_count = old_rows - rows
            for r in range(drop_count):
                self.scrollback.append("".join(self.grid[r]))
            # 重建 grid 与 attrs
            new_grid = [self.grid[r] for r in range(drop_count, old_rows)]
            new_attrs = [self.attrs[r] for r in range(drop_count, old_rows)]
        elif rows > old_rows:
            # 底部追加空行
            new_grid = self.grid + [[" " for _ in range(old_cols)] for _ in range(rows - old_rows)]
            new_attrs = self.attrs + [
                [dict(_DEFAULT_ATTR) for _ in range(old_cols)]
                for _ in range(rows - old_rows)
            ]
        else:
            new_grid = [row[:] for row in self.grid]
            new_attrs = [row[:] for row in self.attrs]

        # 列数变化：截断或补空格
        if cols != old_cols:
            for r in range(rows):
                row = new_grid[r]
                attr_row = new_attrs[r]
                if cols < old_cols:
                    new_grid[r] = row[:cols]
                    new_attrs[r] = attr_row[:cols]
                else:
                    new_grid[r] = row + [" " for _ in range(cols - old_cols)]
                    new_attrs[r] = attr_row + [dict(_DEFAULT_ATTR) for _ in range(cols - old_cols)]

        self.grid = new_grid
        self.attrs = new_attrs
        self.cols = cols
        self.rows = rows

        # 裁剪光标到新边界
        if self.cursor_row >= self.rows:
            self.cursor_row = self.rows - 1
        if self.cursor_col >= self.cols:
            self.cursor_col = self.cols - 1
        if self.cursor_row < 0:
            self.cursor_row = 0
        if self.cursor_col < 0:
            self.cursor_col = 0

    def get_snapshot(self) -> List[List[str]]:
        """返回当前屏幕网格的深拷贝。"""
        return [row[:] for row in self.grid]

    def get_scrollback(self, limit: int = 100) -> List[str]:
        """
        返回滚动历史。

        Args:
            limit: 返回最近 limit 行；超过实际行数时返回全部。
        """
        if limit <= 0:
            return []
        items = list(self.scrollback)
        if len(items) > limit:
            items = items[-limit:]
        return items

    # ------------------------------------------------------------------
    # 内部：字符与控制字符处理
    # ------------------------------------------------------------------
    def _write_char(self, ch: str) -> None:
        """写入单个字符（包括控制字符 LF/CR/BS/TAB）。"""
        if ch == "\n":
            self._line_feed()
            return
        if ch == "\r":
            self.cursor_col = 0
            return
        if ch == "\b":
            # 退格：光标左移一格，不擦除字符
            if self.cursor_col > 0:
                self.cursor_col -= 1
            return
        if ch == "\t":
            # 移动到下一个 tab stop
            next_stop = (self.cursor_col // _TAB_STOP_INTERVAL + 1) * _TAB_STOP_INTERVAL
            self.cursor_col = min(next_stop, self.cols - 1)
            return
        if ch == "\x07":
            # 响铃，忽略
            return

        # 可打印字符
        if self.cursor_col >= self.cols:
            # 自动换行
            self.cursor_col = 0
            self._line_feed()
        if self.cursor_row >= self.rows:
            # 安全兜底：超出时滚动
            self._scroll_up(self.cursor_row - self.rows + 1)
            self.cursor_row = self.rows - 1

        self.grid[self.cursor_row][self.cursor_col] = ch
        self.attrs[self.cursor_row][self.cursor_col] = dict(self._current_attr)
        self.cursor_col += 1

    def _line_feed(self) -> None:
        """换行：光标下移一行，到达底部时滚动。"""
        if self.cursor_row >= self.rows - 1:
            self._scroll_up(1)
        else:
            self.cursor_row += 1

    def _scroll_up(self, n: int = 1) -> None:
        """向上滚动 n 行：顶部 n 行进入 scrollback，底部追加空行。"""
        if n <= 0:
            return
        n = min(n, self.rows)
        for r in range(n):
            self.scrollback.append("".join(self.grid[r]))
        # 重建网格
        new_grid = self.grid[n:] + [[" " for _ in range(self.cols)] for _ in range(n)]
        new_attrs = self.attrs[n:] + [
            [dict(_DEFAULT_ATTR) for _ in range(self.cols)] for _ in range(n)
        ]
        self.grid = new_grid
        self.attrs = new_attrs
        # 光标行号同步上移
        self.cursor_row = max(0, self.cursor_row - n)

    # ------------------------------------------------------------------
    # 内部：转义序列解析
    # ------------------------------------------------------------------
    def _consume_escape(self, data: str, start: int) -> int:
        """
        从 data[start] 开始（必须是 ESC）解析一条转义序列。

        Returns:
            消耗的字符数（包含 ESC）。无法识别时返回 1（仅跳过 ESC）。
        """
        n = len(data)
        # 至少要有 ESC + 1 字符
        if start + 1 >= n:
            return 1

        nxt = data[start + 1]
        if nxt == "[":
            # CSI 序列：ESC [ params final
            return self._consume_csi(data, start)
        if nxt == "]":
            # OSC 序列：ESC ] ... BEL 或 ST（ESC \），简化处理：跳到 BEL 或 ESC
            return self._consume_osc(data, start)
        # 其他 ESC 序列（如 ESC =, ESC >, ESC ( B 等）：消耗 ESC + 1 字符
        self._handle_escape(nxt)
        return 2

    def _consume_csi(self, data: str, start: int) -> int:
        """
        解析 CSI 序列（ESC [ ... final）。

        final 字符范围：0x40-0x7E。中间可包含参数字节 0x30-0x3F 与中间字节 0x20-0x2F。
        """
        n = len(data)
        i = start + 2  # 跳过 ESC [
        params_start = i
        while i < n:
            c = data[i]
            code = ord(c)
            if 0x40 <= code <= 0x7E:
                # final 字节
                params_str = data[params_start:i]
                self._handle_csi(params_str, c)
                return i - start + 1
            i += 1
        # 没有遇到 final 字节，序列不完整：消耗剩余全部
        return n - start

    def _consume_osc(self, data: str, start: int) -> int:
        """解析 OSC 序列（ESC ] data ST/BEL）。简化：找到 BEL 或 ESC \\ 终止。"""
        n = len(data)
        i = start + 2
        while i < n:
            c = data[i]
            if c == "\x07":
                return i - start + 1
            if c == "\x1b" and i + 1 < n and data[i + 1] == "\\":
                return i - start + 2
            i += 1
        return n - start

    def _handle_escape(self, seq: str) -> None:
        """
        处理其他 ESC 序列（非 CSI/OSC）。

        简化实现：忽略所有不支持的序列，避免抛错。
        """
        # 列出已知的 ESC 序列：当前不实现任何行为，保留接口供子类扩展
        _ = seq

    def _handle_csi(self, params: str, final: str) -> None:
        """
        处理 CSI 序列。

        Args:
            params: 参数字节字符串（如 "0;1"），可能为空。
            final: 终止字节（如 "A"、"m"、"J"）。
        """
        # 解析参数列表
        param_list = self._parse_csi_params(params)

        if final == "A":
            # 光标上移 n 行（默认 1）
            n_val = param_list[0] if param_list else 1
            self.cursor_row = max(0, self.cursor_row - max(1, n_val))
            return
        if final == "B":
            # 光标下移 n 行
            n_val = param_list[0] if param_list else 1
            self.cursor_row = min(self.rows - 1, self.cursor_row + max(1, n_val))
            return
        if final == "C":
            # 光标右移 n 列
            n_val = param_list[0] if param_list else 1
            self.cursor_col = min(self.cols - 1, self.cursor_col + max(1, n_val))
            return
        if final == "D":
            # 光标左移 n 列
            n_val = param_list[0] if param_list else 1
            self.cursor_col = max(0, self.cursor_col - max(1, n_val))
            return
        if final in ("H", "f"):
            # 光标定位：CSI row;col H，1-based
            row = (param_list[0] if len(param_list) >= 1 and param_list[0] > 0 else 1) - 1
            col = (param_list[1] if len(param_list) >= 2 and param_list[1] > 0 else 1) - 1
            self.cursor_row = max(0, min(self.rows - 1, row))
            self.cursor_col = max(0, min(self.cols - 1, col))
            return
        if final == "J":
            # 清屏模式：0=光标到末尾，1=开头到光标，2=全屏
            mode = param_list[0] if param_list else 0
            self._erase_display(mode)
            return
        if final == "K":
            # 清行模式：0=光标到行尾，1=行首到光标，2=整行
            mode = param_list[0] if param_list else 0
            self._erase_line(mode)
            return
        if final == "m":
            # SGR：仅解析粗体/重置，其他颜色忽略
            self._handle_sgr(param_list)
            return
        if final == "d":
            # CSA: 行号（垂直绝对位置）
            row = (param_list[0] if param_list and param_list[0] > 0 else 1) - 1
            self.cursor_row = max(0, min(self.rows - 1, row))
            return
        if final == "G":
            # CSA: 列号（水平绝对位置）
            col = (param_list[0] if param_list and param_list[0] > 0 else 1) - 1
            self.cursor_col = max(0, min(self.cols - 1, col))
            return
        # 其他未实现的 CSI 序列：忽略

    def _parse_csi_params(self, params: str) -> List[int]:
        """解析 CSI 参数字符串为整数列表（空段视为 0）。"""
        if not params:
            return []
        # 过滤掉非参数字节（中间字节 0x20-0x2F 之外的）
        # 简化：只取数字与分号
        cleaned = re.sub(r"[^0-9;]", "", params)
        if not cleaned:
            return []
        parts = cleaned.split(";")
        result: List[int] = []
        for p in parts:
            if p == "":
                result.append(0)
            else:
                try:
                    result.append(int(p))
                except ValueError:
                    result.append(0)
        return result

    def _erase_display(self, mode: int) -> None:
        """清屏。"""
        if mode == 0:
            # 光标到末尾
            for c in range(self.cursor_col, self.cols):
                self.grid[self.cursor_row][c] = " "
                self.attrs[self.cursor_row][c] = dict(_DEFAULT_ATTR)
            for r in range(self.cursor_row + 1, self.rows):
                for c in range(self.cols):
                    self.grid[r][c] = " "
                    self.attrs[r][c] = dict(_DEFAULT_ATTR)
        elif mode == 1:
            # 开头到光标
            for r in range(0, self.cursor_row):
                for c in range(self.cols):
                    self.grid[r][c] = " "
                    self.attrs[r][c] = dict(_DEFAULT_ATTR)
            for c in range(0, self.cursor_col + 1):
                self.grid[self.cursor_row][c] = " "
                self.attrs[self.cursor_row][c] = dict(_DEFAULT_ATTR)
        elif mode == 2:
            # 全屏
            for r in range(self.rows):
                for c in range(self.cols):
                    self.grid[r][c] = " "
                    self.attrs[r][c] = dict(_DEFAULT_ATTR)

    def _erase_line(self, mode: int) -> None:
        """清行。"""
        if mode == 0:
            for c in range(self.cursor_col, self.cols):
                self.grid[self.cursor_row][c] = " "
                self.attrs[self.cursor_row][c] = dict(_DEFAULT_ATTR)
        elif mode == 1:
            for c in range(0, self.cursor_col + 1):
                self.grid[self.cursor_row][c] = " "
                self.attrs[self.cursor_row][c] = dict(_DEFAULT_ATTR)
        elif mode == 2:
            for c in range(self.cols):
                self.grid[self.cursor_row][c] = " "
                self.attrs[self.cursor_row][c] = dict(_DEFAULT_ATTR)

    def _handle_sgr(self, param_list: List[int]) -> None:
        """处理 SGR 序列。简化：仅识别 0=重置、1=粗体、22=取消粗体。"""
        if not param_list:
            param_list = [0]
        i = 0
        while i < len(param_list):
            code = param_list[i]
            if code == 0:
                self._current_attr = dict(_DEFAULT_ATTR)
            elif code == 1:
                self._current_attr["bold"] = True
            elif code == 22:
                self._current_attr["bold"] = False
            # 其他颜色码：忽略，但保持当前属性
            i += 1


__all__ = ["VTScreen"]
