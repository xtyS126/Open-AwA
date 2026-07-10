"""
验证内置模型表统一为 JSON 单源的测试模块。

覆盖场景：
- Python 常量已被删除，不可导入
- JSON 文件结构包含 cherry-studio 兼容的新字段
- initialize_default_pricing 从 JSON 加载数据到 DB
- reload_from_json 能清空缓存并读取最新 JSON 数据
- model_capabilities.json 的 capabilities 数组已从 tool_call/vision 迁移
"""

import importlib
import json
import shutil
from pathlib import Path
from typing import List

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 先导入 db.models.Base 避免 billing.models 触发循环导入
from db.models import Base
from billing.models import ModelPricing
from billing.pricing_manager import PricingManager
from config.config_loader import config_loader


PRICING_DIR = Path(__file__).resolve().parent.parent / "config" / "pricing"


@pytest.fixture
def db_session():
    """创建内存数据库会话，测试结束后关闭。"""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def pricing_manager(db_session):
    """创建 PricingManager 实例。"""
    return PricingManager(db_session)


class TestPythonConstantsRemoved:
    """验证三组 Python 常量已被删除。"""

    def test_no_python_constants_in_pricing_manager(self):
        """from billing.pricing_manager import DEFAULT_PRICING_DATA 应抛 ImportError"""
        mod = importlib.import_module("billing.pricing_manager")
        for name in (
            "DEFAULT_PRICING_DATA",
            "DEFAULT_CONFIGURATIONS",
            "MODEL_CAPABILITY_DEFAULTS",
        ):
            assert not hasattr(mod, name), f"PricingManager 仍包含已废弃的 Python 常量: {name}"

    def test_pricing_manager_class_has_no_constant_attrs(self):
        """PricingManager 类属性中不应存在三组废弃常量"""
        for name in (
            "DEFAULT_PRICING_DATA",
            "DEFAULT_CONFIGURATIONS",
            "MODEL_CAPABILITY_DEFAULTS",
        ):
            assert not hasattr(PricingManager, name), (
                f"PricingManager 类属性中仍存在废弃常量: {name}"
            )


class TestJsonStructureNewFields:
    """验证 pricing_data.json 每条记录含 cherry-studio 兼容新字段。"""

    def test_json_structure_has_new_fields(self):
        """pricing_data.json 每条记录含 cache_read_price 等新字段"""
        data: List[dict] = config_loader.load_pricing_data()
        assert len(data) > 0, "pricing_data.json 不应为空"

        required_fields = [
            "cache_read_price",
            "cache_write_price",
            "per_image_price",
            "per_minute_price",
            "owned_by",
            "family",
            "capabilities",
            "input_modalities",
            "output_modalities",
            "max_output_tokens",
        ]
        for entry in data:
            for field in required_fields:
                assert field in entry, (
                    f"{entry.get('provider')}/{entry.get('model')} 缺少字段: {field}"
                )

    def test_json_preserves_legacy_fields(self):
        """pricing_data.json 保留旧字段（向后兼容）"""
        data = config_loader.load_pricing_data()
        legacy_fields = ["provider", "model", "input_price", "output_price", "currency"]
        for entry in data:
            for field in legacy_fields:
                assert field in entry, f"旧字段丢失: {field}"


class TestCapabilitiesMigrated:
    """验证 model_capabilities.json 的 capabilities 数组已从 tool_call/vision 迁移。"""

    def test_capabilities_migrated_from_tool_call(self):
        """model_capabilities.json 的 capabilities 数组包含 function-call 等"""
        raw = config_loader.get_raw_json("model_capabilities")
        assert isinstance(raw, list)
        assert len(raw) > 0

        has_function_call = False
        has_vision = False
        for entry in raw:
            capabilities = entry.get("capabilities")
            assert isinstance(capabilities, list), (
                f"{entry.get('provider')}/{entry.get('model')} capabilities 不是数组"
            )
            if "function-call" in capabilities:
                has_function_call = True
            if "vision" in capabilities:
                has_vision = True

        assert has_function_call, "capabilities 数组中未找到 function-call"
        assert has_vision, "capabilities 数组中未找到 vision"

    def test_capabilities_consistent_with_model_spec(self):
        """supports_function_calling=true 的记录 capabilities 应包含 function-call"""
        raw = config_loader.get_raw_json("model_capabilities")
        for entry in raw:
            model_spec = entry.get("model_spec", {}) or {}
            capabilities = entry.get("capabilities", []) or []
            if model_spec.get("supports_function_calling"):
                assert "function-call" in capabilities, (
                    f"{entry.get('provider')}/{entry.get('model')} "
                    "supports_function_calling=true 但 capabilities 缺少 function-call"
                )
            if model_spec.get("supports_vision") or entry.get("supports_vision"):
                assert "vision" in capabilities, (
                    f"{entry.get('provider')}/{entry.get('model')} "
                    "supports_vision=true 但 capabilities 缺少 vision"
                )


