"""
PII 敏感信息过滤模块 — 跨层安全组件。
检测和清洗个人身份信息 (PII)，可用于日志脱敏、对话记录、行为日志等多个子系统。
"""
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class PiiDetectionResult:
    """PII 检测结果。"""
    has_pii: bool = False
    pii_types: list[str] = None
    pii_count: int = 0
    scrubbed_text: str = ""

    def __post_init__(self):
        if self.pii_types is None:
            self.pii_types = []


# PII 检测模式（按类别分组）
PII_PATTERNS = {
    # 中国身份证号 (18位)
    "cn_id_card": re.compile(
        r'\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b'
    ),
    # 中国手机号
    "cn_phone": re.compile(
        r'\b1[3-9]\d{9}\b'
    ),
    # 电子邮箱
    "email": re.compile(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    ),
    # 银行卡号 (Luhn 算法可验证，这里用宽松匹配)
    "bank_card": re.compile(
        r'\b\d{16,19}\b'
    ),
    # IPv4 地址
    "ipv4": re.compile(
        r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b'
    ),
    # IPv6 地址
    "ipv6": re.compile(
        r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b'
    ),
    # API Key 模式 (常见前缀)
    "api_key": re.compile(
        r'\b(?:sk-[A-Za-z0-9]{32,}|AKIA[A-Z0-9]{16}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9]{22,})'
    ),
    # 国内固定电话
    "cn_landline": re.compile(
        r'\b0\d{2,3}[-\s]?\d{7,8}\b'
    ),
    # 护照号码（宽松匹配）
    "passport": re.compile(
        r'\b[EeGgPpSsDd]\d{7,8}\b'
    ),
}

# 替换字符串
REPLACEMENTS = {
    "cn_id_card": "[身份证号已脱敏]",
    "cn_phone": "[手机号已脱敏]",
    "email": "[邮箱已脱敏]",
    "bank_card": "[银行卡号已脱敏]",
    "ipv4": "[IP已脱敏]",
    "ipv6": "[IPv6已脱敏]",
    "api_key": "[API密钥已脱敏]",
    "cn_landline": "[电话已脱敏]",
    "passport": "[护照号已脱敏]",
}


def detect_pii(text: str) -> list[tuple[str, str, int, int]]:
    """
    检测文本中的 PII 信息。
    返回 (类型, 匹配文本, 起始位置, 结束位置) 列表。
    """
    findings = []
    for pii_type, pattern in PII_PATTERNS.items():
        for match in pattern.finditer(text):
            findings.append((pii_type, match.group(), match.start(), match.end()))
    # 按位置排序
    findings.sort(key=lambda x: x[2])
    return findings


def scrub_pii(text: str) -> PiiDetectionResult:
    """
    清洗文本中的 PII 信息，用占位符替换。
    返回包含检测结果和清洗后文本的 PiiDetectionResult。
    """
    findings = detect_pii(text)
    if not findings:
        return PiiDetectionResult(scrubbed_text=text)

    # 从右向左替换以避免位置偏移
    result_text = text
    pii_types = []
    for pii_type, _, start, end in reversed(findings):
        replacement = REPLACEMENTS.get(pii_type, f"[{pii_type}已脱敏]")
        result_text = result_text[:start] + replacement + result_text[end:]
        if pii_type not in pii_types:
            pii_types.append(pii_type)

    return PiiDetectionResult(
        has_pii=True,
        pii_types=pii_types,
        pii_count=len(findings),
        scrubbed_text=result_text,
    )


def scrub_for_logging(text: str, max_length: int = 2000) -> str:
    """
    日志专用 PII 清洗函数。
    除 PII 脱敏外，还截断过长的文本。
    """
    result = scrub_pii(text)
    cleaned = result.scrubbed_text
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length] + "..."
    return cleaned


def sanitize_pii_in_dict(data: dict, keys_to_scrub: Optional[list[str]] = None) -> dict:
    """
    递归清洗字典中所有字符串值的 PII。
    可指定需要深度清洗的 key 列表。
    """
    if not isinstance(data, dict):
        return data

    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            # 对敏感 key 的内容进行深度清洗
            if keys_to_scrub and key in keys_to_scrub:
                result[key] = scrub_pii(value).scrubbed_text
            else:
                result[key] = value
        elif isinstance(value, dict):
            result[key] = sanitize_pii_in_dict(value, keys_to_scrub)
        elif isinstance(value, list):
            result[key] = [
                sanitize_pii_in_dict(item, keys_to_scrub) if isinstance(item, dict)
                else scrub_pii(item).scrubbed_text if isinstance(item, str)
                else item
                for item in value
            ]
        else:
            result[key] = value
    return result
