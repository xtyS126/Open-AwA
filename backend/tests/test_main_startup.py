"""
后端启动测试模块，负责验证服务启动入口对主机、端口配置以及端口占用异常的处理行为。
通过这些测试可以确保启动参数可配置，同时不会破坏现有应用初始化流程。
"""

import errno
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


class TestMainStartup:
    """
    封装后端启动入口相关测试。
    该测试类聚焦于配置解析与启动异常处理，避免影响应用其余功能初始化。
    """

    def test_get_server_host_uses_backend_host_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        验证主机配置优先读取 BACKEND_HOST。
        当同时存在兼容变量 HOST 时，应始终以前者为准。
        """
        monkeypatch.setenv("BACKEND_HOST", "127.0.0.1")
        monkeypatch.setenv("HOST", "0.0.0.0")

        assert main.get_server_host() == "127.0.0.1"

    def test_get_server_port_uses_backend_port_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        验证端口配置优先读取 BACKEND_PORT。
        当同时存在兼容变量 PORT 时，应始终以前者为准，并转换为整数返回。
        """
        monkeypatch.setenv("BACKEND_PORT", "9100")
        monkeypatch.setenv("PORT", "9200")

        assert main.get_server_port() == 9100

    def test_get_server_port_raises_for_invalid_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        验证非法端口配置会抛出明确异常。
        这样可以帮助调用方快速识别环境变量填写错误的问题。
        """
        monkeypatch.setenv("BACKEND_PORT", "invalid-port")
        monkeypatch.delenv("PORT", raising=False)

        with pytest.raises(ValueError, match="无效的端口配置"):
            main.get_server_port()

    def test_run_server_passes_configured_host_and_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        验证启动入口会将解析后的主机与端口传递给 uvicorn。
        该测试通过注入假的 uvicorn 模块避免真正启动网络服务。
        """
        captured: dict[str, object] = {}

        def fake_run(app, host: str, port: int) -> None:
            """
            记录启动参数，便于断言 run_server 的传参行为。
            """
            captured["app"] = app
            captured["host"] = host
            captured["port"] = port

        monkeypatch.setenv("BACKEND_HOST", "127.0.0.1")
        monkeypatch.setenv("BACKEND_PORT", "8765")
        monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))

        main.run_server()

        assert captured == {"app": main.app, "host": "127.0.0.1", "port": 8765}

    def test_run_server_raises_friendly_error_when_port_in_use(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        验证端口被占用时会抛出友好的提示信息。
        这样可以让调用方直接知道需要释放端口或修改端口配置，而不是只看到底层系统错误。
        """

        def fake_run(app, host: str, port: int) -> None:
            """
            模拟 uvicorn 在绑定端口时触发地址占用异常。
            """
            raise OSError(errno.EADDRINUSE, "Address already in use")

        monkeypatch.setenv("BACKEND_PORT", "8001")
        monkeypatch.delenv("PORT", raising=False)
        monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))

        with pytest.raises(RuntimeError, match="端口 8001 已被占用"):
            main.run_server()
