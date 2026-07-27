"""IM 适配器认证失败时的资源释放回归测试。"""

import pytest

from im.adapter_base import IMChannelConfig
from im.dingtalk_adapter import DingtalkAdapter
from im.feishu_adapter import FeishuAdapter
from im.telegram_adapter import TelegramAdapter


class FailingHttpClient:
    """模拟认证请求失败且可观测关闭状态的异步 HTTP 客户端。"""

    def __init__(self) -> None:
        self.closed = False

    async def get(self, *args, **kwargs):
        """模拟 Telegram 验证请求失败。"""
        del args, kwargs
        raise RuntimeError("认证请求失败")

    async def post(self, *args, **kwargs):
        """模拟飞书和钉钉认证请求失败。"""
        del args, kwargs
        raise RuntimeError("认证请求失败")

    async def aclose(self) -> None:
        """记录关闭调用。"""
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter_class", "config"),
    [
        (FeishuAdapter, IMChannelConfig(channel="feishu", app_id="id", app_secret="secret")),
        (DingtalkAdapter, IMChannelConfig(channel="dingtalk", app_id="id", app_secret="secret")),
        (TelegramAdapter, IMChannelConfig(channel="telegram", bot_token="token")),
    ],
)
async def test_start_closes_http_client_when_authentication_fails(monkeypatch, adapter_class, config):
    """认证失败时必须关闭已创建客户端，且不保留适配器引用。"""
    client = FailingHttpClient()
    module_name = adapter_class.__module__
    module = __import__(module_name, fromlist=["httpx"])
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda *args, **kwargs: client)

    adapter = adapter_class(config)

    with pytest.raises(RuntimeError, match="认证请求失败"):
        await adapter.start()

    assert client.closed is True
    assert adapter._client is None
    assert adapter.is_running is False
