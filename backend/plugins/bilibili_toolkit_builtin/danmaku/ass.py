"""ASS 字幕渲染（含 lane 碰撞算法）。

将 :class:`DanmakuElem` 列表渲染为 ASS（Advanced SubStation Alpha）字幕
字符串，包含 3 种 style：Float（滚动）/ Bottom（底部）/ Top（顶部）。

lane 碰撞算法：
- 滚动弹幕（mode=1）：同一 lane 上，前一条弹幕的右边界必须先离开屏幕
  右边缘，后一条弹幕才能进入；若会碰撞则尝试延迟（最多 1 秒），
  延迟后仍碰撞则跳过该弹幕。
- 顶部（mode=5）/ 底部（mode=4）弹幕：独立 lane 池，同一 lane 上
  前一条弹幕消失后才能放新弹幕。
- 高级弹幕（mode>=7）直接跳过。

参考实现：
- ``bili-sync/crates/bili_sync/src/bilibili/danmaku/canvas/mod.rs``
  ``Canvas`` 与 ``CanvasConfig``
- ``bili-sync/crates/bili_sync/src/bilibili/danmaku/canvas/lane.rs``
  ``Lane`` 与 ``Collision``
- ``bili-sync/crates/bili_sync/src/bilibili/danmaku/ass_writer.rs``
  ``AssWriter`` 与 ``DanmakuOption::ass_styles``
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field
from google.protobuf.message import Message as _ProtoMessage

# ASS 画布分辨率（与任务要求一致）
ASS_PLAY_RES_X: int = 1920
ASS_PLAY_RES_Y: int = 1080

# 基准字号（像素），font_size 字段作为缩放系数时使用
_BASE_FONT_SIZE: int = 25

# 弹幕类型编号
_MODE_FLOAT: int = 1
_MODE_BOTTOM: int = 4
_MODE_TOP: int = 5

# 顶部/底部弹幕显示时长（秒），与滚动 duration 解耦
_TOP_BOTTOM_DURATION: float = 5.0

# 允许延迟的最大秒数（与 Rust canvas.rs 的 1.0 一致）
_MAX_DELAY_SECONDS: float = 1.0


class DanmakuOption(BaseModel):
    """ASS 渲染选项。

    字段对应 ``schema.json`` 的 ``danmaku_option`` 配置项，WebUI 可热更新。
    """

    font: str = Field(default="sans-serif", description="ASS 字体名称")
    font_size: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="字号缩放系数，1.0 表示基准字号 25 像素",
    )
    alpha: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="不透明度 0-1，1.0 表示完全不透明",
    )
    stroke: float = Field(
        default=1.5,
        ge=0.0,
        le=10.0,
        description="描边宽度",
    )
    lane_size: int = Field(
        default=32,
        ge=8,
        le=128,
        description="轨道高度（像素），影响 lane 数量与弹幕行高",
    )
    # 以下字段为 lane 碰撞算法所需，参考 Rust DanmakuOption
    duration: float = Field(
        default=15.0,
        ge=3.0,
        description="滚动弹幕的固定显示时长（秒），最少 3 秒",
    )
    width_ratio: float = Field(
        default=1.2,
        ge=0.5,
        le=5.0,
        description="弹幕像素长度缩放系数",
    )
    horizontal_gap: float = Field(
        default=20.0,
        ge=0.0,
        description="两条滚动弹幕之间的最小水平间距（像素）",
    )
    float_percentage: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="滚动弹幕最多占用的屏幕高度百分比",
    )
    bottom_percentage: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="底部弹幕最多占用的屏幕高度百分比（顶部共用）",
    )
    bold: bool = Field(default=True, description="是否加粗")
    time_offset: float = Field(
        default=0.0,
        description="时间轴偏移（秒），用于整体提前/延后",
    )


@dataclass
class _Danmu:
    """内部弹幕表示，剥离 protobuf Message 后用于 lane 布局。

    Attributes:
        timeline_s: 出现时间（秒，由 progress 毫秒转换）。
        content: 弹幕正文。
        mode: 弹幕类型（1=滚动 4=底部 5=顶部）。
        rgb: (r, g, b) 三元组，由 color 字段解析。
    """

    timeline_s: float
    content: str
    mode: int
    rgb: tuple[int, int, int]


@dataclass
class _Drawable:
    """一条已布局的 ASS Dialogue 行所需的全部信息。"""

    danmu: _Danmu
    duration: float
    style_name: str
    start: tuple[int, int]
    end: tuple[int, int]


@dataclass
class _Lane:
    """单个 lane 的占用状态。

    Attributes:
        last_shoot_time: 上一条弹幕的发射时间（秒）。
        last_length: 上一条弹幕的像素长度。
    """

    last_shoot_time: float
    last_length: float


@dataclass
class _Collision:
    """lane 碰撞检测结果。

    ``time_needed`` 仅在 ``kind="collide"`` 时有意义。
    """

    kind: str  # "separate" / "not_enough_time" / "collide"
    time_needed: float = 0.0


def _danmu_length(danmu: _Danmu, option: DanmakuOption) -> float:
    """计算弹幕的像素长度。

    汉字算一个全宽，ASCII 字符算 2/3 宽（与 Rust ``Danmu::length`` 一致）。
    再乘 :attr:`DanmakuOption.width_ratio` 缩放系数。

    Args:
        danmu: 内部弹幕表示。
        option: 渲染选项。

    Returns:
        弹幕像素长度（浮点数）。
    """
    # ASCII 字符权重 2，非 ASCII 字符权重 3，求和后除以 3 得到字符宽度倍数
    char_sum = sum(2 if ch.isascii() else 3 for ch in danmu.content)
    base_length = _BASE_FONT_SIZE * char_sum / 3
    return base_length * option.width_ratio


def _lane_available_for(
    lane: _Lane,
    other: _Danmu,
    option: DanmakuOption,
    canvas_width: int,
) -> _Collision:
    """判断 lane 是否可以容纳新弹幕（滚动弹幕专用）。

    算法完全对齐 Rust ``Lane::available_for``，T 为固定 duration。

    Args:
        lane: 当前 lane 状态。
        other: 待放置弹幕。
        option: 渲染选项（提供 duration / horizontal_gap）。
        canvas_width: 画布宽度（像素）。

    Returns:
        :class:`_Collision` 检测结果。
    """
    t = option.duration
    w = float(canvas_width)
    gap = option.horizontal_gap

    t1 = lane.last_shoot_time
    t2 = other.timeline_s
    l1 = lane.last_length
    l2 = _danmu_length(other, option)

    v1 = (w + l1) / t
    v2 = (w + l2) / t

    delta_t = t2 - t1
    # 第一条弹幕右边到屏幕右边的距离
    delta_x = v1 * delta_t - l1

    if delta_x < gap:
        # 没有足够的空间，必定碰撞
        if l2 <= l1:
            # l2 较短较慢，只需安排在 l1 之后
            return _Collision(
                kind="collide",
                time_needed=(gap - delta_x) / v1,
            )
        # l2 较长较快，需要 l1 消失后 l2 也有足够距离
        return _Collision(
            kind="collide",
            time_needed=(t - (w - gap) / v2) - delta_t,
        )

    # delta_x >= gap，第一条已发射
    if l2 <= l1:
        # l2 较慢，永远追不上，安全
        return _Collision(kind="separate")

    # 追击问题：l2 较快可能在 l1 消失后追上
    pos = v2 * (t - delta_t)
    if pos < (w - gap):
        return _Collision(kind="not_enough_time")
    return _Collision(
        kind="collide",
        time_needed=(pos - (w - gap)) / v2,
    )


def _top_bottom_available_for(
    lane: _Lane,
    other: _Danmu,
    duration: float,
) -> _Collision:
    """判断 top/bottom lane 是否可容纳新弹幕。

    top/bottom 弹幕固定位置显示，碰撞条件简单：同一 lane 上前一条
    弹幕的结束时间（last_shoot_time + duration）必须早于新弹幕开始时间。

    Args:
        lane: 当前 lane 状态。
        other: 待放置弹幕。
        duration: top/bottom 弹幕显示时长（秒）。

    Returns:
        :class:`_Collision` 检测结果。
    """
    end_time = lane.last_shoot_time + duration
    if other.timeline_s >= end_time:
        return _Collision(kind="separate")
    return _Collision(
        kind="collide",
        time_needed=end_time - other.timeline_s,
    )


@dataclass
class _Canvas:
    """弹幕画布，管理 float / top / bottom 三组 lane 池。

    每组 lane 池是一个 ``list[_Lane | None]``，``None`` 表示该 lane 从未被
    使用（首次放置时无需碰撞检测，直接写入）。
    """

    width: int
    height: int
    option: DanmakuOption
    float_lanes: list[Optional[_Lane]]
    top_lanes: list[Optional[_Lane]]
    bottom_lanes: list[Optional[_Lane]]

    def draw(self, danmu: _Danmu) -> Optional[_Drawable]:
        """尝试将弹幕布局到画布上，返回 Drawable 或 None（被跳过）。

        Args:
            danmu: 内部弹幕表示。

        Returns:
            :class:`_Drawable` 实例，或 ``None`` 表示该弹幕被跳过。
        """
        # 应用时间轴偏移
        danmu.timeline_s += self.option.time_offset
        if danmu.timeline_s < 0.0:
            return None

        if danmu.mode == _MODE_FLOAT:
            return self._draw_float(danmu)
        if danmu.mode == _MODE_TOP:
            return self._draw_top_bottom(danmu, "Top", self.top_lanes)
        if danmu.mode == _MODE_BOTTOM:
            return self._draw_top_bottom(danmu, "Bottom", self.bottom_lanes)
        # 高级弹幕（mode >= 7）等不支持，跳过
        return None

    def _draw_float(self, danmu: _Danmu) -> Optional[_Drawable]:
        """滚动弹幕的 lane 碰撞布局。

        遍历所有 float lane，找到第一个可放置（空 / Separate / NotEnoughTime）
        的 lane；若全部 Collide 则选 time_needed 最小的 lane，延迟不超过
        :data:`_MAX_DELAY_SECONDS` 秒后放置，否则跳过。
        """
        collisions: list[tuple[float, int]] = []
        for idx, lane in enumerate(self.float_lanes):
            if lane is None:
                # 空 lane 直接放置
                return self._place_float(danmu, idx)
            col = _lane_available_for(lane, danmu, self.option, self.width)
            if col.kind in ("separate", "not_enough_time"):
                return self._place_float(danmu, idx)
            # collide，记录 time_needed 与 lane idx
            collisions.append((col.time_needed, idx))

        # 全部 collide，尝试延迟
        if collisions:
            collisions.sort(key=lambda x: x[0])
            time_needed, lane_idx = collisions[0]
            if time_needed < _MAX_DELAY_SECONDS:
                # 延迟 time_needed + 0.01 秒后放置（间隔也不要太小）
                danmu.timeline_s += time_needed + 0.01
                return self._place_float(danmu, lane_idx)
        return None

    def _place_float(self, danmu: _Danmu, lane_idx: int) -> _Drawable:
        """在指定 float lane 上放置弹幕，返回 Drawable 并更新 lane 状态。"""
        length = _danmu_length(danmu, self.option)
        self.float_lanes[lane_idx] = _Lane(
            last_shoot_time=danmu.timeline_s,
            last_length=length,
        )
        y = lane_idx * self.option.lane_size
        return _Drawable(
            danmu=danmu,
            duration=self.option.duration,
            style_name="Float",
            start=(self.width, y),
            end=(-int(length), y),
        )

    def _draw_top_bottom(
        self,
        danmu: _Danmu,
        style_name: str,
        lanes: list[Optional[_Lane]],
    ) -> Optional[_Drawable]:
        """顶部/底部弹幕的 lane 碰撞布局。

        遍历所有 lane，找到第一个可放置（空 / Separate）的 lane；
        若全部 Collide 则尝试延迟，不超过 :data:`_MAX_DELAY_SECONDS` 秒。
        """
        collisions: list[tuple[float, int]] = []
        for idx, lane in enumerate(lanes):
            if lane is None:
                return self._place_top_bottom(danmu, style_name, idx, lanes)
            col = _top_bottom_available_for(lane, danmu, _TOP_BOTTOM_DURATION)
            if col.kind == "separate":
                return self._place_top_bottom(danmu, style_name, idx, lanes)
            collisions.append((col.time_needed, idx))

        if collisions:
            collisions.sort(key=lambda x: x[0])
            time_needed, lane_idx = collisions[0]
            if time_needed < _MAX_DELAY_SECONDS:
                danmu.timeline_s += time_needed + 0.01
                return self._place_top_bottom(danmu, style_name, lane_idx, lanes)
        return None

    def _place_top_bottom(
        self,
        danmu: _Danmu,
        style_name: str,
        lane_idx: int,
        lanes: list[Optional[_Lane]],
    ) -> _Drawable:
        """在指定 top/bottom lane 上放置弹幕，返回 Drawable 并更新 lane 状态。"""
        lanes[lane_idx] = _Lane(
            last_shoot_time=danmu.timeline_s,
            last_length=0.0,  # top/bottom 弹幕不使用 length 字段
        )
        # top/bottom 弹幕水平居中，垂直位置由 lane_idx 决定
        # ASS Alignment=7（左上）+ MarginV 控制垂直位置；这里用 MarginV 间接控制
        # 简化处理：用 \pos 标签定位
        x = self.width // 2
        if style_name == "Top":
            y = lane_idx * self.option.lane_size
        else:
            # Bottom 弹幕从底部往上排
            y = self.height - (lane_idx + 1) * self.option.lane_size
        return _Drawable(
            danmu=danmu,
            duration=_TOP_BOTTOM_DURATION,
            style_name=style_name,
            start=(x, y),
            end=(x, y),
        )


def _format_time(t: float) -> str:
    """将秒数格式化为 ASS 时间字符串 ``H:MM:SS.cc``。

    Args:
        t: 时间（秒，浮点数）。

    Returns:
        形如 ``0:00:01.50`` 的时间字符串。
    """
    if t < 0:
        t = 0.0
    total_cs = int(round(t * 100.0))
    hours = total_cs // 360000
    minutes = (total_cs % 360000) // 6000
    seconds = (total_cs % 6000) // 100
    cs = total_cs % 100
    return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"


def _escape_text(text: str) -> str:
    """转义 ASS 文本：去除首尾空白，``\\n`` 转换为 ``\\N``。

    Args:
        text: 原始弹幕文本。

    Returns:
        转义后的文本。
    """
    return text.strip().replace("\n", "\\N")


def _ass_color(alpha: float, rgb: tuple[int, int, int]) -> str:
    """生成 ASS 颜色字符串 ``&HAABBGGRR``。

    ASS 颜色格式：``&H{alpha:02x}{BB}{GG:02x}{RR:02x}``，
    其中 alpha 0=不透明，255=完全透明。

    Args:
        alpha: 不透明度 0-1（1.0 表示完全不透明）。
        rgb: (r, g, b) 三元组，每个分量 0-255。

    Returns:
        8 字符的 ASS 颜色字符串（不含 ``&H`` 前缀），如 ``4CFFFFFF``。
    """
    # 不透明度 alpha 转 ASS 透明度（0=不透明，255=完全透明）
    ass_alpha = int(round((1.0 - max(0.0, min(1.0, alpha))) * 255.0))
    r, g, b = rgb
    # 限制 0-255
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    return f"{ass_alpha:02X}{b:02X}{g:02X}{r:02X}"


def _build_styles(option: DanmakuOption) -> list[str]:
    """生成 ASS [V4+ Styles] 段的三条 Style 行。

    格式：``Style: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,
    OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,
    Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,
    MarginV,Encoding``

    Args:
        option: 渲染选项。

    Returns:
        三条 Style 行（Float / Bottom / Top），不带换行符。
    """
    # 实际字号 = 基准字号 * 缩放系数
    font_size = int(round(_BASE_FONT_SIZE * option.font_size))
    # 透明度字符串（PrimaryColour 与 OutlineColour 共用）
    primary = _ass_color(option.alpha, (255, 255, 255))
    outline = _ass_color(option.alpha, (0, 0, 0))
    bold = "1" if option.bold else "0"
    # 三种 style 的差异仅 Name，其余字段完全相同（与 Rust ass_styles 一致）
    common = (
        f",{option.font},{font_size},&H{primary},&H00FFFFFF,&H{outline},&H00000000,"
        f"{bold},0,0,0,100,100,0.00,0.00,1,"
        f"{option.stroke},0,7,0,0,0,1"
    )
    return [
        f"Style: Float{common}",
        f"Style: Bottom{common}",
        f"Style: Top{common}",
    ]


def _elem_to_danmu(elem: _ProtoMessage) -> Optional[_Danmu]:
    """将 protobuf DanmakuElem 转换为内部 _Danmu 表示。

    Args:
        elem: :class:`DanmakuElem` 实例。

    Returns:
        :class:`_Danmu` 实例，或 ``None``（如果模式不支持）。
    """
    mode = int(elem.mode)
    # 仅处理滚动(1) / 底部(4) / 顶部(5)，其他类型跳过
    if mode not in (_MODE_FLOAT, _MODE_BOTTOM, _MODE_TOP):
        return None
    color = int(elem.color)
    rgb = (
        (color >> 16) & 0xFF,
        (color >> 8) & 0xFF,
        color & 0xFF,
    )
    return _Danmu(
        timeline_s=float(elem.progress) / 1000.0,
        content=str(elem.content),
        mode=mode,
        rgb=rgb,
    )


def _build_canvas(option: DanmakuOption) -> _Canvas:
    """根据渲染选项构造画布，分配三组 lane 池。

    Args:
        option: 渲染选项。

    Returns:
        :class:`_Canvas` 实例，lane 池已按百分比分配。
    """
    float_count = int(
        option.float_percentage * ASS_PLAY_RES_Y / option.lane_size
    )
    bottom_count = int(
        option.bottom_percentage * ASS_PLAY_RES_Y / option.lane_size
    )
    # 至少 1 个 lane，避免空池导致所有弹幕被跳过
    float_count = max(1, float_count)
    bottom_count = max(1, bottom_count)
    return _Canvas(
        width=ASS_PLAY_RES_X,
        height=ASS_PLAY_RES_Y,
        option=option,
        float_lanes=[None] * float_count,
        top_lanes=[None] * bottom_count,
        bottom_lanes=[None] * bottom_count,
    )


def render_ass(
    danmaku_list: list[_ProtoMessage],
    duration_sec: int,
    option: Optional[DanmakuOption] = None,
) -> str:
    """将弹幕列表渲染为 ASS 字幕字符串。

    Args:
        danmaku_list: :class:`DanmakuElem` 列表，应按出现时间升序排序
            （:func:`fetch_danmaku` 已排序）。
        duration_sec: 视频时长（秒），仅用于 Script Info 元信息，不参与布局。
        option: 渲染选项，``None`` 使用默认 :class:`DanmakuOption`。

    Returns:
        ASS 字幕文件的完整字符串内容（含 ``[Script Info]`` /
        ``[V4+ Styles]`` / ``[Events]`` 三段）。

    Note:
        文件命名约定 ``.zh-CN.default.ass`` 由调用方拼路径，本函数只返回内容。
    """
    opt = option or DanmakuOption()
    canvas = _build_canvas(opt)

    # 逐条布局，生成 Drawable 列表
    drawables: list[_Drawable] = []
    for elem in danmaku_list:
        danmu = _elem_to_danmu(elem)
        if danmu is None:
            continue
        drawable = canvas.draw(danmu)
        if drawable is not None:
            drawables.append(drawable)

    # 拼装 ASS 文件
    styles = _build_styles(opt)
    header = (
        "[Script Info]\n"
        "; Script generated by bilibili-toolkit-builtin\n"
        "Title: Bilibili Danmaku\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {ASS_PLAY_RES_X}\n"
        f"PlayResY: {ASS_PLAY_RES_Y}\n"
        f"Aspect Ratio: {ASS_PLAY_RES_X}:{ASS_PLAY_RES_Y}\n"
        "Collisions: Normal\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n"
        "YCbCr Matrix: TV.601\n"
        "\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        + "\n".join(styles)
        + "\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )

    lines: list[str] = [header]
    for drawable in drawables:
        lines.append(_format_dialogue(drawable))

    return "".join(lines)


def _format_dialogue(drawable: _Drawable) -> str:
    """将单条 Drawable 格式化为 ASS Dialogue 行。

    Args:
        drawable: 已布局的弹幕。

    Returns:
        形如 ``Dialogue: 2,0:00:01.00,0:00:16.00,Float,,0,0,0,,{...}text\n``
        的 Dialogue 行。
    """
    start = _format_time(drawable.danmu.timeline_s)
    end = _format_time(drawable.danmu.timeline_s + drawable.duration)
    r, g, b = drawable.danmu.rgb
    # ASS 颜色 \c&HBBGGRR& （不含 alpha，alpha 由 style 控制）
    color_tag = f"\\c&H{b:02X}{g:02X}{r:02X}&"
    if drawable.style_name == "Float":
        x0, y0 = drawable.start
        x1, y1 = drawable.end
        effect = f"\\move({x0}, {y0}, {x1}, {y1})"
    else:
        # Top / Bottom 用 \pos 固定位置
        x0, y0 = drawable.start
        effect = f"\\pos({x0}, {y0})"
    text = _escape_text(drawable.danmu.content)
    return (
        f"Dialogue: 2,{start},{end},{drawable.style_name},,0,0,0,,"
        f"{{{effect}{color_tag}}}{text}\n"
    )


__all__ = [
    "ASS_PLAY_RES_X",
    "ASS_PLAY_RES_Y",
    "DanmakuOption",
    "render_ass",
]
