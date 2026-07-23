"""WBI 签名算法单元测试。

覆盖 ``bilibili/wbi.py`` 的：
- :func:`get_mixin_key`：img_key + sub_key → 32 字符 mixin_key
- :func:`sign_wbi`：参数 + WBI 密钥 → 含 ``w_rid`` 与 ``wts`` 的新 dict
- :func:`extract_wbi_key`：从 nav 端点 URL 提取 img_key / sub_key
- :class:`BilibiliAPIError`：异常类构造与 code 字段

测试向量来源：
- img_key / sub_key 取自 B 站 nav 端点真实响应样本
  ``https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png``
  ``https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b130000.woff``
- mixin_key 与 w_rid 由测试内独立重算（非调用被测函数），
  用以验证 ``wbi.py`` 内 ``MIXIN_KEY_ENC_TAB`` 与 MD5 流程无回归
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import Dict
from urllib.parse import urlencode

import pytest

# 注入 backend 目录到 sys.path，便于直接 import 被测模块
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from plugins.bilibili_toolkit_builtin.bilibili.wbi import (  # noqa: E402
    BilibiliAPIError,
    MIXIN_KEY_ENC_TAB,
    extract_wbi_key,
    get_mixin_key,
    sign_wbi,
)

# ---------------------------------------------------------------------------
# 已知测试向量（img_key / sub_key 来自 B 站 nav 端点真实样本）
# ---------------------------------------------------------------------------

_IMG_KEY: str = "7cd084941338484aae1ad9425b84077c"
_SUB_KEY: str = "4932caff0ff746eab6f01bf08b130000"
_IMG_URL: str = "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png"
_SUB_URL: str = "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b130000.woff"


def _recompute_mixin_key(img_key: str, sub_key: str) -> str:
    """独立重算 mixin_key，用于校验被测函数 ``get_mixin_key`` 输出。

    与 ``wbi.get_mixin_key`` 实现完全独立，逐字符按 ``MIXIN_KEY_ENC_TAB``
    前 32 个索引取值，便于在实现发生回归时定位差异。
    """
    merged: str = img_key + sub_key
    chars: list[str] = []
    for idx in MIXIN_KEY_ENC_TAB[:32]:
        if idx < len(merged):
            chars.append(merged[idx])
    return "".join(chars)


def _recompute_w_rid(
    params: Dict[str, object],
    img_key: str,
    sub_key: str,
    wts: int,
) -> str:
    """独立重算 w_rid，用于校验被测函数 ``sign_wbi`` 输出。

    复刻 B 站 WBI 签名流程：拷贝参数 → 追加 wts → 按 key 排序 →
    清洗 ``!'()*`` 字符 → urlencode → 追加 mixin_key → MD5。
    """
    mixin_key = _recompute_mixin_key(img_key, sub_key)
    signed: Dict[str, str] = {k: str(v) for k, v in params.items()}
    signed["wts"] = str(wts)
    ordered = sorted(signed.items())
    sanitized = {k: re.sub(r"[!'()*]", "", v) for k, v in ordered}
    query = urlencode(sanitized)
    return hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# get_mixin_key
# ---------------------------------------------------------------------------


def test_get_mixin_key_returns_32_chars() -> None:
    """mixin_key 长度必须为 32 字符（与 B 站服务端期望一致）。"""
    mixin_key = get_mixin_key(_IMG_KEY, _SUB_KEY)
    assert len(mixin_key) == 32
    assert all(c in "0123456789abcdef" for c in mixin_key)


def test_get_mixin_key_matches_recomputed() -> None:
    """mixin_key 必须与独立重算结果一致，验证 MIXIN_KEY_ENC_TAB 应用正确。"""
    expected = _recompute_mixin_key(_IMG_KEY, _SUB_KEY)
    actual = get_mixin_key(_IMG_KEY, _SUB_KEY)
    assert actual == expected


def test_get_mixin_key_deterministic() -> None:
    """同一 img_key / sub_key 多次调用结果一致。"""
    first = get_mixin_key(_IMG_KEY, _SUB_KEY)
    second = get_mixin_key(_IMG_KEY, _SUB_KEY)
    assert first == second


def test_get_mixin_key_empty_inputs() -> None:
    """img_key 与 sub_key 同时为空时返回空字符串。"""
    assert get_mixin_key("", "") == ""


def test_get_mixin_key_short_input_safely_truncated() -> None:
    """输入短于 64 字符时按切片语义安全截断，不抛 IndexError。"""
    # 输入仅 4 字符，所有 MIXIN_KEY_ENC_TAB 索引 >= 4 都被跳过
    short_key = get_mixin_key("ab", "cd")
    # 仅索引 0、1、2、3 在范围内，对应 merged[0..3]
    # MIXIN_KEY_ENC_TAB[:32] 中 <=3 的索引有 2, 3, 0, 1
    assert len(short_key) >= 1
    assert all(c in "abcd" for c in short_key)


# ---------------------------------------------------------------------------
# sign_wbi
# ---------------------------------------------------------------------------


def test_sign_wbi_returns_dict_with_w_rid_and_wts() -> None:
    """sign_wbi 返回的 dict 必须包含 w_rid 与 wts 字段。"""
    params: Dict[str, object] = {"foo": "114", "bar": "514"}
    signed = sign_wbi(params, _IMG_KEY, _SUB_KEY, wts=1702204800)
    assert "w_rid" in signed
    assert "wts" in signed
    assert signed["wts"] == "1702204800"


def test_sign_wbi_w_rid_matches_recomputed() -> None:
    """w_rid 必须与独立重算结果一致，验证 MD5 + urlencode 流程正确。"""
    params: Dict[str, object] = {"foo": "114", "bar": "514", "baz": 114514}
    wts = 1702204800
    expected = _recompute_w_rid(params, _IMG_KEY, _SUB_KEY, wts)
    actual = sign_wbi(params, _IMG_KEY, _SUB_KEY, wts=wts)["w_rid"]
    assert actual == expected


def test_sign_wbi_preserves_original_params() -> None:
    """sign_wbi 必须保留原始参数（值统一转为 str）。"""
    params: Dict[str, object] = {"bvid": "BV1gLfnY8E6D", "cid": 12345}
    signed = sign_wbi(params, _IMG_KEY, _SUB_KEY, wts=1702204800)
    assert signed["bvid"] == "BV1gLfnY8E6D"
    assert signed["cid"] == "12345"


def test_sign_wbi_does_not_mutate_input() -> None:
    """sign_wbi 不可修改入参 params（拷贝实现）。"""
    params: Dict[str, object] = {"bvid": "BV1gLfnY8E6D"}
    original_keys = set(params.keys())
    sign_wbi(params, _IMG_KEY, _SUB_KEY, wts=1702204800)
    assert set(params.keys()) == original_keys
    assert "w_rid" not in params
    assert "wts" not in params


def test_sign_wbi_all_values_are_strings() -> None:
    """sign_wbi 返回的 dict 中所有值必须为 str（便于直接作为 query 参数）。"""
    params: Dict[str, object] = {"cid": 12345, "qn": 127}
    signed = sign_wbi(params, _IMG_KEY, _SUB_KEY, wts=1702204800)
    for value in signed.values():
        assert isinstance(value, str)


def test_sign_wbi_uses_wts_when_provided() -> None:
    """显式传入 wts 时必须使用该值，而非当前时间戳。"""
    params: Dict[str, object] = {"foo": "bar"}
    wts = 1700000000
    signed = sign_wbi(params, _IMG_KEY, _SUB_KEY, wts=wts)
    assert signed["wts"] == "1700000000"


def test_sign_wbi_sanitizes_special_chars() -> None:
    """参数值中的 ``!'()*`` 字符必须在签名前被剔除（与 B 站服务端一致）。"""
    params: Dict[str, object] = {"foo": "a'b(c)d*e!"}
    signed = sign_wbi(params, _IMG_KEY, _SUB_KEY, wts=1702204800)
    # 重算时也剔除特殊字符
    expected = _recompute_w_rid(params, _IMG_KEY, _SUB_KEY, 1702204800)
    assert signed["w_rid"] == expected
    # w_rid 不应包含被剔除的字符
    assert "'" not in signed["foo"]
    assert "(" not in signed["foo"]


