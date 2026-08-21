"""SD WebUI (A1111) 兼容层（api/routes/sdwebui_compat.py）单元测试。

覆盖：
- 认证：Basic（用户名:API Key / 裸 API Key）/ Bearer / 未认证与错误密钥拒绝
- options：当前模型读取、set-model 切换、未知模型 400、无生图模型时空 checkpoint
- sd-models：生图模型映射（title 唯一化、剔除内部字段）
- 静态列表：samplers / schedulers / sd-vae / upscalers / latent-upscale-modes
- progress / interrupt：空闲态与空操作
- txt2img：参数转发（尺寸/负面提示词/采样参数/选中模型）、酒馆AI额外字段（url/auth）忽略、
  数量 clamp、空提示词 400、ValueError 400、上游异常 502

测试隔离：
- in-memory SQLite + StaticPool，用例间清理模型配置表
- generate_image 全部 mock，不发起真实 HTTP
- OPENAWA_API_KEY 通过 monkeypatch 注入测试值
"""

from __future__ import annotations

import base64
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# 将 backend 目录加入 sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from api.dependencies import get_db  # noqa: E402
from api.routes import sdwebui_compat  # noqa: E402
from config.settings import settings  # noqa: E402
from db.models import Base  # noqa: E402
from db.models.billing import ModelConfiguration, ProviderCredential  # noqa: E402
from main import app  # noqa: E402

# 测试用 API Key（通过 monkeypatch 注入，不读取真实配置）
# 注意：长度必须 >= 32 字符，否则 lifespan 启动时 _ensure_api_key 校验失败
TEST_API_KEY = "test-sd-compat-key-0123456789abcdef"


# ---------------------------------------------------------------------------
# 测试数据库与客户端
# ---------------------------------------------------------------------------

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
Base.metadata.create_all(bind=_engine)


@pytest.fixture(autouse=True)
def _clear_tables():
    """每个用例运行前后清理模型配置表并重置选中状态，保证用例间互不干扰。"""
    db = _TestingSessionLocal()
    try:
        db.query(ProviderCredential).delete()
        db.query(ModelConfiguration).delete()
        db.commit()
    finally:
        db.close()
    sdwebui_compat._selected_title = None
    yield
    db = _TestingSessionLocal()
    try:
        db.query(ProviderCredential).delete()
        db.query(ModelConfiguration).delete()
        db.commit()
    finally:
        db.close()
    sdwebui_compat._selected_title = None


@pytest.fixture(autouse=True)
def _patch_api_key(monkeypatch: pytest.MonkeyPatch):
    """注入测试 API Key，隔离真实 settings。"""
    monkeypatch.setattr(settings, "OPENAWA_API_KEY", SecretStr(TEST_API_KEY))


def _override_get_db():
    """提供独立测试数据库会话。"""
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def _test_client() -> Iterator[TestClient]:
    """注入依赖覆盖并构造 TestClient（兼容层认证走真实逻辑）。"""
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous_overrides


def _basic_auth(value: str) -> Dict[str, str]:
    """构造酒馆AI形式的 HTTP Basic 认证头。"""
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


def _auth_headers() -> Dict[str, str]:
    """标准酒馆AI认证头：任意用户名 + API Key。"""
    return _basic_auth(f"tavern:{TEST_API_KEY}")


