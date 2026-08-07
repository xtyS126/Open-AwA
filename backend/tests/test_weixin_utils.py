"""
微信工具函数共享模块单元测试。

覆盖 core.weixin_utils 中的三个工具函数：
- normalize_binding_status
- deserialize_skill_config
- validate_qrcode_url
"""

import json
import pytest

from core.weixin_utils import (
    normalize_binding_status,
    deserialize_skill_config,
    validate_qrcode_url,
    WEIXIN_QR_ALLOWED_DOMAINS,
)


# ---------------------------------------------------------------------------
# normalize_binding_status 测试
# ---------------------------------------------------------------------------

class TestNormalizeBindingStatus:
    """测试绑定状态规范化函数。"""

    # -- 已绑定状态映射 --

    @pytest.mark.parametrize("raw", ["bound", "confirmed", "linked", "success", "succeeded"])
    def test_bound_aliases_return_bound(self, raw: str) -> None:
        assert normalize_binding_status(raw) == "bound"

    @pytest.mark.parametrize("raw", ["Bound", "CONFIRMED", " Linked ", "SUCCESS"])
    def test_bound_aliases_case_insensitive_and_stripped(self, raw: str) -> None:
        assert normalize_binding_status(raw) == "bound"

    # -- 待确认状态映射 --

    @pytest.mark.parametrize("raw", ["pending", "confirming", "waiting"])
    def test_pending_aliases_return_pending(self, raw: str) -> None:
        assert normalize_binding_status(raw) == "pending"

    # -- 未绑定 / 空值 --

    @pytest.mark.parametrize("raw", ["unbound", "failed", "none", ""])
    def test_unbound_without_user_id_returns_fallback(self, raw: str) -> None:
        assert normalize_binding_status(raw) == "unbound"

    @pytest.mark.parametrize("raw", ["unbound", "failed", "none", ""])
    def test_unbound_with_user_id_returns_bound(self, raw: str) -> None:
        assert normalize_binding_status(raw, user_id="wx_user_123") == "bound"

    def test_none_input_returns_fallback(self) -> None:
        assert normalize_binding_status(None) == "unbound"

    def test_none_input_with_user_id_returns_bound(self) -> None:
        assert normalize_binding_status(None, user_id="wx_user_123") == "bound"

    # -- 自定义 fallback --

    def test_custom_fallback_without_user_id(self) -> None:
        assert normalize_binding_status("unknown_status", fallback="custom") == "custom"

    def test_custom_fallback_ignored_when_user_id_present(self) -> None:
        assert normalize_binding_status("unknown_status", user_id="uid", fallback="custom") == "bound"

    # -- 未知状态 --

    def test_unknown_status_without_user_id_returns_default_fallback(self) -> None:
        assert normalize_binding_status("something_weird") == "unbound"

    def test_unknown_status_with_user_id_returns_bound(self) -> None:
        assert normalize_binding_status("something_weird", user_id="uid") == "bound"


# ---------------------------------------------------------------------------
# deserialize_skill_config 测试
# ---------------------------------------------------------------------------

class TestDeserializeSkillConfig:
    """测试技能配置反序列化函数。"""

    def test_dict_input_returns_copy(self) -> None:
        original = {"key": "value"}
        result = deserialize_skill_config(original)
        assert result == original
        assert result is not original  # 确认返回副本

    def test_none_returns_empty_dict(self) -> None:
        assert deserialize_skill_config(None) == {}

    def test_empty_string_returns_empty_dict(self) -> None:
        assert deserialize_skill_config("") == {}

    def test_whitespace_only_returns_empty_dict(self) -> None:
        assert deserialize_skill_config("   ") == {}

    def test_json_string_parsed(self) -> None:
        data = {"account_id": "test", "token": "abc"}
        result = deserialize_skill_config(json.dumps(data))
        assert result == data

    def test_json_string_with_whitespace(self) -> None:
        data = {"key": "val"}
        result = deserialize_skill_config(f"  {json.dumps(data)}  ")
        assert result == data

    def test_yaml_string_parsed(self) -> None:
        yaml_text = "account_id: test_id\ntoken: secret"
        result = deserialize_skill_config(yaml_text)
        assert result == {"account_id": "test_id", "token": "secret"}

    def test_invalid_string_raises(self) -> None:
        # 既不是合法 JSON 也不是合法 YAML，应抛异常而非静默返回空字典
        with pytest.raises(ValueError):
            deserialize_skill_config("not json or yaml: [unterminated")

    def test_json_non_dict_raises(self) -> None:
        # JSON 解析成功但不是 dict，属于数据损坏，应抛异常
        with pytest.raises(ValueError):
            deserialize_skill_config("[1, 2, 3]")

    def test_json_integer_raises(self) -> None:
        # 合法 JSON 但不是字典，应抛异常
        with pytest.raises(ValueError):
            deserialize_skill_config(42)

    def test_json_list_raises(self) -> None:
        # 传入列表不是字典，应抛异常
        with pytest.raises(ValueError):
            deserialize_skill_config([1, 2])

    def test_nested_json(self) -> None:
        data = {"weixin": {"account_id": "a1", "nested": {"deep": True}}}
        result = deserialize_skill_config(json.dumps(data))
        assert result == data


# ---------------------------------------------------------------------------
# validate_qrcode_url 测试
# ---------------------------------------------------------------------------

class TestValidateQrcodeUrl:
    """测试二维码 URL 安全校验函数。"""

    def test_valid_https_url_returns_normalized(self) -> None:
        url = "https://mmbiz.qpic.cn/qr_code.png"
        assert validate_qrcode_url(url) == url

    def test_strips_whitespace(self) -> None:
        url = "  https://wx.qq.com/img.png  "
        assert validate_qrcode_url(url) == "https://wx.qq.com/img.png"

    @pytest.mark.parametrize("domain", sorted(WEIXIN_QR_ALLOWED_DOMAINS))
    def test_all_whitelisted_domains_accepted(self, domain: str) -> None:
        url = f"https://{domain}/test.png"
        assert validate_qrcode_url(url) == url

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="为空"):
            validate_qrcode_url("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="为空"):
            validate_qrcode_url("   ")

    def test_http_scheme_rejected(self) -> None:
        with pytest.raises(ValueError, match="https"):
            validate_qrcode_url("http://wx.qq.com/img.png")

    def test_unknown_domain_rejected(self) -> None:
        with pytest.raises(ValueError, match="白名单"):
            validate_qrcode_url("https://evil.example.com/qr.png")

    def test_no_hostname_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_qrcode_url("https:///path/only")

    def test_ftp_scheme_rejected(self) -> None:
        with pytest.raises(ValueError, match="https"):
            validate_qrcode_url("ftp://wx.qq.com/file.png")

    def test_subdomain_not_whitelisted(self) -> None:
        # 子域名不在白名单中
        with pytest.raises(ValueError, match="白名单"):
            validate_qrcode_url("https://sub.wx.qq.com/img.png")