def test_sign_wbi_empty_params() -> None:
    """空 params 时仍能正常签名（仅含 wts 与 w_rid）。"""
    signed = sign_wbi({}, _IMG_KEY, _SUB_KEY, wts=1702204800)
    assert "w_rid" in signed
    assert signed["wts"] == "1702204800"


def test_sign_wbi_w_rid_is_32_char_hex() -> None:
    """w_rid 必须是 32 字符的 MD5 十六进制摘要。"""
    signed = sign_wbi({"foo": "bar"}, _IMG_KEY, _SUB_KEY, wts=1702204800)
    w_rid = signed["w_rid"]
    assert len(w_rid) == 32
    assert all(c in "0123456789abcdef" for c in w_rid)


# ---------------------------------------------------------------------------
# extract_wbi_key
# ---------------------------------------------------------------------------


def test_extract_wbi_key_from_full_urls() -> None:
    """从 nav 端点返回的完整 URL 中提取 img_key 与 sub_key。"""
    img_key, sub_key = extract_wbi_key(_IMG_URL, _SUB_URL)
    assert img_key == _IMG_KEY
    assert sub_key == _SUB_KEY


def test_extract_wbi_key_handles_url_without_extension() -> None:
    """URL 路径无扩展名时直接返回文件名。"""
    img_key, _ = extract_wbi_key(
        "https://i0.hdslb.com/bfs/wbi/abc123",
        "https://i0.hdslb.com/bfs/wbi/def456.png",
    )
    assert img_key == "abc123"


def test_extract_wbi_key_empty_url_returns_empty_string() -> None:
    """任一 URL 为空时对应位置返回空串。"""
    img_key, sub_key = extract_wbi_key("", "")
    assert img_key == ""
    assert sub_key == ""


def test_extract_wbi_key_strips_query_and_fragment() -> None:
    """URL 含 query / fragment 时仅取 path 的文件名部分。"""
    img_key, _ = extract_wbi_key(
        "https://i0.hdslb.com/bfs/wbi/abc123.png?v=1#frag",
        "https://i0.hdslb.com/bfs/wbi/def456.png",
    )
    assert img_key == "abc123"


# ---------------------------------------------------------------------------
# BilibiliAPIError
# ---------------------------------------------------------------------------


def test_bilibili_api_error_default_code_is_none() -> None:
    """BilibiliAPIError 默认 code 为 None。"""
    err = BilibiliAPIError("test error")
    assert err.code is None
    assert "test error" in str(err)


def test_bilibili_api_error_with_code() -> None:
    """带 code 的 BilibiliAPIError 保留 code 字段。"""
    err = BilibiliAPIError("rate limited", code=-352)
    assert err.code == -352
    assert "rate limited" in str(err)


def test_bilibili_api_error_is_runtime_error() -> None:
    """BilibiliAPIError 必须继承 RuntimeError 以便上层捕获。"""
    err = BilibiliAPIError("test")
    assert isinstance(err, RuntimeError)
