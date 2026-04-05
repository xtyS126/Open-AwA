"""
计费与用量管理模块，负责价格配置、预算控制、用量追踪与报表能力。
这一部分直接关联成本核算、调用统计以及运维观测。
"""

from sqlalchemy import text, or_
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Set, Tuple
from billing.models import ModelPricing, ModelConfiguration
from datetime import datetime, timezone
import json


class PricingManager:
    
    """
    封装与PricingManager相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    @staticmethod
    def _validate_configurations_uniqueness(configurations: List[Dict]) -> Tuple[bool, List[Tuple[str, str]]]:
        """
        处理validate、configurations、uniqueness相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        seen: Set[Tuple[str, str]] = set()
        duplicates: List[Tuple[str, str]] = []
        
        for config in configurations:
            key = (config["provider"], config["model"])
            if key in seen:
                duplicates.append(key)
            else:
                seen.add(key)
        
        return (len(duplicates) == 0, duplicates)
    
    @staticmethod
    def validate_default_configurations() -> Tuple[bool, List[Tuple[str, str]]]:
        """
        校验default、configurations相关输入、规则或结构是否合法。
        返回结果通常用于阻止非法输入继续流入后续链路。
        """
        return PricingManager._validate_configurations_uniqueness(PricingManager.DEFAULT_CONFIGURATIONS)

    @staticmethod
    def normalize_provider(provider: Optional[str]) -> str:
        """
        规范化provider相关输入、配置或字段值。
        该步骤主要用于降低外部输入不一致性对内部逻辑的影响。
        """
        return (provider or "").strip().lower()

    @staticmethod
    def normalize_model(model: Optional[str]) -> str:
        """
        规范化model相关输入、配置或字段值。
        该步骤主要用于降低外部输入不一致性对内部逻辑的影响。
        """
        return (model or "").strip()

    @staticmethod
    def _normalize_provider_api_endpoint(provider: Optional[str], api_endpoint: Optional[str]) -> Optional[str]:
        """
        处理normalize、provider、api、endpoint相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        raw = (api_endpoint or "").strip()
        if not raw:
            return None

        normalized_provider = PricingManager.normalize_provider(provider)
        suffix_map = {
            "openai": "/v1/chat/completions",
            "deepseek": "/v1/chat/completions",
            "moonshot": "/v1/chat/completions",
            "alibaba": "/compatible-mode/v1/chat/completions",
            "zhipu": "/api/paas/v4/chat/completions",
            "anthropic": "/v1/messages",
            "google": "/v1beta/models",
        }
        default_suffix = suffix_map.get(normalized_provider, "/v1/chat/completions")
        known_suffixes = {default_suffix, *suffix_map.values()}

        trimmed = raw.rstrip("/")
        lowered = trimmed.lower()
        if any(lowered.endswith(suffix.lower()) for suffix in known_suffixes):
            return trimmed

        path_name = ""
        try:
            from urllib.parse import urlparse
            path_name = (urlparse(raw).path or "").lower()
        except Exception:
            path_name = ""

        is_base_path = path_name in {"", "/", "/v1", "/v1beta", "/api"}
        if not is_base_path:
            return trimmed

        return f"{trimmed}{default_suffix}"

    @staticmethod
    def parse_selected_models(selected_models: Optional[str]) -> List[str]:
        """
        解析selected、models相关输入内容，并转换为内部可用结构。
        它常用于屏蔽外部协议差异并统一上层业务使用的数据格式。
        """
        if not selected_models:
            return []

        try:
            data = json.loads(selected_models)
        except (TypeError, ValueError):
            return []

        if not isinstance(data, list):
            return []

        normalized: List[str] = []
        seen: Set[str] = set()
        for item in data:
            model = PricingManager.normalize_model(str(item))
            if not model or model in seen:
                continue
            seen.add(model)
            normalized.append(model)

        return normalized

    @staticmethod
    def serialize_selected_models(selected_models: Optional[List[str]]) -> str:
        """
        将selected、models相关对象序列化为接口或存储所需格式。
        通常用于在内部对象与外部输出结构之间建立稳定映射。
        """
        normalized: List[str] = []
        seen: Set[str] = set()

        for item in selected_models or []:
            model = PricingManager.normalize_model(str(item))
            if not model or model in seen:
                continue
            seen.add(model)
            normalized.append(model)

        return json.dumps(normalized, ensure_ascii=False)

    LEGACY_DEFAULT_CONFIGURATION_KEYS = [
        ("openai", "gpt-4"),
        ("openai", "gpt-4o-mini"),
        ("anthropic", "claude-3.5-sonnet"),
        ("google", "gemini-2.0-flash"),
        ("deepseek", "deepseek-chat")
    ]

    DEFAULT_CONFIGURATIONS = [
        {
            "provider": "openai",
            "model": "gpt-4",
            "display_name": "GPT-4",
            "description": "最强大的通用AI模型",
            "is_active": True,
            "is_default": True,
            "sort_order": 0,
        },
        {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "display_name": "GPT-4o Mini",
            "description": "兼顾速度与成本的轻量模型",
            "is_active": True,
            "is_default": False,
            "sort_order": 1,
        },
        {
            "provider": "anthropic",
            "model": "claude-3.5-sonnet",
            "display_name": "Claude 3.5 Sonnet",
            "description": "适合复杂推理与长文本处理",
            "is_active": True,
            "is_default": False,
            "sort_order": 2,
        },
        {
            "provider": "google",
            "model": "gemini-2.0-flash",
            "display_name": "Gemini 2.0 Flash",
            "description": "响应快速，适合高频交互场景",
            "is_active": True,
            "is_default": False,
            "sort_order": 3,
        },
        {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "display_name": "DeepSeek Chat",
            "description": "适用于中文对话与通用生成任务",
            "is_active": True,
            "is_default": False,
            "sort_order": 4,
        },
    ]

    DEFAULT_PRICING_DATA = [
        {
            "provider": "openai",
            "model": "gpt-4.1",
            "input_price": 6.00,
            "output_price": 18.00,
            "currency": "USD",
            "context_window": 1000000
        },
        {
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "input_price": 0.30,
            "output_price": 1.20,
            "currency": "USD",
            "context_window": 1000000
        },
        {
            "provider": "openai",
            "model": "gpt-4.1-nano",
            "input_price": 0.10,
            "output_price": 0.40,
            "currency": "USD",
            "context_window": 1000000
        },
        {
            "provider": "openai",
            "model": "o1",
            "input_price": 15.00,
            "output_price": 60.00,
            "currency": "USD",
            "context_window": 100000
        },
        {
            "provider": "openai",
            "model": "gpt-4o",
            "input_price": 6.00,
            "output_price": 18.00,
            "currency": "USD",
            "context_window": 1000000
        },
        {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "input_price": 0.30,
            "output_price": 1.20,
            "currency": "USD",
            "context_window": 1000000
        },
        {
            "provider": "anthropic",
            "model": "claude-3.5-sonnet",
            "input_price": 3.00,
            "output_price": 15.00,
            "currency": "USD",
            "context_window": 200000
        },
        {
            "provider": "anthropic",
            "model": "claude-3.5-haiku",
            "input_price": 0.80,
            "output_price": 4.00,
            "currency": "USD",
            "context_window": 200000
        },
        {
            "provider": "google",
            "model": "gemini-2.0-flash",
            "input_price": 0.075,
            "output_price": 0.30,
            "currency": "USD",
            "context_window": 1000000
        },
        {
            "provider": "google",
            "model": "gemini-3.1-flash-lite",
            "input_price": 0.25,
            "output_price": 1.50,
            "currency": "USD",
            "context_window": 1000000
        },
        {
            "provider": "google",
            "model": "gemini-2.0-pro",
            "input_price": 1.25,
            "output_price": 10.00,
            "currency": "USD",
            "context_window": 2000000
        },
        {
            "provider": "deepseek",
            "model": "deepseek-v3",
            "input_price": 2.00,
            "output_price": 8.00,
            "currency": "CNY",
            "cache_hit_price": 1.00,
            "context_window": 640000
        },
        {
            "provider": "deepseek",
            "model": "deepseek-r1",
            "input_price": 4.00,
            "output_price": 16.00,
            "currency": "CNY",
            "cache_hit_price": 1.00,
            "context_window": 640000
        },
        {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "input_price": 2.00,
            "output_price": 8.00,
            "currency": "CNY",
            "context_window": 128000
        },
        {
            "provider": "alibaba",
            "model": "qwen-long",
            "input_price": 0.50,
            "output_price": 2.00,
            "currency": "CNY",
            "context_window": 10000000
        },
        {
            "provider": "alibaba",
            "model": "qwen3",
            "input_price": 0.80,
            "output_price": 3.20,
            "currency": "CNY",
            "context_window": 1000000
        },
        {
            "provider": "alibaba",
            "model": "qwen2.5-turbo",
            "input_price": 0.60,
            "output_price": 2.40,
            "currency": "CNY",
            "context_window": 1000000
        },
        {
            "provider": "moonshot",
            "model": "kimi-128k",
            "input_price": 60.00,
            "output_price": 60.00,
            "currency": "CNY",
            "context_window": 128000
        },
        {
            "provider": "moonshot",
            "model": "kimi-vision-8k",
            "input_price": 12.00,
            "output_price": 12.00,
            "currency": "CNY",
            "context_window": 8000
        },
        {
            "provider": "moonshot",
            "model": "kimi-vision-32k",
            "input_price": 24.00,
            "output_price": 24.00,
            "currency": "CNY",
            "context_window": 32000
        },
        {
            "provider": "moonshot",
            "model": "kimi-vision-128k",
            "input_price": 60.00,
            "output_price": 60.00,
            "currency": "CNY",
            "context_window": 128000
        },
        {
            "provider": "zhipu",
            "model": "glm-4",
            "input_price": 0.50,
            "output_price": 1.00,
            "currency": "CNY",
            "context_window": 128000
        },
        {
            "provider": "zhipu",
            "model": "glm-4-plus",
            "input_price": 1.00,
            "output_price": 2.00,
            "currency": "CNY",
            "context_window": 128000
        }
    ]

    def __init__(self, db: Session):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.db = db

    def ensure_configuration_schema(self) -> None:
        """
        确保configuration、schema相关前置条件或数据结构已经准备完成。
        通常用于在真正执行业务前补齐环境、表结构或缺失配置。
        """
        columns = {
            row[1]
            for row in self.db.execute(text("PRAGMA table_info(model_configurations)")).fetchall()
        }

        if "icon" not in columns:
            self.db.execute(text("ALTER TABLE model_configurations ADD COLUMN icon VARCHAR"))
        if "selected_models" not in columns:
            self.db.execute(text("ALTER TABLE model_configurations ADD COLUMN selected_models TEXT"))

        self.db.commit()

    def get_pricing(self, provider: str, model: str) -> Optional[ModelPricing]:
        """
        获取pricing相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        provider = self.normalize_provider(provider)
        model = self.normalize_model(model)
        return self.db.query(ModelPricing).filter(
            ModelPricing.provider == provider,
            ModelPricing.model == model,
            ModelPricing.is_active == True
        ).first()

    def get_all_pricing(self, provider: Optional[str] = None) -> List[ModelPricing]:
        """
        获取all、pricing相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        query = self.db.query(ModelPricing).filter(ModelPricing.is_active == True)
        normalized_provider = self.normalize_provider(provider)
        if normalized_provider:
            query = query.filter(ModelPricing.provider == normalized_provider)
        return query.order_by(ModelPricing.provider, ModelPricing.model).all()

    def get_provider_catalog(self) -> List[Dict]:
        """
        获取provider、catalog相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        config_rows = self.db.query(ModelConfiguration.provider).filter(
            ModelConfiguration.is_active == True
        ).distinct().all()

        provider_ids = sorted({
            self.normalize_provider(row[0])
            for row in config_rows
            if self.normalize_provider(row[0])
        })

        provider_names = {
            "openai": "OpenAI",
            "anthropic": "Anthropic",
            "google": "Google",
            "deepseek": "DeepSeek",
            "alibaba": "阿里通义千问",
            "moonshot": "Kimi",
            "zhipu": "智谱AI"
        }

        result = []
        for provider_id in provider_ids:
            config = self.get_default_provider_configuration(provider_id)
            if not config:
                continue

            selected_models = self.parse_selected_models(config.selected_models)
            result.append({
                "id": provider_id,
                "name": provider_names.get(provider_id, provider_id.upper()),
                "display_name": config.display_name or provider_names.get(provider_id, provider_id.upper()),
                "icon": config.icon,
                "api_endpoint": config.api_endpoint,
                "has_api_key": bool(config.api_key),
                "selected_models": selected_models,
                "configuration_count": self.db.query(ModelConfiguration).filter(
                    ModelConfiguration.provider == provider_id,
                    ModelConfiguration.is_active == True
                ).count()
            })
        return result

    def get_providers(self) -> List[str]:
        """
        获取providers相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        return [provider["id"] for provider in self.get_provider_catalog()]

    def create_pricing(self, pricing_data: Dict) -> ModelPricing:
        """
        创建pricing相关对象、记录或执行结果。
        实现过程中往往会涉及初始化、组装、持久化或返回统一结构。
        """
        pricing_data["provider"] = self.normalize_provider(pricing_data.get("provider"))
        pricing_data["model"] = self.normalize_model(pricing_data.get("model"))
        pricing = ModelPricing(**pricing_data)
        self.db.add(pricing)
        self.db.commit()
        self.db.refresh(pricing)
        return pricing

    def update_pricing(self, pricing_id: int, pricing_data: Dict) -> Optional[ModelPricing]:
        """
        更新pricing相关数据、配置或状态。
        阅读时需要重点关注覆盖规则、副作用以及更新后的数据一致性。
        """
        pricing = self.db.query(ModelPricing).filter(ModelPricing.id == pricing_id).first()
        if pricing:
            if "provider" in pricing_data:
                pricing_data["provider"] = self.normalize_provider(pricing_data.get("provider"))
            if "model" in pricing_data:
                pricing_data["model"] = self.normalize_model(pricing_data.get("model"))
            for key, value in pricing_data.items():
                setattr(pricing, key, value)
            pricing.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(pricing)
        return pricing

    def delete_pricing(self, pricing_id: int) -> bool:
        """
        删除pricing相关对象或持久化记录。
        实现中通常还会同时处理资源释放、状态回收或关联数据清理。
        """
        pricing = self.db.query(ModelPricing).filter(ModelPricing.id == pricing_id).first()
        if pricing:
            pricing.is_active = False
            self.db.commit()
            return True
        return False

    def initialize_default_pricing(self) -> int:
        """
        处理initialize、default、pricing相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        count = 0
        for data in self.DEFAULT_PRICING_DATA:
            existing = self.db.query(ModelPricing).filter(
                ModelPricing.provider == data["provider"],
                ModelPricing.model == data["model"]
            ).first()
            
            if not existing:
                pricing = ModelPricing(**data)
                self.db.add(pricing)
                count += 1
        
        self.db.commit()
        return count

    def initialize_default_configurations(self) -> int:
        """
        处理initialize、default、configurations相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.ensure_configuration_schema()

        existing_count = self.db.query(ModelConfiguration).count()
        if existing_count > 0:
            return 0

        is_unique, duplicates = self.validate_default_configurations()
        if not is_unique:
            duplicate_text = ", ".join(f"{provider}/{model}" for provider, model in duplicates)
            raise ValueError(f"Duplicate default configurations found: {duplicate_text}")

        count = 0
        for data in self.DEFAULT_CONFIGURATIONS:
            normalized = self._normalize_configuration_payload(data)
            config = ModelConfiguration(**normalized)
            self.db.add(config)
            count += 1

        self.db.commit()
        return count

    def remove_legacy_default_configurations(self) -> int:
        """
        移除legacy、default、configurations相关数据、缓存或配置项。
        这类逻辑常用于运行时清理、兼容性整理或状态维护。
        """
        self.ensure_configuration_schema()

        conditions = [
            (ModelConfiguration.provider == provider) & (ModelConfiguration.model == model)
            for provider, model in self.LEGACY_DEFAULT_CONFIGURATION_KEYS
        ]

        if not conditions:
            return 0

        rows = self.db.query(ModelConfiguration).filter(
            or_(*conditions),
            ModelConfiguration.api_key.is_(None)
        ).all()

        count = len(rows)
        if count == 0:
            return 0

        for row in rows:
            self.db.delete(row)

        self.db.commit()
        return count

    def validate_pricing_data(self, data: Dict) -> tuple:
        """
        校验pricing、data相关输入、规则或结构是否合法。
        返回结果通常用于阻止非法输入继续流入后续链路。
        """
        errors = []
        
        if "input_price" in data:
            if not isinstance(data["input_price"], (int, float)) or data["input_price"] < 0:
                errors.append("input_price must be a non-negative number")
        
        if "output_price" in data:
            if not isinstance(data["output_price"], (int, float)) or data["output_price"] < 0:
                errors.append("output_price must be a non-negative number")
        
        if "currency" in data:
            if data["currency"] not in ["USD", "CNY"]:
                errors.append("currency must be USD or CNY")
        
        if "cache_hit_price" in data:
            if data["cache_hit_price"] is not None:
                if not isinstance(data["cache_hit_price"], (int, float)) or data["cache_hit_price"] < 0:
                    errors.append("cache_hit_price must be a non-negative number")
        
        return (len(errors) == 0, errors)

    def get_active_configurations(self) -> List[ModelConfiguration]:
        """
        获取active、configurations相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        self.ensure_configuration_schema()
        return self.db.query(ModelConfiguration).filter(
            ModelConfiguration.is_active == True
        ).order_by(ModelConfiguration.sort_order, ModelConfiguration.id).all()

    def get_configuration(self, config_id: int) -> Optional[ModelConfiguration]:
        """
        获取configuration相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        self.ensure_configuration_schema()
        return self.db.query(ModelConfiguration).filter(
            ModelConfiguration.id == config_id
        ).first()

    def get_default_configuration(self) -> Optional[ModelConfiguration]:
        """
        获取default、configuration相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        self.ensure_configuration_schema()
        return self.db.query(ModelConfiguration).filter(
            ModelConfiguration.is_active == True,
            ModelConfiguration.is_default == True
        ).first()

    def get_configuration_by_provider_model(self, provider: str, model: str) -> Optional[ModelConfiguration]:
        """
        获取configuration、by、provider、model相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        self.ensure_configuration_schema()
        provider = self.normalize_provider(provider)
        model = self.normalize_model(model)
        return self.db.query(ModelConfiguration).filter(
            ModelConfiguration.is_active == True,
            ModelConfiguration.provider == provider,
            ModelConfiguration.model == model
        ).first()

    def get_default_provider_configuration(self, provider: str) -> Optional[ModelConfiguration]:
        """
        获取default、provider、configuration相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        self.ensure_configuration_schema()
        provider = self.normalize_provider(provider)
        query = self.db.query(ModelConfiguration).filter(
            ModelConfiguration.provider == provider,
            ModelConfiguration.is_active == True
        )

        default_config = query.filter(ModelConfiguration.is_default == True).first()
        if default_config:
            return default_config

        return query.order_by(ModelConfiguration.sort_order, ModelConfiguration.id).first()

    def _normalize_configuration_payload(self, config_data: Dict) -> Dict:
        """
        处理normalize、configuration、payload相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        normalized = dict(config_data)

        if "provider" in normalized:
            normalized["provider"] = self.normalize_provider(normalized.get("provider"))
        if "model" in normalized:
            normalized["model"] = self.normalize_model(normalized.get("model"))
        if "display_name" in normalized and normalized.get("display_name") is not None:
            normalized["display_name"] = normalized["display_name"].strip() or None
        if "description" in normalized and normalized.get("description") is not None:
            normalized["description"] = normalized["description"].strip() or None
        if "icon" in normalized and normalized.get("icon") is not None:
            normalized["icon"] = normalized["icon"].strip() or None
        if "api_endpoint" in normalized and normalized.get("api_endpoint") is not None:
            normalized["api_endpoint"] = self._normalize_provider_api_endpoint(
                normalized.get("provider"),
                normalized.get("api_endpoint")
            )
        if "api_key" in normalized and normalized.get("api_key") is not None:
            normalized["api_key"] = normalized["api_key"].strip() or None
        if "selected_models" in normalized:
            normalized["selected_models"] = self.serialize_selected_models(normalized.get("selected_models"))

        return normalized

    def create_configuration(self, config_data: Dict) -> ModelConfiguration:
        """
        创建configuration相关对象、记录或执行结果。
        实现过程中往往会涉及初始化、组装、持久化或返回统一结构。
        """
        self.ensure_configuration_schema()
        normalized = self._normalize_configuration_payload(config_data)

        if normalized.get("is_default", False):
            self.db.query(ModelConfiguration).filter(
                ModelConfiguration.is_default == True
            ).update({"is_default": False})
        
        config = ModelConfiguration(**normalized)
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)
        return config

    def update_configuration(self, config_id: int, config_data: Dict) -> Optional[ModelConfiguration]:
        """
        更新configuration相关数据、配置或状态。
        阅读时需要重点关注覆盖规则、副作用以及更新后的数据一致性。
        """
        self.ensure_configuration_schema()
        config = self.db.query(ModelConfiguration).filter(
            ModelConfiguration.id == config_id
        ).first()
        
        if config:
            normalized = self._normalize_configuration_payload(config_data)

            if normalized.get("is_default", False):
                self.db.query(ModelConfiguration).filter(
                    ModelConfiguration.is_default == True,
                    ModelConfiguration.id != config_id
                ).update({"is_default": False})
            
            for key, value in normalized.items():
                if key != "id":
                    setattr(config, key, value)
            config.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(config)
        
        return config

    def delete_configuration(self, config_id: int) -> bool:
        """
        删除configuration相关对象或持久化记录。
        实现中通常还会同时处理资源释放、状态回收或关联数据清理。
        """
        self.ensure_configuration_schema()
        config = self.db.query(ModelConfiguration).filter(
            ModelConfiguration.id == config_id
        ).first()
        
        if config:
            config.is_active = False
            self.db.commit()
            return True
        return False

    def delete_provider_configurations(self, provider: str) -> int:
        """
        删除provider、configurations相关对象或持久化记录。
        实现中通常还会同时处理资源释放、状态回收或关联数据清理。
        """
        self.ensure_configuration_schema()
        provider_id = self.normalize_provider(provider)
        if not provider_id:
            return 0

        configs = self.db.query(ModelConfiguration).filter(
            ModelConfiguration.provider == provider_id,
            ModelConfiguration.is_active == True
        ).all()

        if len(configs) == 0:
            return 0

        now = datetime.now(timezone.utc)
        for config in configs:
            config.is_active = False
            config.updated_at = now

        self.db.commit()
        return len(configs)

    def set_default_configuration(self, config_id: int) -> Optional[ModelConfiguration]:
        """
        设置default、configuration相关配置或运行状态。
        此类方法通常会直接影响后续执行路径或运行上下文中的关键数据。
        """
        self.ensure_configuration_schema()
        self.db.query(ModelConfiguration).filter(
            ModelConfiguration.is_default == True
        ).update({"is_default": False})
        
        config = self.db.query(ModelConfiguration).filter(
            ModelConfiguration.id == config_id
        ).first()
        
        if config:
            config.is_default = True
            config.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(config)
        
        return config
