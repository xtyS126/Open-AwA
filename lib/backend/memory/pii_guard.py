"""
PII 脱敏模块。

借鉴 openhanako 的 pii-guard.js 设计，在长期记忆写入前对敏感信息脱敏，
将 API key / 私钥 / 信用卡 / 身份证 / SSN 五类 PII 替换为 [REDACTED]，
避免用户隐私数据被嵌入向量库后被检索泄露。

设计要点：
- 纯函数 + 无副作用，便于单元测试与并发调用
- 使用正则匹配，避免引入重依赖（如 LLM 二次确认）
- 不修改原字符串语义结构，仅替换敏感字段，保留上下文可读性
- 对 Luhn 校验通过的信用卡号、合法身份证校验位才脱敏，避免误伤普通数字串
"""

from __future__ import annotations

import re
from typing import List, Tuple

# 脱敏占位符
REDACTED_PLACEHOLDER = "[REDACTED]"


# ---------- 正则定义 ----------

# API key：sk- / sk_ / sk-ant- / sk-or- 等前缀 + 32 位以上字母数字
# 兼容 OpenAI / Anthropic / OpenRouter / DeepSeek 等主流服务
API_KEY_PATTERN = re.compile(
    r"\b(?:sk-(?:ant-)?(?:proj-)?|sk_|sk-or-|sk-or-v1-|ds-|deepseek-|rk-)"
    r"[A-Za-z0-9_\-]{32,}\b",
    re.IGNORECASE,
)

# PEM 格式私钥：BEGIN ... PRIVATE KEY ... END ... PRIVATE KEY
PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----.*?"
    r"-----END (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----",
    re.DOTALL,
)

# 信用卡号：13-19 位连续数字（可能含 - 或空格分隔）
_CREDIT_CARD_CANDIDATE_PATTERN = re.compile(
    r"\b(?:\d[ \-]?){13,19}\b"
)

# 身份证号：18 位，前 17 位数字 + 末位数字或 X
_ID_CARD_PATTERN = re.compile(
    r"\b\d{17}[\dXx]\b"
)

# SSN：XXX-XX-XXXX 格式
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


# ---------- 校验函数 ----------

def _luhn_check(number: str) -> bool:
    """Luhn 算法校验信用卡号是否合法。"""
    digits = [int(ch) for ch in number if ch.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    parity = len(digits) % 2
    for idx, digit in enumerate(digits):
        if idx % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _id_card_check(id_number: str) -> bool:
    """中国大陆身份证号校验位检查（GB 11643-1999）。"""
    if len(id_number) != 18:
        return False
    if not id_number[:17].isdigit():
        return False
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_codes = "10X98765432"
    total = sum(int(id_number[i]) * weights[i] for i in range(17))
    expected = check_codes[total % 11]
    return id_number[-1].upper() == expected


# ---------- 主入口 ----------

def _redact_credit_cards(content: str) -> Tuple[str, List[str]]:
    """脱敏信用卡号（需通过 Luhn 校验）。"""
    matches: List[str] = []
    redacted = content

    def _replace(match: re.Match) -> str:
        raw = match.group(0)
        digits_only = re.sub(r"[^\d]", "", raw)
        if _luhn_check(digits_only):
            matches.append(raw)
            return REDACTED_PLACEHOLDER
        return raw

    redacted = _CREDIT_CARD_CANDIDATE_PATTERN.sub(_replace, redacted)
    return redacted, matches


def _redact_id_cards(content: str) -> Tuple[str, List[str]]:
    """脱敏中国大陆身份证号（需通过校验位检查）。"""
    matches: List[str] = []
    redacted = content

    def _replace(match: re.Match) -> str:
        raw = match.group(0)
        if _id_card_check(raw):
            matches.append(raw)
            return REDACTED_PLACEHOLDER
        return raw

    redacted = _ID_CARD_PATTERN.sub(_replace, redacted)
    return redacted, matches


def _redact_ssns(content: str) -> Tuple[str, List[str]]:
    """脱敏美国 SSN（XXX-XX-XXXX）。"""
    matches: List[str] = []
    redacted = content

    def _replace(match: re.Match) -> str:
        raw = match.group(0)
        # 简单校验：避免全 0、连续相同数字等明显伪造值
        area, group, serial = raw.split("-")
        if area == "000" or group == "00" or serial == "0000":
            return raw
        if area == "666" or area.startswith("9"):
            # 666 与 900-999 在 SSA 历史上不分配
            return raw
        matches.append(raw)
        return REDACTED_PLACEHOLDER

    redacted = _SSN_PATTERN.sub(_replace, redacted)
    return redacted, matches


def _redact_api_keys(content: str) -> Tuple[str, List[str]]:
    """脱敏主流 AI 服务的 API key。"""
    matches: List[str] = []
    redacted = content

    def _replace(match: re.Match) -> str:
        raw = match.group(0)
        matches.append(raw)
        return REDACTED_PLACEHOLDER

    redacted = API_KEY_PATTERN.sub(_replace, redacted)
    return redacted, matches


def _redact_private_keys(content: str) -> Tuple[str, List[str]]:
    """脱敏 PEM 格式私钥块。"""
    matches: List[str] = []
    redacted = content

    def _replace(match: re.Match) -> str:
        raw = match.group(0)
        matches.append(raw)
        return REDACTED_PLACEHOLDER

    redacted = PRIVATE_KEY_PATTERN.sub(_replace, redacted)
    return redacted, matches


def scrub(content: str) -> str:
    """
    对输入内容执行 PII 脱敏，返回脱敏后的字符串。

    支持五类 PII：API key / PEM 私钥 / 信用卡号 / 身份证号 / SSN。
    对信用卡号与身份证号执行校验位检查，避免误伤普通数字串。

    Args:
        content: 原始文本内容。

    Returns:
        脱敏后的文本，敏感字段被替换为 ``[REDACTED]``。
        若 ``content`` 为空或非字符串，原样返回。
    """
    if not isinstance(content, str) or not content:
        return content

    redacted = content
    # 顺序：先 PEM（最长）→ API key → 信用卡 → 身份证 → SSN
    # 避免信用卡正则吃掉 PEM 块中数字片段
    redacted, _ = _redact_private_keys(redacted)
    redacted, _ = _redact_api_keys(redacted)
    redacted, _ = _redact_credit_cards(redacted)
    redacted, _ = _redact_id_cards(redacted)
    redacted, _ = _redact_ssns(redacted)
    return redacted


def scan(content: str) -> List[str]:
    """
    扫描内容中命中的 PII 原文（不脱敏），用于审计与测试。

    Args:
        content: 原始文本。

    Returns:
        命中的 PII 字段列表，按检测顺序排列。无 PII 时返回空列表。
    """
    if not isinstance(content, str) or not content:
        return []

    hits: List[str] = []
    _, private_keys = _redact_private_keys(content)
    hits.extend(private_keys)
    _, api_keys = _redact_api_keys(content)
    hits.extend(api_keys)
    _, cards = _redact_credit_cards(content)
    hits.extend(cards)
    _, ids = _redact_id_cards(content)
    hits.extend(ids)
    _, ssns = _redact_ssns(content)
    hits.extend(ssns)
    return hits
