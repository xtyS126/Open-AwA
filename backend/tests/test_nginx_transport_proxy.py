"""Nginx HTTP 与 WebSocket 单一路径代理门禁。"""

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONFIGS = (
    PROJECT_ROOT / "deploy" / "nginx.conf",
    PROJECT_ROOT / "deploy" / "nginx" / "ssl.conf",
)


def _api_location(config_source: str) -> str:
    """提取普通 API location 块用于代理头校验。"""
    match = re.search(
        r"location /api/ \{(?P<body>.*?)\n    \}",
        config_source,
        flags=re.DOTALL,
    )
    assert match is not None
    return match.group("body")


def test_api_proxy_handles_http_and_websocket_without_dead_ws_location() -> None:
    """真实 /api WebSocket 端点必须与普通 API 共用一个代理权威。"""
    for config_path in NGINX_CONFIGS:
        source = config_path.read_text(encoding="utf-8-sig")
        api_location = _api_location(source)

        assert "map $http_upgrade $connection_upgrade" in source
        assert "proxy_set_header Upgrade $http_upgrade;" in api_location
        assert "proxy_set_header Connection $connection_upgrade;" in api_location
        assert "location /ws/" not in source
