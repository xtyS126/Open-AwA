"""B 站字幕下载与 SRT 转换。

调用 ``/x/player/wbi/v2`` 获取视频字幕列表（WBI 签名），过滤 AI 字幕后
下载 JSON body 并转换为 SRT 格式落盘。多语言字幕分别保存为
``{base_name}.{lan}.srt``，单语言字幕保存为 ``{base_name}.srt``。

参考实现：``bili-sync/crates/bili_sync/src/bilibili/subtitle.rs`` 的
``SubTitleInfo`` / ``SubTitleBody`` / ``format_time``。

与 Rust 实现的差异：
- ``SubtitleInfo`` 额外携带 ``ai_type`` 字段，过滤时同时检查
  ``subtitle_url`` 是否包含 ``ai_subtitle`` 与 ``ai_type != 0``（双重判定）
- 字幕 body 通过独立 ``httpx.AsyncClient`` 拉取（CDN 链接，不走
  :class:`BilibiliClient` 的 base_url，无需 WBI 签名与风控检测）
- ``subtitle_url`` 以 ``//`` 开头时自动补全 ``https:`` 协议前缀
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from loguru import logger
from pydantic import BaseModel, Field

from .bilibili.client import BilibiliClient
from .bilibili.wbi import BilibiliAPIError

# 字幕列表端点路径（B 站 API 相对路径，base_url 已在 BilibiliClient 中配置）
SUBTITLE_LIST_ENDPOINT: str = "/x/player/wbi/v2"

# 字幕 body 下载请求超时（秒），字幕 JSON 通常较小
_SUBTITLE_BODY_TIMEOUT: float = 15.0

# 字幕 body 下载请求头：Referer 设置为 B 站主页以绕过基础防盗链
_SUBTITLE_REQUEST_HEADERS: dict[str, str] = {
    "Referer": "https://www.bilibili.com/",
}


class SubtitleInfo(BaseModel):
    """B 站字幕元信息。

    对应 ``/x/player/wbi/v2`` 响应中 ``data.subtitle.subtitles[]`` 元素。

    Attributes:
        lan: 语言代码，如 ``zh-CN`` / ``en-US``。
        subtitle_url: 字幕 JSON body URL（可能以 ``//`` 开头需补 ``https:``）。
        ai_type: AI 字幕标识，0=非 AI 字幕，1=AI 字幕（用于过滤）。
    """

    lan: str = Field(..., description="语言代码，如 zh-CN / en-US")
    subtitle_url: str = Field(..., description="字幕 JSON body URL")
    ai_type: int = Field(default=0, description="AI 字幕标识，0=非AI，1=AI")

    def is_ai_subtitle(self) -> bool:
        """判断是否为 AI 字幕。

        双重判定：
        1. ``subtitle_url`` 包含 ``ai_subtitle`` 字符串（与 Rust 实现一致，
           B 站 CDN 路径 ``/bfs/ai_subtitle/`` 标识 AI 生成字幕）
        2. ``ai_type != 0``（API 字段标识，作为兜底判定）

        任一条件满足即视为 AI 字幕，调用方应跳过。

        Returns:
            ``True`` 表示是 AI 字幕，应跳过；``False`` 表示是人工字幕。
        """
        return "ai_subtitle" in self.subtitle_url or self.ai_type != 0


async def get_subtitle_list(
    client: BilibiliClient,
    bvid: str,
    cid: int,
) -> list[SubtitleInfo]:
    """获取视频字幕列表。

    调用 ``GET /x/player/wbi/v2?bvid=&cid=``（WBI 签名），解析
    ``data.subtitle.subtitles[]`` 数组为 :class:`SubtitleInfo` 列表。

    风控检测由 :meth:`BilibiliClient.request` 内部的 :func:`check_response`
    自动完成，触发 412/403/-352/v_voucher 信号时抛出 :class:`RiskControlError`。

    Args:
        client: :class:`BilibiliClient` 实例。
        bvid: BV 号。
        cid: 分 P cid。

    Returns:
        :class:`SubtitleInfo` 列表（未过滤 AI 字幕）。无字幕时返回空列表。

    Raises:
        BilibiliAPIError: API 返回非零 code 或响应结构异常时抛出。
        RiskControlError: 触发风控时抛出。
    """
    payload = await client.request(
        method="GET",
        path=SUBTITLE_LIST_ENDPOINT,
        params={"bvid": bvid, "cid": cid},
        need_wbi=True,
    )
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise BilibiliAPIError(
            f"player/wbi/v2 响应 data 字段非对象: {type(data).__name__}"
        )
    subtitle_section = data.get("subtitle") or {}
    if not isinstance(subtitle_section, dict):
        raise BilibiliAPIError(
            f"player/wbi/v2 响应 subtitle 字段非对象: "
            f"{type(subtitle_section).__name__}"
        )
    raw_subtitles = subtitle_section.get("subtitles") or []
    if not isinstance(raw_subtitles, list):
        raise BilibiliAPIError(
            f"player/wbi/v2 响应 subtitles 字段非数组: "
            f"{type(raw_subtitles).__name__}"
        )
    return _parse_subtitles(raw_subtitles, bvid=bvid, cid=cid)


def _filter_ai_subtitles(subtitles: list[SubtitleInfo]) -> list[SubtitleInfo]:
    """过滤 AI 字幕，仅保留人工字幕。

    Args:
        subtitles: 原始字幕列表。

    Returns:
        过滤后的字幕列表（不包含 AI 字幕）。
    """
    return [sub for sub in subtitles if not sub.is_ai_subtitle()]


async def fetch_subtitle_body(
    client: BilibiliClient,
    subtitle_url: str,
) -> dict[str, Any]:
    """下载字幕 JSON body。

    字幕 URL 是 B 站 CDN 链接（如 ``https://aisubtitle.hdslb.com/...``），
    不走 :class:`BilibiliClient` 的 base_url，无需 WBI 签名与风控检测。
    使用独立 ``httpx.AsyncClient`` 直接 GET。

    ``subtitle_url`` 以 ``//`` 开头（协议相对 URL）时自动补全 ``https:`` 前缀。

    Args:
        client: :class:`BilibiliClient` 实例（仅用于复用 User-Agent，
            实际请求不走其 base_url）。
        subtitle_url: 字幕 JSON body URL。

    Returns:
        字幕 body dict，结构为 ``{"body": [{"from": <sec>, "to": <sec>,
        "content": "..."}]}``。

    Raises:
        httpx.HTTPError: 网络层异常或 HTTP 状态码非 2xx 时抛出。
        ValueError: 响应非 JSON 或非对象时抛出。
    """
    # 补全协议相对 URL（B 站 CDN 常返回 //aisubtitle.hdslb.com/... 形式）
    url: str = subtitle_url
    if url.startswith("//"):
        url = "https:" + url

    # 复用 client 的 User-Agent，保持与 B 站请求一致的指纹
    headers: dict[str, str] = {
        "User-Agent": client.user_agent,
        **_SUBTITLE_REQUEST_HEADERS,
    }

    async with httpx.AsyncClient(
        timeout=_SUBTITLE_BODY_TIMEOUT,
        headers=headers,
    ) as http_client:
        response = await http_client.get(url)
        response.raise_for_status()
        try:
            payload = response.json()
        except Exception as exc:
            raise ValueError(
                f"字幕 body 响应非 JSON: url={url}, status={response.status_code}"
            ) from exc

    if not isinstance(payload, dict):
        raise ValueError(
            f"字幕 body 响应 JSON 非对象: url={url}, type={type(payload).__name__}"
        )
    return payload


def to_srt(subtitle_body: dict[str, Any]) -> str:
    """将字幕 JSON body 转换为 SRT 格式字符串。

    遍历 ``body`` 数组，每条生成 4 行：
    1. 序号（从 0 开始，与 bili-sync Rust 实现一致）
    2. 时间区间：``HH:MM:SS,mmm --> HH:MM:SS,mmm``
    3. 字幕内容
    4. 空行（条目分隔）

    时间戳格式：秒数（float）→ ``HH:MM:SS,mmm``，毫秒部分取
    ``int((time - int(time)) * 1000)``，与 Rust ``format_time`` 行为一致
    （float 精度问题导致的几毫秒误差可接受）。

    Args:
        subtitle_body: 字幕 body dict，应包含 ``body`` 数组字段。

    Returns:
        SRT 格式字符串。空 body 时返回空字符串。
    """
    body = subtitle_body.get("body") or []
    if not isinstance(body, list):
        body = []

    parts: list[str] = []
    for idx, item in enumerate(body):
        if not isinstance(item, dict):
            continue
        from_sec = float(item.get("from", 0))
        to_sec = float(item.get("to", 0))
        content = str(item.get("content", ""))
        # 每个 part 末尾的 \n 与 join 的 \n 共同构成条目间空行
        parts.append(
            f"{idx}\n"
            f"{_format_time(from_sec)} --> {_format_time(to_sec)}\n"
            f"{content}\n"
        )
    return "\n".join(parts)


async def save_subtitle(
    client: BilibiliClient,
    bvid: str,
    cid: int,
    base_name: str,
    output_dir: Path,
) -> list[Path]:
    """下载并保存视频字幕为 SRT 文件。

    流程：
    1. 调用 :func:`get_subtitle_list` 获取字幕列表
    2. 调用 :func:`_filter_ai_subtitles` 过滤 AI 字幕
    3. 遍历剩余字幕，调用 :func:`fetch_subtitle_body` 拉取 JSON body
    4. 调用 :func:`to_srt` 转换为 SRT 格式
    5. 落盘：多语言时 ``{base_name}.{lan}.srt``，单语言时 ``{base_name}.srt``

    ``output_dir`` 不存在时自动创建（含父目录）。

    Args:
        client: :class:`BilibiliClient` 实例。
        bvid: BV 号。
        cid: 分 P cid。
        base_name: 文件名前缀（不含扩展名）。
        output_dir: 输出目录。

    Returns:
        已保存的 SRT 文件路径列表。无可用字幕（或全部被 AI 过滤）时返回空列表。

    Raises:
        BilibiliAPIError: 字幕列表 API 返回异常时抛出。
        RiskControlError: 触发风控时抛出。
        httpx.HTTPError: 字幕 body 下载网络层异常时抛出。
        ValueError: 字幕 body 响应非 JSON 时抛出。
    """
    # 确保输出目录存在
    output_dir.mkdir(parents=True, exist_ok=True)

    # 获取字幕列表并过滤 AI 字幕
    subtitles = await get_subtitle_list(client, bvid, cid)
    subtitles = _filter_ai_subtitles(subtitles)
    if not subtitles:
        logger.info(
            "无可用字幕（已过滤 AI 字幕）: bvid={}, cid={}",
            bvid,
            cid,
        )
        return []

    # 多语言时文件名带语言后缀，单语言时不带
    multi_lang: bool = len(subtitles) > 1
    saved_paths: list[Path] = []
    for sub in subtitles:
        body = await fetch_subtitle_body(client, sub.subtitle_url)
        srt_content = to_srt(body)
        if multi_lang:
            file_path = output_dir / f"{base_name}.{sub.lan}.srt"
        else:
            file_path = output_dir / f"{base_name}.srt"
        # 同步写入即可，SRT 文件通常较小（< 100KB），无需异步 I/O
        file_path.write_text(srt_content, encoding="utf-8")
        saved_paths.append(file_path)
        logger.debug(
            "字幕已保存: bvid={}, cid={}, lan={}, dest={}",
            bvid,
            cid,
            sub.lan,
            file_path,
        )

    logger.info(
        "字幕保存完成: bvid={}, cid={}, count={}",
        bvid,
        cid,
        len(saved_paths),
    )
    return saved_paths


def _parse_subtitles(
    raw_subtitles: list[Any],
    *,
    bvid: str,
    cid: int,
) -> list[SubtitleInfo]:
    """解析 ``data.subtitle.subtitles[]`` 数组为 :class:`SubtitleInfo` 列表。

    Args:
        raw_subtitles: 原始 subtitles 数组（list of dict）。
        bvid: BV 号（仅用于日志）。
        cid: 分 P cid（仅用于日志）。

    Returns:
        :class:`SubtitleInfo` 列表。跳过非 dict 元素与缺失 lan/subtitle_url 的条目。
    """
    result: list[SubtitleInfo] = []
    for raw in raw_subtitles:
        if not isinstance(raw, dict):
            continue
        lan = str(raw.get("lan") or "")
        subtitle_url = str(raw.get("subtitle_url") or "")
        if not lan or not subtitle_url:
            # lan 或 subtitle_url 缺失时跳过（无法定位字幕）
            continue
        ai_type = int(raw.get("ai_type") or 0)
        result.append(
            SubtitleInfo(
                lan=lan,
                subtitle_url=subtitle_url,
                ai_type=ai_type,
            )
        )
    logger.debug(
        "字幕列表解析完成: bvid={}, cid={}, total={}",
        bvid,
        cid,
        len(result),
    )
    return result


def _format_time(time: float) -> str:
    """将秒数（float）格式化为 SRT 时间戳 ``HH:MM:SS,mmm``。

    与 bili-sync Rust ``format_time`` 行为一致：
    - 秒部分取 ``int(time)`` 截断
    - 毫秒部分取 ``int((time - int(time)) * 1000)``，float 精度问题
      导致的几毫秒误差可接受（参考 Rust 实现注释）
    - 小时/分钟/秒通过整数除法计算，避免浮点累积误差

    Args:
        time: 秒数（可能含小数）。

    Returns:
        ``HH:MM:SS,mmm`` 格式字符串。小时数超过 99 时仍正常输出
        （如 360001.23 → ``100:00:01,229``）。
    """
    second_int = int(time)
    millisecond = int((time - second_int) * 1000)
    hour = second_int // 3600
    minute = (second_int % 3600) // 60
    second = second_int % 60
    return f"{hour:02d}:{minute:02d}:{second:02d},{millisecond:03d}"


__all__ = [
    "SUBTITLE_LIST_ENDPOINT",
    "SubtitleInfo",
    "fetch_subtitle_body",
    "get_subtitle_list",
    "save_subtitle",
    "to_srt",
]