def _create_image_config(
    db: Session,
    *,
    provider: str = "openai",
    model: str = "gpt-image-1",
    api_key: str = "sk-test-key",
    api_endpoint: str = "https://api.openai.com/v1",
) -> ModelConfiguration:
    """构造生图模型配置行。"""
    config = ModelConfiguration(
        provider=provider,
        model=model,
        api_key=api_key,
        api_endpoint=api_endpoint,
        is_image_generation=True,
        is_active=True,
        image_generation_usage="测试生图模型",
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


# ---------------------------------------------------------------------------
# 认证测试
# ---------------------------------------------------------------------------


class TestCompatAuth:
    """兼容层认证：Basic / Bearer / 拒绝未认证。"""

    def test_no_auth_header_rejected(self):
        """未携带认证头必须 401。"""
        with _test_client() as client:
            response = client.get("/sdapi/v1/options")
        assert response.status_code == 401

    def test_wrong_key_rejected(self):
        """错误 API Key 必须 401。"""
        with _test_client() as client:
            response = client.get("/sdapi/v1/options", headers=_basic_auth("tavern:wrong-key"))
        assert response.status_code == 401

    def test_basic_user_key_accepted(self):
        """用户名:API Key 形式（酒馆AI标准）认证通过。"""
        with _test_client() as client:
            response = client.get("/sdapi/v1/options", headers=_auth_headers())
        assert response.status_code == 200

    def test_basic_bare_key_accepted(self):
        """无冒号的裸 API Key 形式认证通过。"""
        with _test_client() as client:
            response = client.get("/sdapi/v1/options", headers=_basic_auth(TEST_API_KEY))
        assert response.status_code == 200

    def test_bearer_accepted(self):
        """Bearer API Key 形式认证通过。"""
        with _test_client() as client:
            response = client.get(
                "/sdapi/v1/options", headers={"Authorization": f"Bearer {TEST_API_KEY}"}
            )
        assert response.status_code == 200

    def test_malformed_basic_rejected(self):
        """非法 base64 的 Basic 头必须 401（不抛 500）。"""
        with _test_client() as client:
            response = client.get(
                "/sdapi/v1/options", headers={"Authorization": "Basic !!!not-base64!!!"}
            )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# options / 模型列表 / 静态列表测试
# ---------------------------------------------------------------------------


class TestOptionsAndModels:
    """options 与 sd-models：选中状态与模型映射。"""

    def test_options_returns_default_model(self, db_session: Session):
        """未选择时返回第一个生图模型的 title。"""
        _create_image_config(db_session)
        with _test_client() as client:
            response = client.get("/sdapi/v1/options", headers=_auth_headers())
        assert response.status_code == 200
        assert response.json()["sd_model_checkpoint"] == "openai:gpt-image-1"

    def test_options_without_models_returns_empty(self):
        """无生图模型时返回空 checkpoint（ping 仍可 200 通过）。"""
        with _test_client() as client:
            response = client.get("/sdapi/v1/options", headers=_auth_headers())
        assert response.status_code == 200
        assert response.json()["sd_model_checkpoint"] == ""

    def test_set_model_switches_selection(self, db_session: Session):
        """set-model 切换后 options 返回新模型 title。"""
        _create_image_config(db_session, model="gpt-image-1")
        _create_image_config(db_session, model="qwen-image", api_endpoint="https://dashscope.aliyuncs.com")
        with _test_client() as client:
            set_resp = client.post(
                "/sdapi/v1/options",
                json={"sd_model_checkpoint": "openai:qwen-image"},
                headers=_auth_headers(),
            )
            get_resp = client.get("/sdapi/v1/options", headers=_auth_headers())
        assert set_resp.status_code == 200
        assert get_resp.json()["sd_model_checkpoint"] == "openai:qwen-image"

    def test_set_model_unknown_rejected(self, db_session: Session):
        """未知模型名返回 400。"""
        _create_image_config(db_session)
        with _test_client() as client:
            response = client.post(
                "/sdapi/v1/options",
                json={"sd_model_checkpoint": "nope:unknown"},
                headers=_auth_headers(),
            )
        assert response.status_code == 400

    def test_sd_models_shape(self, db_session: Session):
        """sd-models 返回 A1111 形状且不含内部字段。"""
        _create_image_config(db_session, provider="openai", model="gpt-image-1")
        _create_image_config(db_session, provider="dashscope", model="qwen-image")
        with _test_client() as client:
            response = client.get("/sdapi/v1/sd-models", headers=_auth_headers())
        assert response.status_code == 200
        models = response.json()
        assert len(models) == 2
        titles = [m["title"] for m in models]
        assert titles == ["openai:gpt-image-1", "dashscope:qwen-image"]
        for entry in models:
            assert "model_name" in entry
            assert "_config_id" not in entry


class TestStaticLists:
    """静态列表端点：填充酒馆AI设置面板。"""

    def test_samplers(self):
        """采样器列表含 name 字段。"""
        with _test_client() as client:
            response = client.get("/sdapi/v1/samplers", headers=_auth_headers())
        assert response.status_code == 200
        names = [item["name"] for item in response.json()]
        assert "Euler a" in names and "DDIM" in names

    def test_schedulers(self):
        """调度器列表含 name 字段。"""
        with _test_client() as client:
            response = client.get("/sdapi/v1/schedulers", headers=_auth_headers())
        assert response.status_code == 200
        names = [item["name"] for item in response.json()]
        assert "normal" in names

    def test_vaes_and_sd_modules(self):
        """sd-vae 与 Forge 别名 sd-modules 均返回 model_name 列表。"""
        with _test_client() as client:
            vae_resp = client.get("/sdapi/v1/sd-vae", headers=_auth_headers())
            module_resp = client.get("/sdapi/v1/sd-modules", headers=_auth_headers())
        assert vae_resp.status_code == 200
        assert module_resp.status_code == 200
        assert vae_resp.json()[0]["model_name"] == "Automatic"
        assert module_resp.json()[0]["model_name"] == "Automatic"

    def test_upscalers_and_latent_modes(self):
        """放大器与潜空间放大模式列表含 name 字段。"""
        with _test_client() as client:
            upscalers = client.get("/sdapi/v1/upscalers", headers=_auth_headers())
            latent = client.get("/sdapi/v1/latent-upscale-modes", headers=_auth_headers())
        assert upscalers.status_code == 200
        assert latent.status_code == 200
        assert upscalers.json()[0]["name"] == "None"
        assert any(item["name"] == "Latent" for item in latent.json())


class TestProgressAndInterrupt:
    """progress 与 interrupt：空闲态与空操作。"""

    def test_progress_idle(self):
        """progress 恒返回空闲态（酒馆AI set-model 轮询立即通过）。"""
        with _test_client() as client:
            response = client.get("/sdapi/v1/progress", headers=_auth_headers())
        assert response.status_code == 200
        data = response.json()
        assert data["progress"] == 0
        assert data["state"]["job_count"] == 0

    def test_interrupt_noop(self):
        """POST / GET interrupt 均为空操作 200。"""
        with _test_client() as client:
            post_resp = client.post("/sdapi/v1/interrupt", headers=_auth_headers())
            get_resp = client.get("/sdapi/v1/interrupt", headers=_auth_headers())
        assert post_resp.status_code == 200
        assert get_resp.status_code == 200


# ---------------------------------------------------------------------------
# txt2img 核心测试
# ---------------------------------------------------------------------------


def _mock_generate_result() -> Dict[str, Any]:
    """构造 generate_image 的 mock 返回值。"""
    return {
        "ok": True,
        "model": {"id": 1, "provider": "openai", "model": "gpt-image-1", "label": "openai:gpt-image-1"},
        "protocol": "openai",
        "size": "1024x1024",
        "n": 1,
        "images": [
            {"b64_json": "aGVsbG8=", "format": "png", "file_path": "/tmp/a.png", "bytes": 5}
        ],
    }


class TestTxt2Img:
    """txt2img：酒馆AI核心生图请求。"""

    def test_txt2img_success_forwards_params(self, db_session: Session):
        """成功生图：参数正确转发，响应为 A1111 形状（纯 base64 images + JSON 字符串 info）。"""
        config = _create_image_config(db_session)
        with patch(
            "api.routes.sdwebui_compat.generate_image", new_callable=AsyncMock
        ) as mock_generate:
            mock_generate.return_value = _mock_generate_result()
            with _test_client() as client:
                response = client.post(
                    "/sdapi/v1/txt2img",
                    json={
                        # 酒馆AI代理字段，兼容层必须忽略
                        "url": "http://localhost:8000",
                        "auth": "tavern:key",
                        "prompt": "a cute cat",
                        "negative_prompt": "lowres, bad anatomy",
                        "width": 1024,
                        "height": 768,
                        "steps": 28,
                        "cfg_scale": 5.5,
                        "sampler_name": "DPM++ 2M",
                        "scheduler": "karras",
                        "seed": 42,
                        "n_iter": 1,
                        "batch_size": 1,
                        "override_settings": {"CLIP_stop_at_last_layers": 2},
                    },
                    headers=_auth_headers(),
                )

        assert response.status_code == 200
        data = response.json()
        assert data["images"] == ["aGVsbG8="]
        # info 必须是合法 JSON 字符串（A1111 协议形状）
        info = json.loads(data["info"])
        assert info["model"] == "openai:gpt-image-1"

        # 校验转发给核心生图服务的参数
        mock_generate.assert_awaited_once()
        kwargs = mock_generate.call_args.kwargs
        assert kwargs["prompt"] == "a cute cat"
        assert kwargs["negative_prompt"] == "lowres, bad anatomy"
        assert kwargs["size"] == "1024x768"
        assert kwargs["config_id"] == config.id
        assert kwargs["generation_params"]["steps"] == 28
        assert kwargs["generation_params"]["cfg_scale"] == 5.5
        assert kwargs["generation_params"]["sampler_name"] == "DPM++ 2M"
        assert kwargs["generation_params"]["scheduler"] == "karras"
        assert kwargs["generation_params"]["seed"] == 42

    def test_txt2img_uses_selected_model(self, db_session: Session):
        """set-model 切换后 txt2img 使用切换后的模型 config_id。"""
        first = _create_image_config(db_session, model="gpt-image-1")
        second = _create_image_config(db_session, model="qwen-image", api_endpoint="https://dashscope.aliyuncs.com")
        with patch(
            "api.routes.sdwebui_compat.generate_image", new_callable=AsyncMock
        ) as mock_generate:
            mock_generate.return_value = _mock_generate_result()
            with _test_client() as client:
                client.post(
                    "/sdapi/v1/options",
                    json={"sd_model_checkpoint": "openai:qwen-image"},
                    headers=_auth_headers(),
                )
                response = client.post(
                    "/sdapi/v1/txt2img",
                    json={"prompt": "a cat", "width": 512, "height": 512},
                    headers=_auth_headers(),
                )
        assert response.status_code == 200
        kwargs = mock_generate.call_args.kwargs
        assert kwargs["config_id"] == second.id
        assert kwargs["config_id"] != first.id

    def test_txt2img_n_clamped_to_6(self, db_session: Session):
        """n_iter * batch_size 超出上限时 clamp 到 6。"""
        _create_image_config(db_session)
        with patch(
            "api.routes.sdwebui_compat.generate_image", new_callable=AsyncMock
        ) as mock_generate:
            mock_generate.return_value = _mock_generate_result()
            with _test_client() as client:
                response = client.post(
                    "/sdapi/v1/txt2img",
                    json={"prompt": "a cat", "n_iter": 5, "batch_size": 4},
                    headers=_auth_headers(),
                )
        assert response.status_code == 200
        assert mock_generate.call_args.kwargs["n"] == 6

    def test_txt2img_empty_prompt_rejected(self, db_session: Session):
        """空提示词返回 400。"""
        _create_image_config(db_session)
        with _test_client() as client:
            response = client.post(
                "/sdapi/v1/txt2img",
                json={"prompt": "   "},
                headers=_auth_headers(),
            )
        assert response.status_code == 400

    def test_txt2img_without_models_rejected(self):
        """无生图模型时返回 400 与可读错误。"""
        with _test_client() as client:
            response = client.post(
                "/sdapi/v1/txt2img",
                json={"prompt": "a cat"},
                headers=_auth_headers(),
            )
        assert response.status_code == 400
        # 项目统一错误包装：{error: {code, message, ...}}
        assert "生图模型" in response.json()["error"]["message"]

    def test_txt2img_value_error_returns_400(self, db_session: Session):
        """核心生图抛 ValueError（配置/上游业务错误）时返回 400。"""
        _create_image_config(db_session)
        with patch(
            "api.routes.sdwebui_compat.generate_image", new_callable=AsyncMock
        ) as mock_generate:
            mock_generate.side_effect = ValueError("生图接口请求失败: 状态码 401")
            with _test_client() as client:
                response = client.post(
                    "/sdapi/v1/txt2img",
                    json={"prompt": "a cat"},
                    headers=_auth_headers(),
                )
        assert response.status_code == 400
        assert "状态码 401" in response.json()["error"]["message"]

    def test_txt2img_upstream_error_returns_502(self, db_session: Session):
        """网络等未预期异常返回 502（不静默吞）。"""
        _create_image_config(db_session)
        with patch(
            "api.routes.sdwebui_compat.generate_image", new_callable=AsyncMock
        ) as mock_generate:
            mock_generate.side_effect = RuntimeError("connection reset")
            with _test_client() as client:
                response = client.post(
                    "/sdapi/v1/txt2img",
                    json={"prompt": "a cat"},
                    headers=_auth_headers(),
                )
        assert response.status_code == 502
        assert "connection reset" in response.json()["error"]["message"]

    def test_txt2img_unauthenticated_rejected(self, db_session: Session):
        """未认证的 txt2img 请求必须 401。"""
        _create_image_config(db_session)
        with _test_client() as client:
            response = client.post("/sdapi/v1/txt2img", json={"prompt": "a cat"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# 数据库会话 fixture（供需要直接操作 DB 的用例使用）
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session() -> Session:
    """提供独立数据库会话。"""
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
