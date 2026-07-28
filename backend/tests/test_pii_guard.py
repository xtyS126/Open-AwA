"""
PII 脱敏模块单元测试。

覆盖 API key / 私钥 / 信用卡 / 身份证 / SSN 五类 PII 的正例、负例与边界情况。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.pii_guard import REDACTED_PLACEHOLDER, scan, scrub


class TestApiKeyScrub:
    """API key 脱敏正例与负例。"""

    def test_openai_api_key_redacted(self):
        content = "用户的 OpenAI key 是 sk-abc123def4567890abcdef1234567890"
        result = scrub(content)
        assert "sk-abc123def4567890abcdef1234567890" not in result
        assert REDACTED_PLACEHOLDER in result

    def test_anthropic_api_key_redacted(self):
        content = "请保存 sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"
        result = scrub(content)
        assert "sk-ant-api03" not in result
        assert REDACTED_PLACEHOLDER in result

    def test_deepseek_api_key_redacted(self):
        content = "DS key: ds-abcdefghijklmnopqrstuvwxyz0123456789"
        result = scrub(content)
        assert "ds-abcdefghijklmnopqrstuvwxyz0123456789" not in result
        assert REDACTED_PLACEHOLDER in result

    def test_short_string_not_redacted(self):
        # 长度不足 32 字符的 sk- 前缀不应误判
        content = "sk-abcd1234"
        result = scrub(content)
        assert result == content


class TestPrivateKeyScrub:
    """PEM 私钥块脱敏。"""

    def test_rsa_private_key_redacted(self):
        pem_block = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/ygWy0nM6m3b1J6x\n"
            "-----END RSA PRIVATE KEY-----"
        )
        content = f"私钥如下: {pem_block} 请妥善保存"
        result = scrub(content)
        assert "MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/ygWy0nM6m3b1J6x" not in result
        assert REDACTED_PLACEHOLDER in result

    def test_ec_private_key_redacted(self):
        pem_block = (
            "-----BEGIN EC PRIVATE KEY-----\n"
            "MHcCAQEEINvMyq5TF4Ny\n"
            "-----END EC PRIVATE KEY-----"
        )
        result = scrub(f"key={pem_block}")
        assert "MHcCAQEEINvMyq5TF4Ny" not in result
        assert REDACTED_PLACEHOLDER in result

    def test_non_pem_text_not_redacted(self):
        content = "BEGIN PRIVATE KEY 是私钥起始标记"
        result = scrub(content)
        assert result == content


class TestCreditCardScrub:
    """信用卡号脱敏（依赖 Luhn 校验）。"""

    def test_valid_visa_redacted(self):
        # 4111111111111111 是常见测试卡号，通过 Luhn 校验
        content = "信用卡号 4111111111111111 已绑定"
        result = scrub(content)
        assert "4111111111111111" not in result
        assert REDACTED_PLACEHOLDER in result

    def test_valid_mastercard_redacted(self):
        # 5555555555554444 是 Mastercard 测试卡号
        content = "5555 5555 5555 4444"
        result = scrub(content)
        assert "5555" not in result.replace(REDACTED_PLACEHOLDER, "")

    def test_invalid_card_not_redacted(self):
        # 不通过 Luhn 的随机数字串不应被脱敏
        content = "1234567890123456"
        result = scrub(content)
        assert result == content

    def test_short_digits_not_redacted(self):
        content = "订单号 12345"
        result = scrub(content)
        assert result == content


class TestIdCardScrub:
    """身份证号脱敏（依赖校验位）。"""

    def test_valid_id_card_redacted(self):
        # 110101199003078013 通过 GB 11643-1999 校验位计算
        content = "身份证号 110101199003078013"
        result = scrub(content)
        assert "110101199003078013" not in result
        assert REDACTED_PLACEHOLDER in result

    def test_invalid_id_card_not_redacted(self):
        # 末位校验位错误不应脱敏
        content = "123456789012345678"
        result = scrub(content)
        assert result == content

    def test_short_digits_not_redacted(self):
        content = "工号 123456"
        result = scrub(content)
        assert result == content


class TestSSNScrub:
    """SSN 脱敏。"""

    def test_valid_ssn_redacted(self):
        content = "SSN: 123-45-6789"
        result = scrub(content)
        assert "123-45-6789" not in result
        assert REDACTED_PLACEHOLDER in result

    def test_zero_ssn_not_redacted(self):
        content = "000-00-0000"
        result = scrub(content)
        assert result == content

    def test_invalid_area_ssn_not_redacted(self):
        # 666 区域号不分配
        content = "666-12-3456"
        result = scrub(content)
        assert result == content

    def test_invalid_format_not_redacted(self):
        content = "123456789"
        result = scrub(content)
        assert result == content


class TestCombinedAndEdgeCases:
    """组合 PII 与边界情况。"""

    def test_no_pii_unchanged(self):
        content = "用户喜欢 Python 编程语言，常在后端使用 FastAPI"
        assert scrub(content) == content

    def test_empty_string(self):
        assert scrub("") == ""

    def test_none_input_unchanged(self):
        assert scrub(None) is None

    def test_non_string_input_unchanged(self):
        assert scrub(12345) == 12345

    def test_multiple_pii_combined(self):
        content = (
            "API key sk-abc123def4567890abcdef1234567890 已泄露，"
            "信用卡 4111111111111111 也需要重置，"
            "身份证 110101199003078013 已记录"
        )
        result = scrub(content)
        assert "sk-abc123def4567890abcdef1234567890" not in result
        assert "4111111111111111" not in result
        assert "110101199003078013" not in result
        assert result.count(REDACTED_PLACEHOLDER) >= 3

    def test_pii_in_chinese_context(self):
        content = "用户的 OpenAI key 是 sk-abc123def4567890abcdef1234567890"
        result = scrub(content)
        assert "用户的 OpenAI key 是" in result
        assert REDACTED_PLACEHOLDER in result

    def test_scan_returns_hits(self):
        content = "sk-abc123def4567890abcdef1234567890 and 4111111111111111"
        hits = scan(content)
        assert len(hits) == 2
        assert any("sk-abc123" in hit for hit in hits)
        assert any("4111111111111111" in hit for hit in hits)

    def test_scan_empty_for_no_pii(self):
        assert scan("普通文本无敏感信息") == []
