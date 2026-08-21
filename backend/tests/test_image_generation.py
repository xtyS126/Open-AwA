"""生图功能（image-generation-builtin 插件 + core/image_generation.py）单元测试。

覆盖：
- 协议判定与端点推导（OpenAI 兼容 / DashScope 原生 / SD WebUI 原生）
- 尺寸解析、图片格式识别
- 生图模型配置解析（is_image_generation 标记、API Key 解析、fail-closed 错误）
- generate_image 三协议分发、结果组装与文件保存
- 插件入口（initialize / get_tools / execute 降级路径）
- 工具 handler（image_generate）与 REST 路由（models 列表 / generate）

测试隔离：
- 使用 in-memory SQLite 与 StaticPool
- 生图结果保存目录 patch 为 pytest 临时目录，不污染 var/data/generated
- 上游协议调用全部 mock，不发起真实 HTTP
"""

from __future__ import annotations

import base64
import io
import sys
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# 将 backend 目录加入 sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from api.dependencies import get_current_user, get_db  # noqa: E402
from billing.pricing_manager import PricingManager  # noqa: E402
from billing.routers.billing import ModelConfigCreateRequest  # noqa: E402
from core.image_generation import (  # noqa: E402
    IMAGE_OUTPUT_DIR,
    _dashscope_native_endpoint,
    _detect_binary_format,
    _detect_protocol,
    _generate_novelai,
    _normalize_openai_base,
    _novelai_endpoint,
    _novelai_noise_schedule,
    _novelai_sampler,
    _parse_size,
    _resolve_image_configuration,
    _sdwebui_endpoint,
    generate_image,
    list_image_models,
)
from db.models import Base  # noqa: E402
from db.models.billing import ModelConfiguration, ProviderCredential  # noqa: E402
from main import app  # noqa: E402
from plugins.image_generation_builtin.plugin import ImageGenerationPlugin  # noqa: E402
from plugins.image_generation_builtin.tools import (  # noqa: E402
    IMAGE_GENERATION_TOOLS,
    image_generate,
)


# ---------------------------------------------------------------------------
# 测试数据库
# ---------------------------------------------------------------------------

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
Base.metadata.create_all(bind=_engine)


@pytest.fixture
def db_session() -> Session:
    """提供独立数据库会话。"""
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _clear_tables():
    """每个用例运行前后清理模型配置表，保证用例间互不干扰。"""
    db = _TestingSessionLocal()
    try:
        db.query(ProviderCredential).delete()
        db.query(ModelConfiguration).delete()
        db.commit()
    finally:
        db.close()
    yield
    db = _TestingSessionLocal()
    try:
        db.query(ProviderCredential).delete()
        db.query(ModelConfiguration).delete()
        db.commit()
    finally:
        db.close()


