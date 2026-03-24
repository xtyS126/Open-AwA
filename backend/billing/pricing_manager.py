from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Set, Tuple
from billing.models import ModelPricing, ModelConfiguration
from datetime import datetime


class PricingManager:
    
    @staticmethod
    def _validate_configurations_uniqueness(configurations: List[Dict]) -> Tuple[bool, List[Tuple[str, str]]]:
        """
        验证配置列表中 provider+model 组合的唯一性
        返回: (是否唯一, 重复项列表)
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
        验证默认配置常量的唯一性(静态验证)
        在部署前调用此方法可提前发现问题
        """
        return PricingManager._validate_configurations_uniqueness(
            PricingManager.DEFAULT_CONFIGURATIONS
        )
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

    DEFAULT_CONFIGURATIONS = [
        {
            "provider": "openai",
            "model": "gpt-4",
            "display_name": "GPT-4",
            "description": "GPT最强大的通用AI模型，支持复杂推理和创意任务",
            "is_active": True,
            "is_default": True,
            "sort_order": 0
        },
        {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "display_name": "GPT-4o Mini",
            "description": "轻量高效的通用模型，适合快速响应场景",
            "is_active": True,
            "is_default": False,
            "sort_order": 1
        },
        {
            "provider": "anthropic",
            "model": "claude-3.5-sonnet",
            "display_name": "Claude 3.5 Sonnet",
            "description": "平衡推理能力与速度的模型",
            "is_active": True,
            "is_default": False,
            "sort_order": 2
        },
        {
            "provider": "google",
            "model": "gemini-2.0-flash",
            "display_name": "Gemini 2.0 Flash",
            "description": "Google 高速度多模态模型",
            "is_active": True,
            "is_default": False,
            "sort_order": 3
        },
        {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "display_name": "DeepSeek Chat",
            "description": "中文场景友好的对话模型",
            "is_active": True,
            "is_default": False,
            "sort_order": 4
        }
    ]

    def __init__(self, db: Session):
        self.db = db

    def get_pricing(self, provider: str, model: str) -> Optional[ModelPricing]:
        return self.db.query(ModelPricing).filter(
            ModelPricing.provider == provider,
            ModelPricing.model == model,
            ModelPricing.is_active == True
        ).first()

    def get_all_pricing(self, provider: Optional[str] = None) -> List[ModelPricing]:
        query = self.db.query(ModelPricing).filter(ModelPricing.is_active == True)
        if provider:
            query = query.filter(ModelPricing.provider == provider)
        return query.all()

    def get_providers(self) -> List[str]:
        results = self.db.query(ModelPricing.provider).filter(
            ModelPricing.is_active == True
        ).distinct().all()
        return [r[0] for r in results]

    def create_pricing(self, pricing_data: Dict) -> ModelPricing:
        pricing = ModelPricing(**pricing_data)
        self.db.add(pricing)
        self.db.commit()
        self.db.refresh(pricing)
        return pricing

    def update_pricing(self, pricing_id: int, pricing_data: Dict) -> Optional[ModelPricing]:
        pricing = self.db.query(ModelPricing).filter(ModelPricing.id == pricing_id).first()
        if pricing:
            for key, value in pricing_data.items():
                setattr(pricing, key, value)
            pricing.updated_at = datetime.utcnow()
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
        from loguru import logger
        
        is_unique, duplicates = self._validate_configurations_uniqueness(self.DEFAULT_CONFIGURATIONS)
        if not is_unique:
            duplicate_str = ", ".join([f"{p}/{m}" for p, m in duplicates])
            logger.error(
                f"DEFAULT_CONFIGURATIONS contains duplicate entries: {duplicate_str}. "
                f"Fix the code before deployment!"
            )
            self.db.rollback()
            raise ValueError(
                f"Configuration error: Found {len(duplicates)} duplicate(s) in DEFAULT_CONFIGURATIONS: {duplicate_str}"
            )
        
        existing_count = self.db.query(ModelConfiguration).count()
        if existing_count > 0:
            logger.info(f"Model configurations already exist ({existing_count}), skipping initialization")
            return 0
        
        count = 0
        for data in self.DEFAULT_CONFIGURATIONS:
            existing = self.db.query(ModelConfiguration).filter(
                ModelConfiguration.provider == data["provider"],
                ModelConfiguration.model == data["model"]
            ).first()
            
            if not existing:
                config = ModelConfiguration(**data)
                self.db.add(config)
                count += 1
                logger.info(f"Created default configuration: {data['provider']}/{data['model']}")
        
        self.db.commit()
        logger.info(f"Initialized {count} default model configurations")
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
        return self.db.query(ModelConfiguration).filter(
            ModelConfiguration.is_active == True
        ).order_by(ModelConfiguration.sort_order, ModelConfiguration.id).all()

    def get_configuration(self, config_id: int) -> Optional[ModelConfiguration]:
        return self.db.query(ModelConfiguration).filter(
            ModelConfiguration.id == config_id
        ).first()

    def get_default_configuration(self) -> Optional[ModelConfiguration]:
        return self.db.query(ModelConfiguration).filter(
            ModelConfiguration.is_active == True,
            ModelConfiguration.is_default == True
        ).first()

    def create_configuration(self, config_data: Dict) -> ModelConfiguration:
        if config_data.get("is_default", False):
            self.db.query(ModelConfiguration).filter(
                ModelConfiguration.is_default == True
            ).update({"is_default": False})
        
        config = ModelConfiguration(**config_data)
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)
        return config

    def update_configuration(self, config_id: int, config_data: Dict) -> Optional[ModelConfiguration]:
        config = self.db.query(ModelConfiguration).filter(
            ModelConfiguration.id == config_id
        ).first()
        
        if config:
            if config_data.get("is_default", False):
                self.db.query(ModelConfiguration).filter(
                    ModelConfiguration.is_default == True,
                    ModelConfiguration.id != config_id
                ).update({"is_default": False})
            
            for key, value in config_data.items():
                if key != "id":
                    setattr(config, key, value)
            config.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(config)
        
        return config

    def delete_configuration(self, config_id: int) -> bool:
        config = self.db.query(ModelConfiguration).filter(
            ModelConfiguration.id == config_id
        ).first()
        
        if config:
            config.is_active = False
            self.db.commit()
            return True
        return False

    def set_default_configuration(self, config_id: int) -> Optional[ModelConfiguration]:
        self.db.query(ModelConfiguration).filter(
            ModelConfiguration.is_default == True
        ).update({"is_default": False})
        
        config = self.db.query(ModelConfiguration).filter(
            ModelConfiguration.id == config_id
        ).first()
        
        if config:
            config.is_default = True
            config.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(config)
        
        return config
