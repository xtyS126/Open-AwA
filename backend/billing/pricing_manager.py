from sqlalchemy import text, or_
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Set, Tuple
from billing.models import ModelPricing, ModelConfiguration
from datetime import datetime, timezone
import json


class PricingManager:
    
    @staticmethod
    def _validate_configurations_uniqueness(configurations: List[Dict]) -> Tuple[bool, List[Tuple[str, str]]]:
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
        return (True, [])

    @staticmethod
    def normalize_provider(provider: Optional[str]) -> str:
        return (provider or "").strip().lower()

    @staticmethod
    def normalize_model(model: Optional[str]) -> str:
        return (model or "").strip()

    @staticmethod
    def parse_selected_models(selected_models: Optional[str]) -> List[str]:
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
        self.db = db

    def ensure_configuration_schema(self) -> None:
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
        provider = self.normalize_provider(provider)
        model = self.normalize_model(model)
        return self.db.query(ModelPricing).filter(
            ModelPricing.provider == provider,
            ModelPricing.model == model,
            ModelPricing.is_active == True
        ).first()

    def get_all_pricing(self, provider: Optional[str] = None) -> List[ModelPricing]:
        query = self.db.query(ModelPricing).filter(ModelPricing.is_active == True)
        normalized_provider = self.normalize_provider(provider)
        if normalized_provider:
            query = query.filter(ModelPricing.provider == normalized_provider)
        return query.order_by(ModelPricing.provider, ModelPricing.model).all()

    def get_provider_catalog(self) -> List[Dict]:
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
        return [provider["id"] for provider in self.get_provider_catalog()]

    def create_pricing(self, pricing_data: Dict) -> ModelPricing:
        pricing_data["provider"] = self.normalize_provider(pricing_data.get("provider"))
        pricing_data["model"] = self.normalize_model(pricing_data.get("model"))
        pricing = ModelPricing(**pricing_data)
        self.db.add(pricing)
        self.db.commit()
        self.db.refresh(pricing)
        return pricing

    def update_pricing(self, pricing_id: int, pricing_data: Dict) -> Optional[ModelPricing]:
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
        pricing = self.db.query(ModelPricing).filter(ModelPricing.id == pricing_id).first()
        if pricing:
            pricing.is_active = False
            self.db.commit()
            return True
        return False

    def initialize_default_pricing(self) -> int:
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
        return 0

    def remove_legacy_default_configurations(self) -> int:
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
        self.ensure_configuration_schema()
        return self.db.query(ModelConfiguration).filter(
            ModelConfiguration.is_active == True
        ).order_by(ModelConfiguration.sort_order, ModelConfiguration.id).all()

    def get_configuration(self, config_id: int) -> Optional[ModelConfiguration]:
        self.ensure_configuration_schema()
        return self.db.query(ModelConfiguration).filter(
            ModelConfiguration.id == config_id
        ).first()

    def get_default_configuration(self) -> Optional[ModelConfiguration]:
        self.ensure_configuration_schema()
        return self.db.query(ModelConfiguration).filter(
            ModelConfiguration.is_active == True,
            ModelConfiguration.is_default == True
        ).first()

    def get_configuration_by_provider_model(self, provider: str, model: str) -> Optional[ModelConfiguration]:
        self.ensure_configuration_schema()
        provider = self.normalize_provider(provider)
        model = self.normalize_model(model)
        return self.db.query(ModelConfiguration).filter(
            ModelConfiguration.is_active == True,
            ModelConfiguration.provider == provider,
            ModelConfiguration.model == model
        ).first()

    def get_default_provider_configuration(self, provider: str) -> Optional[ModelConfiguration]:
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
            normalized["api_endpoint"] = normalized["api_endpoint"].strip() or None
        if "api_key" in normalized and normalized.get("api_key") is not None:
            normalized["api_key"] = normalized["api_key"].strip() or None
        if "selected_models" in normalized:
            normalized["selected_models"] = self.serialize_selected_models(normalized.get("selected_models"))

        return normalized

    def create_configuration(self, config_data: Dict) -> ModelConfiguration:
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
        self.ensure_configuration_schema()
        config = self.db.query(ModelConfiguration).filter(
            ModelConfiguration.id == config_id
        ).first()
        
        if config:
            config.is_active = False
            self.db.commit()
            return True
        return False

    def set_default_configuration(self, config_id: int) -> Optional[ModelConfiguration]:
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