def _create_image_config(
    db: Session,
    *,
    provider: str = "openai",
    model: str = "gpt-image-1",
    api_key: str = "sk-test-key",
    api_endpoint: str = "https://api.openai.com/v1",
    is_image_generation: bool = True,
    is_active: bool = True,
    usage: str = "高质量写实图片，单张生成",
) -> ModelConfiguration:
    """构造生图模型配置行。"""
    config = ModelConfiguration(
        provider=provider,
        model=model,
        api_key=api_key,
        api_endpoint=api_endpoint,
        is_image_generation=is_image_generation,
        is_active=is_active,
        image_generation_usage=usage,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


# ---------------------------------------------------------------------------
# 协议工具函数测试
# ---------------------------------------------------------------------------


class TestParseSize:
    """尺寸字符串解析。"""

    def test_valid_size(self):
        """合法的 宽x高 格式解析为整数对。"""
        assert _parse_size("1024x1024") == (1024, 1024)
        assert _parse_size("1536x1024") == (1536, 1024)
        assert _parse_size("512x512") == (512, 512)

    def test_invalid_size_raises(self):
        """非法尺寸格式必须抛 ValueError。"""
        with pytest.raises(ValueError):
            _parse_size("1024*1024")
        with pytest.raises(ValueError):
            _parse_size("square")
        with pytest.raises(ValueError):
            _parse_size("")


class TestDetectProtocol:
    """协议族判定：dashscope / sdwebui / openai。"""

    def test_dashscope_endpoint(self):
        """端点含 dashscope 判定为 DashScope 原生协议。"""
        assert _detect_protocol("openai", "https://dashscope.aliyuncs.com/api/v1") == "dashscope"

    def test_dashscope_provider(self):
        """provider 名为 dashscope 判定为 DashScope 原生协议。"""
        assert _detect_protocol("dashscope", "https://compatible.example.com") == "dashscope"

    def test_sdwebui_endpoint(self):
        """端点含 sdapi 判定为 SD WebUI 原生协议。"""
        assert _detect_protocol("openai", "http://127.0.0.1:7860/sdapi/v1/txt2img") == "sdwebui"

    def test_sd_provider(self):
        """provider 名为 sd/stable 判定为 SD WebUI 原生协议。"""
        assert _detect_protocol("stable-diffusion", "http://127.0.0.1:7860") == "sdwebui"
        assert _detect_protocol("sd", "http://127.0.0.1:7860") == "sdwebui"

    def test_openai_default(self):
        """其他情况默认 OpenAI 兼容协议。"""
        assert _detect_protocol("openai", "https://api.openai.com/v1") == "openai"
        assert _detect_protocol("azure", "https://xxx.openai.azure.com") == "openai"

    def test_novelai_provider(self):
        """provider 名为 novelai 判定为 NovelAI 原生协议。"""
        assert _detect_protocol("novelai", "https://api.penguinsama.com") == "novelai"

    def test_novelai_model_name(self):
        """模型名含 nai-diffusion 判定为 NovelAI 原生协议（站点根地址场景）。"""
        assert (
            _detect_protocol("penguinsama", "https://api.penguinsama.com", "nai-diffusion-4-full")
            == "novelai"
        )

    def test_novelai_endpoint(self):
        """端点含 /ai/generate-image 判定为 NovelAI 原生协议。"""
        assert (
            _detect_protocol("penguinsama", "https://api.penguinsama.com/ai/generate-image")
            == "novelai"
        )

    def test_novelai_not_triggered_by_plain_model(self):
        """普通模型名 + 普通端点不误判为 NovelAI。"""
        assert (
            _detect_protocol("penguinsama", "https://api.penguinsama.com/api/draw/openai/v1", "nano-banana-pro")
            == "openai"
        )


class TestNormalizeOpenaiBase:
    """OpenAI 兼容基址规范化。"""

    def test_strip_chat_completions_suffix(self):
        """剥掉 /chat/completions 后缀并补 /v1。"""
        assert _normalize_openai_base("https://host/v1/chat/completions") == "https://host/v1"

    def test_strip_images_generations_suffix(self):
        """剥掉 /images/generations 后缀。"""
        assert _normalize_openai_base("https://host/v1/images/generations") == "https://host/v1"

    def test_append_v1(self):
        """裸基址补 /v1。"""
        assert _normalize_openai_base("https://host") == "https://host/v1"

    def test_already_normalized(self):
        """已是 /v1 结尾时保持不变。"""
        assert _normalize_openai_base("https://host/v1") == "https://host/v1"


class TestEndpointDerivation:
    """DashScope 原生与 SD WebUI 原生端点推导。"""

    def test_dashscope_compatible_mode_maps_to_native(self):
        """compatible-mode 基址映射为原生 multimodal-generation 端点。"""
        endpoint = _dashscope_native_endpoint("https://dashscope.aliyuncs.com/compatible-mode/v1")
        assert endpoint == "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"

    def test_dashscope_default_host(self):
        """空端点时使用默认阿里云主机。"""
        endpoint = _dashscope_native_endpoint("")
        assert endpoint == "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"

    def test_sdwebui_append_path(self):
        """裸 SD 地址补 /sdapi/v1/txt2img。"""
        assert _sdwebui_endpoint("http://127.0.0.1:7860") == "http://127.0.0.1:7860/sdapi/v1/txt2img"

    def test_sdwebui_keep_existing_path(self):
        """已含完整路径时保持不变。"""
        assert _sdwebui_endpoint("http://127.0.0.1:7860/sdapi/v1/txt2img") == "http://127.0.0.1:7860/sdapi/v1/txt2img"

    def test_novelai_append_path(self):
        """裸站点根地址补 /ai/generate-image。"""
        assert _novelai_endpoint("https://api.penguinsama.com") == "https://api.penguinsama.com/ai/generate-image"

    def test_novelai_keep_existing_path(self):
        """已含完整路径时保持不变。"""
        assert (
            _novelai_endpoint("https://api.penguinsama.com/ai/generate-image")
            == "https://api.penguinsama.com/ai/generate-image"
        )


class TestNovelaiSamplerMapping:
    """A1111 采样器名到 NovelAI 采样器的映射。"""

    def test_native_names_passthrough(self):
        """NovelAI 原生采样器名直接透传。"""
        assert _novelai_sampler("k_euler_ancestral") == "k_euler_ancestral"
        assert _novelai_sampler("k_dpmpp_2m") == "k_dpmpp_2m"
        assert _novelai_sampler("ddim") == "ddim"

    def test_a1111_aliases_mapped(self):
        """A1111 采样器名映射为 NovelAI 等价采样器。"""
        assert _novelai_sampler("Euler a") == "k_euler_ancestral"
        assert _novelai_sampler("DPM++ 2M") == "k_dpmpp_2m"
        assert _novelai_sampler("Euler") == "k_euler"

    def test_unknown_falls_back(self):
        """未知采样器名回退 k_euler_ancestral（不因名称不识别而失败）。"""
        assert _novelai_sampler("Some Weird Sampler") == "k_euler_ancestral"
        assert _novelai_sampler(None) == "k_euler_ancestral"

    def test_noise_schedule_mapping(self):
        """调度器映射：合法值透传，非法值回退 karras。"""
        assert _novelai_noise_schedule("karras") == "karras"
        assert _novelai_noise_schedule("exponential") == "exponential"
        assert _novelai_noise_schedule("normal") == "karras"
        assert _novelai_noise_schedule(None) == "karras"


class TestDetectBinaryFormat:
    """按魔数识别图片格式。"""

    def test_png(self):
        """PNG 魔数识别。"""
        assert _detect_binary_format(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8) == "png"

    def test_jpeg(self):
        """JPEG 魔数识别。"""
        assert _detect_binary_format(b"\xff\xd8\xff\xe0" + b"\x00" * 8) == "jpeg"

    def test_webp(self):
        """WebP 魔数识别。"""
        assert _detect_binary_format(b"RIFF\x00\x00\x00\x00WEBP") == "webp"

    def test_unknown_falls_back_to_png(self):
        """无法识别时按 png 保存（不抛错）。"""
        assert _detect_binary_format(b"\x00\x01\x02\x03") == "png"


# ---------------------------------------------------------------------------
# 模型目录与配置解析测试
# ---------------------------------------------------------------------------


class TestListImageModels:
    """生图模型列表：只返回启用且标记为生图模型的配置。"""

    def test_only_image_generation_active(self, db_session: Session):
        """聊天模型与停用生图模型被过滤，usage 透传。"""
        _create_image_config(db_session, usage="写实风格")
        _create_image_config(
            db_session,
            provider="dashscope",
            model="qwen-image",
            is_image_generation=False,
        )
        _create_image_config(
            db_session,
            provider="sd",
            model="sd-xl",
            is_active=False,
        )
        models = list_image_models(db_session)
        assert len(models) == 1
        assert models[0]["provider"] == "openai"
        assert models[0]["model"] == "gpt-image-1"
        assert models[0]["label"] == "openai:gpt-image-1"
        assert models[0]["usage"] == "写实风格"

    def test_empty_when_no_image_model(self, db_session: Session):
        """未配置生图模型时返回空列表。"""
        _create_image_config(db_session, is_image_generation=False)
        assert list_image_models(db_session) == []


class TestResolveImageConfiguration:
    """生图模型配置解析：标记校验、API Key 解析、fail-closed 错误。"""

    def test_config_id_not_found(self, db_session: Session):
        """指定不存在的 config_id 必须抛 ValueError。"""
        with pytest.raises(ValueError, match="生图模型配置不存在"):
            _resolve_image_configuration(db_session, config_id=9999)

    def test_not_image_generation_rejected(self, db_session: Session):
        """未标记为生图模型的配置必须被拒绝。"""
        config = _create_image_config(db_session, is_image_generation=False)
        with pytest.raises(ValueError, match="未标记为生图模型"):
            _resolve_image_configuration(db_session, config_id=config.id)

    def test_legacy_enc_key_rejected(self, db_session: Session):
        """enc: 旧算法密文已失效，必须显式报错要求重新录入。"""
        config = _create_image_config(db_session, api_key="enc:legacy-cipher")
        with pytest.raises(ValueError, match="已失效"):
            _resolve_image_configuration(db_session, config_id=config.id)

    def test_missing_api_key(self, db_session: Session):
        """无 API Key 且无 ProviderCredential 时必须显式报错。"""
        config = _create_image_config(db_session, api_key="")
        with pytest.raises(ValueError, match="未配置 API Key"):
            _resolve_image_configuration(db_session, config_id=config.id)

    def test_missing_endpoint(self, db_session: Session):
        """无端点时必须显式报错。"""
        config = _create_image_config(db_session, api_endpoint="")
        with pytest.raises(ValueError, match="未配置 API 端点"):
            _resolve_image_configuration(db_session, config_id=config.id)

    def test_plain_api_key_ok(self, db_session: Session):
        """明文 API Key 直接可用。"""
        config = _create_image_config(db_session, api_key="sk-plain")
        resolved = _resolve_image_configuration(db_session, config_id=config.id)
        assert resolved["api_key"] == "sk-plain"
        assert resolved["endpoint"] == "https://api.openai.com/v1"
        assert resolved["label"] == "openai:gpt-image-1"

    def test_default_picks_first_active(self, db_session: Session):
        """config_id 缺省时自动选择第一个启用的生图模型。"""
        _create_image_config(db_session, provider="openai", model="gpt-image-1")
        _create_image_config(db_session, provider="dashscope", model="qwen-image")
        resolved = _resolve_image_configuration(db_session, config_id=None)
        assert resolved["label"] == "openai:gpt-image-1"

    def test_credential_fallback(self, db_session: Session):
        """config 无 API Key 时回退读取 ProviderCredential（by provider name）。"""
        config = _create_image_config(db_session, api_key="")
        credential = ProviderCredential(
            provider="openai",
            api_key="sk-from-credential",
            api_endpoint="https://api.openai.com/v1",
        )
        db_session.add(credential)
        db_session.commit()
        resolved = _resolve_image_configuration(db_session, config_id=config.id)
        assert resolved["api_key"] == "sk-from-credential"


# ---------------------------------------------------------------------------
# generate_image 分发与保存测试
# ---------------------------------------------------------------------------


class TestGenerateImage:
    """三协议分发、参数透传与结果保存。"""

    @pytest.fixture
    def mock_protocols(self):
        """mock 四个协议函数与输出目录。"""
        patches = [
            patch("core.image_generation._generate_openai_compat", new_callable=AsyncMock),
            patch("core.image_generation._generate_dashscope", new_callable=AsyncMock),
            patch("core.image_generation._generate_sdwebui", new_callable=AsyncMock),
            patch("core.image_generation._generate_novelai", new_callable=AsyncMock),
        ]
        for p in patches:
            p.start()
        yield
        for p in patches:
            p.stop()

    @pytest.fixture
    def tmp_output_dir(self, tmp_path: Path):
        """生图输出目录重定向到临时目录。"""
        original = IMAGE_OUTPUT_DIR
        patcher = patch("core.image_generation.IMAGE_OUTPUT_DIR", tmp_path)
        patcher.start()
        yield tmp_path
        patcher.stop()

    def test_empty_prompt_rejected(self, db_session: Session, mock_protocols):
        """空提示词必须抛 ValueError。"""
        with pytest.raises(ValueError, match="提示词不能为空"):
            _ = None
            import asyncio

            asyncio.run(generate_image(db_session, prompt="   "))

    def test_invalid_size_rejected(self, db_session: Session, mock_protocols):
        """非法尺寸必须抛 ValueError。"""
        import asyncio

        with pytest.raises(ValueError):
            asyncio.run(generate_image(db_session, prompt="一只猫", size="square"))

    def test_n_out_of_range(self, db_session: Session, mock_protocols):
        """n 越界必须抛 ValueError。"""
        import asyncio

        with pytest.raises(ValueError):
            asyncio.run(generate_image(db_session, prompt="一只猫", n=0))
        with pytest.raises(ValueError):
            asyncio.run(generate_image(db_session, prompt="一只猫", n=7))

    def test_openai_compat_dispatch(self, db_session: Session, mock_protocols, tmp_output_dir: Path):
        """OpenAI 兼容协议分发：参数透传、结果保存、返回结构完整。"""
        import asyncio

        from core import image_generation as ig

        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        ig._generate_openai_compat.return_value = [{"data": png_bytes}]
        config = _create_image_config(db_session, api_key="sk-plain")

        result = asyncio.run(
            generate_image(
                db_session,
                prompt="一只猫",
                config_id=config.id,
                size="1536x1024",
                n=1,
                quality="high",
            )
        )

        ig._generate_openai_compat.assert_awaited_once()
        call_args = ig._generate_openai_compat.await_args.args
        assert call_args[1] == "一只猫"
        assert call_args[2] == "1536x1024"
        assert call_args[3] == 1
        assert call_args[4] == "high"

        assert result["ok"] is True
        assert result["protocol"] == "openai"
        assert result["model"]["label"] == "openai:gpt-image-1"
        assert result["n"] == 1
        image = result["images"][0]
        assert image["format"] == "png"
        assert image["b64_json"] == base64.b64encode(png_bytes).decode("ascii")
        assert Path(image["file_path"]).exists()
        assert Path(image["file_path"]).parent == tmp_output_dir

    def test_dashscope_dispatch(self, db_session: Session, mock_protocols, tmp_output_dir: Path):
        """DashScope 原生协议分发。"""
        import asyncio

        from core import image_generation as ig

        jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 16
        ig._generate_dashscope.return_value = [{"data": jpeg_bytes}]
        config = _create_image_config(
            db_session,
            provider="dashscope",
            model="qwen-image",
            api_endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

        result = asyncio.run(generate_image(db_session, prompt="山水画", config_id=config.id))

        ig._generate_dashscope.assert_awaited_once()
        assert result["protocol"] == "dashscope"
        assert result["images"][0]["format"] == "jpeg"

    def test_sdwebui_dispatch(self, db_session: Session, mock_protocols, tmp_output_dir: Path):
        """SD WebUI 原生协议分发。"""
        import asyncio

        from core import image_generation as ig

        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        ig._generate_sdwebui.return_value = [{"data": png_bytes}, {"data": png_bytes}]
        config = _create_image_config(
            db_session,
            provider="stable-diffusion",
            model="sd-xl",
            api_endpoint="http://127.0.0.1:7860",
            api_key="",
        )
        credential = ProviderCredential(
            provider="stable-diffusion",
            api_key="sk-sd",
            api_endpoint="http://127.0.0.1:7860",
        )
        db_session.add(credential)
        db_session.commit()

        result = asyncio.run(generate_image(db_session, prompt="机甲", config_id=config.id, n=2))

        ig._generate_sdwebui.assert_awaited_once()
        call_args = ig._generate_sdwebui.await_args.args
        # 新签名：(config, prompt, negative_prompt, width, height, n, generation_params)
        assert call_args[2] is None
        assert call_args[3] == 1024
        assert call_args[4] == 1024
        assert call_args[5] == 2
        assert result["n"] == 2
        assert len(result["images"]) == 2

    def test_novelai_dispatch(self, db_session: Session, mock_protocols, tmp_output_dir: Path):
        """NovelAI 原生协议分发（模型名含 nai-diffusion 触发）。"""
        import asyncio

        from core import image_generation as ig

        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        ig._generate_novelai.return_value = [{"data": png_bytes}]
        config = _create_image_config(
            db_session,
            provider="penguinsama",
            model="nai-diffusion-4-full",
            api_endpoint="https://api.penguinsama.com",
            api_key="sk-nai-test",
        )

        result = asyncio.run(
            generate_image(
                db_session,
                prompt="动漫少女",
                config_id=config.id,
                negative_prompt="lowres",
                generation_params={"steps": 23, "cfg_scale": 5.5, "sampler_name": "Euler a", "seed": 42},
            )
        )

        ig._generate_novelai.assert_awaited_once()
        call_args = ig._generate_novelai.await_args.args
        # 签名：(config, prompt, negative_prompt, width, height, n, generation_params)
        assert call_args[0]["model"] == "nai-diffusion-4-full"
        assert call_args[1] == "动漫少女"
        assert call_args[2] == "lowres"
        assert call_args[3] == 1024
        assert call_args[4] == 1024
        assert call_args[5] == 1
        assert call_args[6]["steps"] == 23
        assert result["protocol"] == "novelai"
        assert result["images"][0]["format"] == "png"


class TestImageConfigEndpointNormalization:
    """生图配置端点规范化：跳过 /v1 后缀，聊天配置保持原行为。"""

    def test_image_config_endpoint_not_suffixed(self, db_session: Session):
        """生图配置的端点不做 /v1 后缀规范化（NovelAI/SD 等用站点根地址）。"""
        pm = PricingManager(db_session)
        config = pm.create_configuration(
            {
                "provider": "penguinsama",
                "model": "nai-diffusion-4-full",
                "api_key": "sk-test",
                "api_endpoint": "https://api.penguinsama.com",
                "is_image_generation": True,
            }
        )
        assert config.api_endpoint == "https://api.penguinsama.com"

    def test_chat_config_endpoint_keeps_suffix_behavior(self, db_session: Session):
        """非生图配置仍按聊天协议规范化补 /v1（既有行为不回归）。"""
        pm = PricingManager(db_session)
        config = pm.create_configuration(
            {
                "provider": "penguinsama",
                "model": "some-chat-model",
                "api_key": "sk-test",
                "api_endpoint": "https://api.penguinsama.com",
            }
        )
        assert config.api_endpoint == "https://api.penguinsama.com/v1"

    def test_image_config_update_endpoint_not_suffixed(self, db_session: Session):
        """部分更新载荷缺省 is_image_generation 时从现有配置回填，端点不被补 /v1。"""
        pm = PricingManager(db_session)
        config = pm.create_configuration(
            {
                "provider": "penguinsama",
                "model": "nai-diffusion-4-full",
                "api_key": "sk-test",
                "api_endpoint": "https://api.penguinsama.com",
                "is_image_generation": True,
            }
        )
        updated = pm.update_configuration(
            config.id, {"api_endpoint": "https://other.example.com"}
        )
        assert updated is not None
        assert updated.api_endpoint == "https://other.example.com"


class TestNovelaiGeneration:
    """NovelAI 协议生图：ZIP 解析与载荷构造。"""

    PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

    @staticmethod
    def _make_zip(png_bytes: bytes) -> bytes:
        """构造内含 PNG 的 ZIP 字节流。"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("image_0.png", png_bytes)
        return buffer.getvalue()

    def _run_generate(self, content: bytes, **kwargs):
        """mock httpx 响应并执行 _generate_novelai。"""
        import asyncio

        config = {
            "id": 1,
            "provider": "novelai",
            "model": "nai-diffusion-4-full",
            "label": "novelai:nai-diffusion-4-full",
            "api_key": "sk-nai",
            "endpoint": "https://api.penguinsama.com",
        }
        with patch("core.image_generation.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            response = MagicMock()
            response.status_code = 200
            response.content = content
            instance.post = AsyncMock(return_value=response)
            images = asyncio.run(
                _generate_novelai(config, "a cat", "lowres", 832, 1216, 1, kwargs.get("generation_params"))
            )
            return images, instance.post

    def test_zip_response_extracted(self):
        """标准 ZIP 响应解出 PNG。"""
        images, _ = self._run_generate(self._make_zip(self.PNG_BYTES))
        assert len(images) == 1
        assert images[0]["data"] == self.PNG_BYTES

    def test_raw_png_response_accepted(self):
        """直接返回 PNG 二进制的站点兼容。"""
        images, _ = self._run_generate(self.PNG_BYTES)
        assert images[0]["data"] == self.PNG_BYTES

    def test_invalid_response_raises(self):
        """既非 ZIP 也非 PNG 的响应必须显式报错。"""
        with pytest.raises(ValueError, match="既非 ZIP 也非 PNG"):
            self._run_generate(b"not an image at all")

    def test_payload_structure(self):
        """载荷符合 NovelAI 协议：action/input/model/parameters 与采样器映射。"""
        images, mock_post = self._run_generate(
            self._make_zip(self.PNG_BYTES),
            generation_params={"steps": 23, "cfg_scale": 5.5, "sampler_name": "Euler a", "scheduler": "karras", "seed": 42},
        )
        assert images
        payload = mock_post.call_args.kwargs["json"]
        assert payload["action"] == "generate"
        assert payload["input"] == "a cat"
        assert payload["model"] == "nai-diffusion-4-full"
        params = payload["parameters"]
        assert params["negative_prompt"] == "lowres"
        assert params["width"] == 832
        assert params["height"] == 1216
        assert params["steps"] == 23
        assert params["scale"] == 5.5
        assert params["seed"] == 42
        # A1111 采样器名映射为 NovelAI 等价名
        assert params["sampler"] == "k_euler_ancestral"
        assert params["noise_schedule"] == "karras"
        # v4 提示词结构与 ST novelai.js 对齐
        assert params["v4_prompt"]["caption"]["base_caption"] == "a cat"
        assert params["v4_negative_prompt"]["caption"]["base_caption"] == "lowres"
        # 端点推导：根地址补 /ai/generate-image
        assert mock_post.call_args.args[0] == "https://api.penguinsama.com/ai/generate-image"

    def test_seed_negative_randomized(self):
        """seed<0（随机）时载荷内 seed 为 0-9999999999 的随机值。"""
        images, mock_post = self._run_generate(
            self._make_zip(self.PNG_BYTES), generation_params={"seed": -1}
        )
        assert images
        seed = mock_post.call_args.kwargs["json"]["parameters"]["seed"]
        assert 0 <= seed <= 9999999999

    def test_queue_full_retries_then_succeeds(self):
        """429 队列满时自动退避重试，恢复后成功出图。"""
        import asyncio

        config = {
            "id": 1,
            "provider": "novelai",
            "model": "nai-diffusion-4-full",
            "label": "novelai:nai-diffusion-4-full",
            "api_key": "sk-nai",
            "endpoint": "https://api.penguinsama.com",
        }
        zip_content = self._make_zip(self.PNG_BYTES)
        with patch("core.image_generation.httpx.AsyncClient") as mock_client, patch(
            "core.image_generation.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            instance = mock_client.return_value.__aenter__.return_value
            resp_429 = MagicMock(status_code=429, text='{"error":"队列已满（14/14）"}')
            resp_ok = MagicMock(status_code=200, content=zip_content)
            instance.post = AsyncMock(side_effect=[resp_429, resp_429, resp_ok])
            images = asyncio.run(
                _generate_novelai(config, "a cat", None, 512, 512, 1, None)
            )

        assert images[0]["data"] == self.PNG_BYTES
        assert instance.post.await_count == 3
        # 两次退避等待（10s + 20s）
        assert mock_sleep.await_count == 2

    def test_queue_full_exhausted_raises(self):
        """重试耗尽仍 429 时抛出带站点响应明细的错误。"""
        import asyncio

        config = {
            "id": 1,
            "provider": "novelai",
            "model": "nai-diffusion-4-full",
            "label": "novelai:nai-diffusion-4-full",
            "api_key": "sk-nai",
            "endpoint": "https://api.penguinsama.com",
        }
        with patch("core.image_generation.httpx.AsyncClient") as mock_client, patch(
            "core.image_generation.asyncio.sleep", new_callable=AsyncMock
        ):
            instance = mock_client.return_value.__aenter__.return_value
            resp_429 = MagicMock(status_code=429, text='{"error":"队列已满"}')
            instance.post = AsyncMock(return_value=resp_429)
            with pytest.raises(ValueError, match="429"):
                asyncio.run(_generate_novelai(config, "a cat", None, 512, 512, 1, None))
        # 初始请求 + 4 次重试
        assert instance.post.await_count == 5


# ---------------------------------------------------------------------------
# 插件入口与工具 handler 测试
# ---------------------------------------------------------------------------


class TestImageGenerationSchema:
    """生图模型字段的 Pydantic schema 定义。"""

    def test_create_request_defaults(self):
        """创建请求新增字段默认值：生图标记 False、用途 None。"""
        request = ModelConfigCreateRequest(
            provider="openai",
            model="gpt-image-1",
        )
        assert request.is_image_generation is False
        assert request.image_generation_usage is None

    def test_create_request_accepts_image_fields(self):
        """创建请求接受生图标记与用途描述。"""
        request = ModelConfigCreateRequest(
            provider="dashscope",
            model="qwen-image",
            is_image_generation=True,
            image_generation_usage="国风插画",
        )
        assert request.is_image_generation is True
        assert request.image_generation_usage == "国风插画"


class TestImageGenerationDefaultProtection:
    """生图模型禁止设为默认聊天模型的 fail-closed 防护。"""

    def test_create_rejects_image_and_default_together(self, db_session: Session):
        """创建时生图标记与默认标记并存必须抛 ValueError。"""
        manager = PricingManager(db_session)
        with pytest.raises(ValueError, match="不能设为默认聊天模型"):
            manager.create_configuration(
                {
                    "provider": "openai",
                    "model": "gpt-image-1",
                    "is_image_generation": True,
                    "is_default": True,
                }
            )

    def test_create_image_model_not_default(self, db_session: Session):
        """仅生图标记（非默认）可正常创建。"""
        manager = PricingManager(db_session)
        config = manager.create_configuration(
            {
                "provider": "openai",
                "model": "gpt-image-1",
                "is_image_generation": True,
                "is_default": False,
                "image_generation_usage": "写实风格",
            }
        )
        assert config.is_image_generation is True
        assert config.is_default is False
        assert config.image_generation_usage == "写实风格"

    def test_update_existing_image_model_to_default_rejected(self, db_session: Session):
        """把已存在的生图模型更新为默认必须抛 ValueError。"""
        config = _create_image_config(db_session)
        manager = PricingManager(db_session)
        with pytest.raises(ValueError, match="不能设为默认聊天模型"):
            manager.update_configuration(config.id, {"is_default": True})

    def test_set_default_on_image_model_rejected(self, db_session: Session):
        """对生图模型调用 set-default 必须抛 ValueError。"""
        config = _create_image_config(db_session)
        manager = PricingManager(db_session)
        with pytest.raises(ValueError, match="不能设为默认聊天模型"):
            manager.set_default_configuration(config.id)

    def test_set_default_on_chat_model_ok(self, db_session: Session):
        """普通聊天模型可正常设为默认。"""
        config = _create_image_config(db_session, is_image_generation=False)
        manager = PricingManager(db_session)
        result = manager.set_default_configuration(config.id)
        assert result.is_default is True


class TestImageGenerationPlugin:
    """插件入口类。"""

    def test_plugin_metadata(self):
        """插件名称/版本/描述。"""
        plugin = ImageGenerationPlugin()
        assert plugin.name == "image-generation-builtin"
        assert plugin.version == "1.0.0"
        assert "生图" in plugin.description

    def test_initialize_loads_tools(self):
        """initialize 后 get_tools 返回 image_generate 工具。"""
        import asyncio

        plugin = ImageGenerationPlugin()
        assert asyncio.run(plugin.initialize()) is True
        tools = plugin.get_tools()
        assert [t["name"] for t in tools] == ["image_generate"]

    def test_execute_fallback_calls_handler(self, db_session: Session):
        """旧版 execute(action=...) 入口降级到 handler 调用。"""
        import asyncio

        plugin = ImageGenerationPlugin()
        asyncio.run(plugin.initialize())
        with patch(
            "plugins.image_generation_builtin.tools.generate_image",
            new_callable=AsyncMock,
        ) as mock_generate:
            mock_generate.return_value = {
                "ok": True,
                "model": {"label": "openai:gpt-image-1"},
                "protocol": "openai",
                "size": "1024x1024",
                "n": 1,
                "images": [{"file_path": "/tmp/a.png", "format": "png", "bytes": 10}],
            }
            result = plugin.execute(
                action="image_generate",
                db=db_session,
                user_id=1,
                prompt="一只猫",
            )
            # handler 是协程函数，execute 返回未 await 的协程（与 bilibili 插件一致）
            assert asyncio.iscoroutine(result)
            asyncio.run(result)
            mock_generate.assert_awaited_once_with(
                db_session,
                prompt="一只猫",
                config_id=None,
                size="1024x1024",
                n=1,
                quality=None,
            )

    def test_execute_unknown_action_raises(self):
        """未知 action 必须抛 NotImplementedError。"""
        import asyncio

        plugin = ImageGenerationPlugin()
        asyncio.run(plugin.initialize())
        with pytest.raises(NotImplementedError):
            plugin.execute(action="no_such_tool")

    def test_cleanup_resets_state(self):
        """cleanup 清空工具列表并复位初始化标记。"""
        import asyncio

        plugin = ImageGenerationPlugin()
        asyncio.run(plugin.initialize())
        plugin.cleanup()
        assert plugin.get_tools() == []
        assert plugin._initialized is False


class TestImageGenerateTool:
    """image_generate 工具 handler。"""

    def test_tool_definition_shape(self):
        """工具定义包含 name / description / parameters / handler。"""
        tool = IMAGE_GENERATION_TOOLS[0]
        assert tool["name"] == "image_generate"
        assert tool["handler"] is image_generate
        assert tool["parameters"]["type"] == "object"
        assert "prompt" in tool["parameters"]["properties"]
        assert tool["parameters"]["required"] == ["prompt"]

    def test_missing_db_injected_rejected(self):
        """db 注入缺失必须显式报错（fail-closed）。"""
        import asyncio

        with pytest.raises(ValueError, match="缺少数据库会话"):
            asyncio.run(image_generate(db=None, user_id=1, prompt="一只猫"))

    def test_handler_returns_metadata_without_b64(self, db_session: Session):
        """handler 返回元数据与保存路径，不携带大 base64 污染模型上下文。"""
        import asyncio

        with patch(
            "plugins.image_generation_builtin.tools.generate_image",
            new_callable=AsyncMock,
        ) as mock_generate:
            mock_generate.return_value = {
                "ok": True,
                "model": {"id": 1, "provider": "openai", "model": "gpt-image-1", "label": "openai:gpt-image-1"},
                "protocol": "openai",
                "size": "1024x1024",
                "n": 1,
                "images": [
                    {"b64_json": "AAA", "format": "png", "file_path": "/var/data/generated/a.png", "bytes": 10}
                ],
            }
            result = asyncio.run(image_generate(db_session, user_id=1, prompt="一只猫"))

        assert result["ok"] is True
        assert "b64_json" not in result["images"][0]
        assert result["images"][0]["file_path"] == "/var/data/generated/a.png"
        assert "生图完成" in result["message"]


# ---------------------------------------------------------------------------
# REST 路由测试
# ---------------------------------------------------------------------------


class _DummyUser:
    """模拟已认证用户，满足路由依赖的最小字段集。"""

    id = "user-001"
    username = "tester"


def _override_get_current_user() -> _DummyUser:
    """返回固定用户，绕过真实认证流程。"""
    return _DummyUser()


def _override_get_db():
    """提供独立测试数据库会话。"""
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def _test_client() -> Iterator[TestClient]:
    """注入依赖覆盖并构造 TestClient，确保用例间隔离。"""
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous_overrides


class TestImageGenerationRoutes:
    """生图 REST 路由：模型列表与生图端点。"""

    def test_get_models_returns_image_models(self, db_session: Session):
        """GET /api/image-generation/models 返回生图模型列表（含 usage）。"""
        _create_image_config(db_session, usage="写实风格")
        with _test_client() as client:
            response = client.get("/api/image-generation/models")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert len(payload["models"]) == 1
        assert payload["models"][0]["usage"] == "写实风格"

    def test_generate_success(self, db_session: Session):
        """POST /api/image-generation/generate 成功返回 base64 与文件路径。"""
        _create_image_config(db_session)
        with patch(
            "plugins.image_generation_builtin.api.routes.generate_image",
            new_callable=AsyncMock,
        ) as mock_generate:
            mock_generate.return_value = {
                "ok": True,
                "model": {"id": 1, "provider": "openai", "model": "gpt-image-1", "label": "openai:gpt-image-1"},
                "protocol": "openai",
                "size": "1024x1024",
                "n": 1,
                "images": [{"b64_json": "AAA", "format": "png", "file_path": "/tmp/a.png", "bytes": 10}],
            }
            with _test_client() as client:
                response = client.post(
                    "/api/image-generation/generate",
                    json={"prompt": "一只猫", "config_id": 1},
                )
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert response.json()["images"][0]["b64_json"] == "AAA"

    def test_generate_value_error_returns_400(self, db_session: Session):
        """配置/参数错误返回显式 400 与可读错误信息。"""
        _create_image_config(db_session)
        with patch(
            "plugins.image_generation_builtin.api.routes.generate_image",
            new_callable=AsyncMock,
        ) as mock_generate:
            mock_generate.side_effect = ValueError("生图模型配置不存在: config_id=999")
            with _test_client() as client:
                response = client.post(
                    "/api/image-generation/generate",
                    json={"prompt": "一只猫", "config_id": 999},
                )
        assert response.status_code == 400
        # 项目统一错误包装：{error: {code, message, ...}}
        assert "生图模型配置不存在" in response.json()["error"]["message"]