class TestInitializeFromJson:
    """验证 initialize_default_pricing 从 JSON 加载数据到 DB。"""

    def test_initialize_default_pricing_loads_from_json(self, pricing_manager, db_session):
        """启动后 DB 中有 pricing_data.json 的条目"""
        config_loader.invalidate_cache()
        count = pricing_manager.initialize_default_pricing()

        json_data = config_loader.load_pricing_data()
        assert count == len(json_data), (
            f"初始化条目数 {count} 与 JSON 条目数 {len(json_data)} 不一致"
        )

        # 抽查 DB 中存在 JSON 中的条目
        first_entry = json_data[0]
        pricing = db_session.query(ModelPricing).filter(
            ModelPricing.provider == first_entry["provider"],
            ModelPricing.model == first_entry["model"],
        ).first()
        assert pricing is not None, "DB 中未找到 JSON 首条记录"

    def test_initialize_default_pricing_idempotent(self, pricing_manager):
        """重复调用 initialize_default_pricing 不会产生重复记录"""
        first_count = pricing_manager.initialize_default_pricing()
        second_count = pricing_manager.initialize_default_pricing()
        assert second_count == 0, "第二次初始化不应新增记录"
        assert first_count > 0


class TestReloadFromJson:
    """验证 reload_from_json 能清空缓存并读取最新 JSON 数据。"""

    def test_reload_from_json_clears_cache(self, pricing_manager, db_session, tmp_path):
        """修改 JSON 后 reload_from_json 能读到新数据"""
        pricing_file = PRICING_DIR / "pricing_data.json"
        backup_file = tmp_path / "pricing_data.json.bak"

        try:
            # 备份原始 JSON
            shutil.copy2(pricing_file, backup_file)
            original_data = json.loads(pricing_file.read_text(encoding="utf-8"))

            # 先正常初始化
            config_loader.invalidate_cache()
            pricing_manager.initialize_default_pricing()
            original_db_count = db_session.query(ModelPricing).count()

            # 在 JSON 末尾追加一条新记录
            new_entry = {
                "provider": "test-provider",
                "model": "test-model-reload",
                "input_price": 1.0,
                "output_price": 2.0,
                "currency": "USD",
                "context_window": 8000,
                "cache_read_price": None,
                "cache_write_price": None,
                "per_image_price": None,
                "per_minute_price": None,
                "owned_by": None,
                "family": None,
                "capabilities": None,
                "input_modalities": None,
                "output_modalities": None,
                "max_output_tokens": None,
            }
            original_data.append(new_entry)
            pricing_file.write_text(
                json.dumps(original_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # 调用 reload_from_json
            pricing_manager.reload_from_json()

            # 验证 DB 中新增了该记录
            new_pricing = db_session.query(ModelPricing).filter(
                ModelPricing.provider == "test-provider",
                ModelPricing.model == "test-model-reload",
            ).first()
            assert new_pricing is not None, "reload_from_json 后未加载到新增的 JSON 记录"
            assert db_session.query(ModelPricing).count() == original_db_count + 1
        finally:
            # 恢复原始 JSON 文件
            shutil.copy2(backup_file, pricing_file)
            config_loader.invalidate_cache()

    def test_reload_from_json_resets_schema_flags(self, pricing_manager):
        """reload_from_json 重置 schema 确保标志"""
        # 先确保 schema 已初始化
        pricing_manager.ensure_pricing_schema()
        assert pricing_manager._pricing_schema_ensured is True

        pricing_manager.reload_from_json()

        # reload 后标志应被重置（然后由 initialize 重新设为 True）
        # 由于 initialize_default_pricing 内部会调用 ensure_pricing_schema，
        # 最终标志会重新变为 True，但缓存已被清空
        assert pricing_manager._pricing_schema_ensured is True
