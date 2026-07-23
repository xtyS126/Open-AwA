"""B 站 WBI 请求签名算法。

WBI 是 B 站用于部分 Web API 请求参数的反爬签名机制：
1. 从 ``/x/web-interface/nav`` 端点获取 ``wbi_img.img_url`` 与 ``sub_url``，
   截取文件名部分得到 ``img_key`` 与 ``sub_key``。
2. 将 ``img_key + sub_key`` 拼接为 64 字符串，按
   :data:`MIXIN_KEY_ENC_TAB` 表置换并取前 32 字符，得到 ``mixin_key``。
3. 请求参数追加 ``wts`` 时间戳，按键排序后 URL 编码为查询串，
   ``w_rid = MD5(查询串 + mixin_key)``。

参考实现：
- ``bili-sync/crates/bili_sync/src/bilibili/credential.rs``（WbiImg::into_mixin_key）
- ``bili-sync/crates/bili_sync/src/bilibili/mod.rs``（sign_request）
- vendored ``openbiliclaw/bilibili/api.py`` 的 ``_WBI_MIXIN_KEY_ENC_TAB``

由于 vendored 实现以私有类方法（``_`` 前缀）形式绑定在
``BilibiliAPIClient`` 上，不便直接 import 复用，本模块采用独立重写，
算法与表值与 vendored / bili-sync 保持一致。
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any
from urllib.parse import urlparse, urlencode

# MIXIN_KEY_ENC_TAB：64 个索引，描述 mixin_key 字符置换顺序。
# 与 bili-sync credential.rs / vendored openbiliclaw api.py 完全一致。
MIXIN_KEY_ENC_TAB: list[int] = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

# WBI 签名前需要从参数值中剔除的特殊字符。
# B 站服务端在计算 w_rid 时会先去除这些字符再做 URL 编码，
# 因此客户端必须保持一致，否则签名失败。
_WBI_SANITIZE_PATTERN = re.compile(r"[!'()*]")


def get_mixin_key(img_key: str, sub_key: str) -> str:
    """从 img_key 与 sub_key 计算 mixin_key。

    将 ``img_key + sub_key`` 拼接为 64 字符串后，按
    :data:`MIXIN_KEY_ENC_TAB` 表置换取前 32 字符。

    Args:
        img_key: 从 nav ``wbi_img.img_url`` 截取的文件名（不含扩展名）。
        sub_key: 从 nav ``wbi_img.sub_url`` 截取的文件名（不含扩展名）。

    Returns:
        32 字符的 mixin_key。如果输入过短导致置换越界，会返回
        实际长度的子串（但仍按 64 字符表置换前 32 个索引）。
    """
    merged = img_key + sub_key
    if not merged:
        return ""
    # 仅取前 32 个索引；输入短于 64 字符时按 Python 切片语义安全截断
    return "".join(merged[i] for i in MIXIN_KEY_ENC_TAB[:32] if i < len(merged))


def sign_wbi(
    params: dict[str, Any],
    img_key: str,
    sub_key: str,
    *,
    wts: int | None = None,
) -> dict[str, str]:
    """对请求参数进行 WBI 签名。

    流程：
    1. 拷贝 ``params``，追加 ``wts`` 时间戳（默认当前时间）。
    2. 按 key 排序。
    3. 剔除每个值中的 ``!'()*`` 字符。
    4. URL 编码为查询串。
    5. ``w_rid = MD5(查询串 + mixin_key)``。
    6. 返回包含 ``w_rid`` 与 ``wts`` 的新 dict（其他参数一并返回）。

    Args:
        params: 原始请求参数（dict，值可以是任意可被 ``str()`` 转换的类型）。
        img_key: 从 nav 端点获取的 img_key。
        sub_key: 从 nav 端点获取的 sub_key。
        wts: 可选的时间戳覆盖（用于测试或重放），默认 ``int(time.time())``。

    Returns:
        新的 dict，包含原始参数 + ``wts`` + ``w_rid``，所有值均为字符串。
    """
    mixin_key = get_mixin_key(img_key, sub_key)
    timestamp = int(time.time()) if wts is None else int(wts)
    # 拷贝避免修改入参；值统一转 str 以便后续处理
    signed: dict[str, str] = {key: str(value) for key, value in params.items()}
    signed["wts"] = str(timestamp)
    # 按 key 排序后再做值清洗，确保与 B 站服务端计算顺序一致
    ordered = sorted(signed.items())
    sanitized = {
        key: _WBI_SANITIZE_PATTERN.sub("", value)
        for key, value in ordered
    }
    query = urlencode(sanitized)
    w_rid = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    sanitized["w_rid"] = w_rid
    return sanitized


def extract_wbi_key(img_url: str, sub_url: str) -> tuple[str, str]:
    """从 nav 端点返回的图片 URL 中提取 img_key 与 sub_key。

    形如 ``https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png``
    的 URL，提取文件名（去掉路径与 ``.png`` 扩展名）作为 key。

    Args:
        img_url: nav ``data.wbi_img.img_url``。
        sub_url: nav ``data.wbi_img.sub_url``。

    Returns:
        ``(img_key, sub_key)`` 元组。任一 URL 为空或无文件名时对应位置返回空串。
    """
    return _extract_filename(img_url), _extract_filename(sub_url)


def _extract_filename(url: str) -> str:
    """从 URL 中提取文件名（去掉路径与扩展名）。"""
    if not url:
        return ""
    path = urlparse(url).path
    filename = path.rsplit("/", 1)[-1]
    if "." not in filename:
        return filename
    return filename.rsplit(".", 1)[0]


async def get_wbi_keys(client: "httpx.AsyncClient") -> tuple[str, str]:  # type: ignore[name-defined]
    """调用 ``/x/web-interface/nav`` 获取 img_key 与 sub_key。

    Args:
        client: 已配置好 Cookie/UA 的 httpx.AsyncClient 实例。

    Returns:
        ``(img_key, sub_key)`` 元组。

    Raises:
        BilibiliAPIError: 当 nav 返回非零 code 或 wbi_img 缺失时抛出。
    """
    # 延迟 import 避免循环依赖
    from .risk_control import check_response

    response = await client.get("https://api.bilibili.com/x/web-interface/nav")
    check_response(response)
    payload = response.json()
    data = payload.get("data") or {}
    wbi_img = data.get("wbi_img") or {}
    img_url = str(wbi_img.get("img_url", "") or "")
    sub_url = str(wbi_img.get("sub_url", "") or "")
    img_key, sub_key = extract_wbi_key(img_url, sub_url)
    if not img_key or not sub_key:
        raise BilibiliAPIError(
            f"nav 返回的 wbi_img 缺失 img_url 或 sub_url: img_url={img_url!r}, sub_url={sub_url!r}"
        )
    return img_key, sub_key


class BilibiliAPIError(RuntimeError):
    """B 站 API 调用失败时抛出的通用异常。"""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code: int | None = code
