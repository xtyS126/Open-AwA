"""
计费与用量管理模块，负责价格配置、预算控制、用量追踪与报表能力。
这一部分直接关联成本核算、调用统计以及运维观测。
"""

from sqlalchemy import text, or_
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Set, Tuple
from billing.models import ModelPricing, ModelConfiguration
from config.config_loader import config_loader
from datetime import datetime, timezone
import json


class PricingManager:
    """
    计费管理器，负责模型价格配置、用量追踪与预算控制。
    提供模型定价的增删改查、供应商配置管理以及默认配置初始化等功能。
    """
    @staticmethod
    def get_provider_base_suffix(provider: Optional[str]) -> str:
        """
        返回 Provider 的基础版本路径。
        不同厂商的基础路径并不相同，不能一律强制补 `/v1`。
        """

        provider_id = PricingManager.normalize_provider(provider)
        return {
            "openai": "/v1",
            "anthropic": "/v1",
            "deepseek": "/v1",
            "google": "/v1beta",
            "alibaba": "/compatible-mode/v1",
            "qwen": "/compatible-mode/v1",
            "moonshot": "/v1",
            "zhipu": "/api/paas/v4",
            "ollama": "/v1",
        }.get(provider_id, "/v1")

    @staticmethod
    def _validate_configurations_uniqueness(configurations: List[Dict]) -> Tuple[bool, List[Tuple[str, str]]]:
        """
        校验配置列表中是否存在重复的 provider/model 组合。
        
        Args:
            configurations: 配置字典列表，每个字典需包含 provider 和 model 字段。
            
        Returns:
            元组，第一个元素表示是否唯一，第二个元素为重复项列表。
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
        校验默认配置的唯一性。
        
        Returns:
            元组，第一个元素表示是否唯一，第二个元素为重复项列表。
        """
        configurations = config_loader.load_default_configurations()
        return PricingManager._validate_configurations_uniqueness(configurations)

    @staticmethod
    def normalize_provider(provider: Optional[str]) -> str:
        """
        规范化供应商名称，转换为小写并去除首尾空格。
        
        Args:
            provider: 原始供应商名称。
            
        Returns:
            规范化后的供应商名称。
        """
        return (provider or "").strip().lower()

    @staticmethod
    def normalize_model(model: Optional[str]) -> str:
        """
        规范化模型名称，去除首尾空格。
        
        Args:
            model: 原始模型名称。
            
        Returns:
            规范化后的模型名称。
        """
        return (model or "").strip()

    @staticmethod
    def _normalize_provider_api_endpoint(provider: Optional[str], api_endpoint: Optional[str]) -> Optional[str]:
        """
        规范化供应商 API 端点地址，移除多余的后缀并添加正确的基础路径。
        
        Args:
            provider: 供应商名称。
            api_endpoint: 原始 API 端点地址。
            
        Returns:
            规范化后的 API 端点地址，若输入为空则返回 None。
        """
        raw = (api_endpoint or "").strip()
        if not raw:
            return None

        # Verify URL format if possible, just like frontend
        from urllib.parse import urlparse
        try:
            parsed = urlparse(raw)
            if not parsed.scheme or not parsed.netloc:
                pass  # We don't raise error to keep compatibility, but frontend validates it
        except Exception:
            pass

        trimmed = raw.rstrip("/")
        known_suffixes = sorted(list(dict.fromkeys([
            "/v1/chat/completions",
            "/compatible-mode/v1/chat/completions",
            "/api/paas/v4/chat/completions",
            "/v1/messages",
            "/v1beta/models",
            "/v1/models",
            "/chat/completions",
            "/models"
        ])), key=len, reverse=True)

        lowered = trimmed.lower()
        for suffix in known_suffixes:
            if lowered.endswith(suffix.lower()):
                trimmed = trimmed[: len(trimmed) - len(suffix)].rstrip("/")
                break

        base_suffix = PricingManager.get_provider_base_suffix(provider)
        if base_suffix and not trimmed.lower().endswith(base_suffix.lower()):
            trimmed = f"{trimmed}{base_suffix}"

        return trimmed or None

    @staticmethod
    def get_provider_endpoint_suffixes(provider: Optional[str]) -> Dict[str, str]:
        """
        获取provider对应的接口后缀映射。
        根据接口规范：
        - 模型列表: /models (用于 GET 请求)
        - 聊天请求: /chat/completions (用于 POST 请求)
        """
        provider_id = PricingManager.normalize_provider(provider)
        if provider_id == "anthropic":
            return {
                "chat": "/messages",
                "models": "/models",
            }
        if provider_id == "google":
            return {
                "chat": "/models",
                "models": "/models",
            }
        return {
            "chat": "/chat/completions",
            "models": "/models",
        }

    @staticmethod
    def build_provider_api_endpoint(provider: Optional[str], base_url: Optional[str], purpose: str) -> Optional[str]:
        """
        基于保存的基础 URL 构建具体用途的接口地址。
        """
        normalized_base_url = PricingManager._normalize_provider_api_endpoint(provider, base_url)
        if not normalized_base_url:
            return None

        suffixes = PricingManager.get_provider_endpoint_suffixes(provider)
        suffix = suffixes.get(purpose)
        if not suffix:
            return normalized_base_url

        lowered = normalized_base_url.lower()
        if lowered.endswith(suffix.lower()):
            return normalized_base_url

        return f"{normalized_base_url}{suffix}"

    @staticmethod
    def parse_selected_models(selected_models: Optional[str]) -> List[str]:
        """
        解析已选模型的 JSON 字符串为列表。
        
        Args:
            selected_models: JSON 格式的模型列表字符串。
            
        Returns:
            去重后的模型名称列表。
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
        将模型列表序列化为 JSON 字符串。
        
        Args:
            selected_models: 模型名称列表。
            
        Returns:
            JSON 格式的字符串。
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

    

    

    @property
    def _default_pricing_data(self):
        """从JSON文件加载默认定价数据"""
        return config_loader.load_pricing_data()

    @property
    def _default_configurations(self):
        """从JSON文件加载默认模型配置"""
        return config_loader.load_default_configurations()

    @property
    def _model_capability_defaults(self):
        """从JSON文件加载模型能力默认值"""
        return config_loader.load_model_capabilities()

    @property
    def _legacy_configuration_keys(self):
        """从JSON文件加载遗留配置键列表"""
        return config_loader.load_legacy_config_keys()

    def __init__(self, db: Session):
        """
        初始化计费管理器。
        
        Args:
            db: 数据库会话对象。
        """
        self.db = db

    def _ensure_model_pricing_schema(self) -> None:
        """
        确保 model_pricing 表包含 supports_vision 和 is_multimodal 列。
        SQLite 不支持 ALTER TABLE ADD COLUMN 带非默认值约束，
        这里通过 PRAGMA table_info 检查列是否存在，不存在则动态添加。
        """
        columns = {
            row[1]
            for row in self.db.execute(text("PRAGMA table_info(model_pricing)")).fetchall()
        }
        if "supports_vision" not in columns:
            self.db.execute(text("ALTER TABLE model_pricing ADD COLUMN supports_vision BOOLEAN DEFAULT 0"))
        if "is_multimodal" not in columns:
            self.db.execute(text("ALTER TABLE model_pricing ADD COLUMN is_multimodal BOOLEAN DEFAULT 0"))
        self.db.commit()

    def ensure_configuration_schema(self) -> None:
        """
        确保模型配置表包含必要的字段，若缺失则动态添加。
        """
        columns = {
            row[1]
            for row in self.db.execute(text("PRAGMA table_info(model_configurations)")).fetchall()
        }

        if "icon" not in columns:
            self.db.execute(text("ALTER TABLE model_configurations ADD COLUMN icon VARCHAR"))
        if "selected_models" not in columns:
            self.db.execute(text("ALTER TABLE model_configurations ADD COLUMN selected_models TEXT"))
        if "max_tokens" not in columns:
            self.db.execute(text("ALTER TABLE model_configurations ADD COLUMN max_tokens INTEGER"))

        self.db.commit()

    def get_pricing(self, provider: str, model: str) -> Optional[ModelPricing]:
        """
        获取指定供应商和模型的价格配置。
        
        Args:
            provider: 供应商名称。
            model: 模型名称。
            
        Returns:
            价格配置对象，若不存在则返回 None。
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
        获取所有激活的价格配置，可按供应商筛选。
        
        Args:
            provider: 可选的供应商名称筛选条件。
            
        Returns:
            价格配置对象列表。
        """
        query = self.db.query(ModelPricing).filter(ModelPricing.is_active == True)
        normalized_provider = self.normalize_provider(provider)
        if normalized_provider:
            query = query.filter(ModelPricing.provider == normalized_provider)
        return query.order_by(ModelPricing.provider, ModelPricing.model).all()

    def get_provider_catalog(self) -> List[Dict]:
        """
        获取供应商目录，合并数据库配置与 pricing_data.json 中的默认定价厂商。

        - 数据库中已存在的供应商标记 source: \"database\"，数据以数据库为准
        - 仅存在于 JSON 中的供应商标记 source: \"pricing_json\"，作为 fallback 条目
        - selected_models 为数据库配置与 JSON 模型的并集

        Returns:
            供应商信息字典列表，数据库条目优先，JSON fallback 条目追加在末尾。
        """
        # 1. 从数据库查询已有的供应商
        config_rows = self.db.query(ModelConfiguration.provider).filter(
            ModelConfiguration.is_active == True
        ).distinct().all()

        db_provider_ids = {
            self.normalize_provider(row[0])
            for row in config_rows
            if self.normalize_provider(row[0])
        }

        # 2. 从定价 JSON 中提取所有唯一供应商及其模型
        pricing_data = config_loader.load_pricing_data()
        json_provider_models: Dict[str, set] = {}
        for entry in pricing_data:
            pid = self.normalize_provider(entry.get("provider"))
            if not pid:
                continue
            model = self.normalize_model(entry.get("model", ""))
            if model:
                json_provider_models.setdefault(pid, set()).add(model)

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

        # 3. 处理数据库已有供应商（source: \"database\"）
        for provider_id in sorted(db_provider_ids):
            config = self.get_default_provider_configuration(provider_id)
            if not config:
                continue

            db_models = self.parse_selected_models(config.selected_models)
            json_models = json_provider_models.get(provider_id, set())
            # 数据库选中的模型在前，JSON 独有模型在后（去重保持顺序）
            merged_models = list(dict.fromkeys(
                db_models + [m for m in sorted(json_models) if m not in set(db_models)]
            ))
            result.append({
                "id": provider_id,
                "name": provider_names.get(provider_id, provider_id.upper()),
                "display_name": config.display_name or provider_names.get(provider_id, provider_id.upper()),
                "icon": config.icon,
                "api_endpoint": config.api_endpoint,
                "has_api_key": bool(config.api_key),
                "selected_models": merged_models,
                "configuration_count": self.db.query(ModelConfiguration).filter(
                    ModelConfiguration.provider == provider_id,
                    ModelConfiguration.is_active == True
                ).count(),
                "source": "database",
            })

        # 4. 追加仅存在于 JSON 的供应商（source: \"pricing_json\"）
        json_only_ids = sorted(json_provider_models.keys() - db_provider_ids)
        for provider_id in json_only_ids:
            result.append({
                "id": provider_id,
                "name": provider_names.get(provider_id, provider_id.upper()),
                "display_name": provider_names.get(provider_id, provider_id.upper()),
                "icon": None,
                "api_endpoint": None,
                "has_api_key": False,
                "selected_models": sorted(json_provider_models.get(provider_id, set())),
                "configuration_count": 0,
                "source": "pricing_json",
            })

        return result

    def get_providers(self) -> List[str]:
        """
        获取所有已配置的供应商 ID 列表。
        
        Returns:
            供应商 ID 列表。
        """
        return [provider["id"] for provider in self.get_provider_catalog()]

    def create_pricing(self, pricing_data: Dict) -> ModelPricing:
        """
        创建新的价格配置记录。
        
        Args:
            pricing_data: 价格配置数据字典。
            
        Returns:
            新创建的价格配置对象。
        """
        pricing_data["provider"] = self.normalize_provider(pricing_data.get("provider"))
        pricing_data["model"] = self.normalize_model(pricing_data.get("model"))
        pricing = ModelPricing(**pricing_data)
        self.db.add(pricing)
        self.db.commit()
        self.db.refresh(pricing)
        return pricing

    PRICING_UPDATE_ALLOWED_FIELDS = {
        "provider", "model", "input_price", "output_price",
        "currency", "unit", "is_active", "description",
    }

    def update_pricing(self, pricing_id: int, pricing_data: Dict) -> Optional[ModelPricing]:
        """
        更新指定 ID 的价格配置。

        Args:
            pricing_id: 价格配置 ID。
            pricing_data: 更新数据字典。

        Returns:
            更新后的价格配置对象，若不存在则返回 None。
        """
        pricing = self.db.query(ModelPricing).filter(ModelPricing.id == pricing_id).first()
        if pricing:
            if "provider" in pricing_data:
                pricing_data["provider"] = self.normalize_provider(pricing_data.get("provider"))
            if "model" in pricing_data:
                pricing_data["model"] = self.normalize_model(pricing_data.get("model"))
            for key, value in pricing_data.items():
                if key not in self.PRICING_UPDATE_ALLOWED_FIELDS:
                    logger.warning(f"拒绝更新不允许的字段: {key}")
                    continue
                setattr(pricing, key, value)
            pricing.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(pricing)
        return pricing

    def delete_pricing(self, pricing_id: int) -> bool:
        """
        软删除指定 ID 的价格配置。
        
        Args:
            pricing_id: 价格配置 ID。
            
        Returns:
            删除成功返回 True，不存在返回 False。
        """
        pricing = self.db.query(ModelPricing).filter(ModelPricing.id == pricing_id).first()
        if pricing:
            pricing.is_active = False
            self.db.commit()
            return True
        return False

    def initialize_default_pricing(self) -> int:
        """
        初始化默认价格配置数据。
        确保 model_pricing 表包含新列，创建记录后从模型能力数据回填模态字段。

        Returns:
            新创建的记录数量。
        """
        # 确保新字段列存在
        self._ensure_model_pricing_schema()

        existing_keys = {
            (m.provider, m.model)
            for m in self.db.query(
                ModelPricing.provider, ModelPricing.model
            ).all()
        }
        count = 0
        for data in self._default_pricing_data:
            if (data["provider"], data["model"]) not in existing_keys:
                pricing = ModelPricing(**data)
                self.db.add(pricing)
                count += 1
        
        self.db.commit()

        # 为新创建的记录回填模态能力字段
        if count > 0:
            cap_dict = self._model_capability_defaults
            for data in self._default_pricing_data:
                key = (data["provider"], data["model"])
                if key in existing_keys:
                    continue
                cap = cap_dict.get(key)
                if cap:
                    self.db.query(ModelPricing).filter(
                        ModelPricing.provider == data["provider"],
                        ModelPricing.model == data["model"]
                    ).update({
                        "supports_vision": cap.get("supports_vision", False),
                        "is_multimodal": cap.get("is_multimodal", False),
                    })
            self.db.commit()

        return count

    def backfill_modality_fields(self) -> int:
        """
        为已有的 ModelPricing 记录批量补齐模态能力字段。
        遍历所有 supports_vision 为 NULL 的记录，从模型能力数据中查找并更新。

        Returns:
            更新的记录数量。
        """
        # 确保新字段列存在
        self._ensure_model_pricing_schema()

        # 查询 supports_vision 为 NULL 的记录（即旧记录，未设置模态字段）
        records = self.db.query(ModelPricing).filter(
            ModelPricing.supports_vision.is_(None)
        ).all()

        if not records:
            return 0

        cap_dict = self._model_capability_defaults
        updated_count = 0

        for record in records:
            key = (record.provider, record.model)
            cap = cap_dict.get(key)
            if cap:
                record.supports_vision = cap.get("supports_vision", False)
                record.is_multimodal = cap.get("is_multimodal", False)
            else:
                # 未找到匹配的能力数据，使用默认值 False
                record.supports_vision = False
                record.is_multimodal = False
            updated_count += 1

        if updated_count > 0:
            self.db.commit()

        return updated_count

    def initialize_default_configurations(self) -> int:
        """
        初始化默认模型配置数据。
        
        Returns:
            新创建的记录数量。
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
        for data in self._default_configurations:
            normalized = self._normalize_configuration_payload(data)
            config = ModelConfiguration(**normalized)
            self.db.add(config)
            count += 1

        self.db.commit()
        return count

    def remove_legacy_default_configurations(self) -> int:
        """
        移除旧版本的默认配置记录。
        
        Returns:
            删除的记录数量。
        """
        self.ensure_configuration_schema()

        conditions = [
            (ModelConfiguration.provider == provider) & (ModelConfiguration.model == model)
            for provider, model in self._legacy_configuration_keys
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
        校验价格数据的合法性。
        
        Args:
            data: 待校验的价格数据字典。
            
        Returns:
            元组，第一个元素表示是否合法，第二个元素为错误信息列表。
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
        获取所有激活的模型配置。
        
        Returns:
            模型配置对象列表。
        """
        self.ensure_configuration_schema()
        return self.db.query(ModelConfiguration).filter(
            ModelConfiguration.is_active == True
        ).order_by(ModelConfiguration.sort_order, ModelConfiguration.id).all()

    def get_configuration(self, config_id: int) -> Optional[ModelConfiguration]:
        """
        获取指定 ID 的模型配置。
        
        Args:
            config_id: 配置 ID。
            
        Returns:
            模型配置对象，若不存在则返回 None。
        """
        self.ensure_configuration_schema()
        return self.db.query(ModelConfiguration).filter(
            ModelConfiguration.id == config_id
        ).first()

    def get_default_configuration(self) -> Optional[ModelConfiguration]:
        """
        获取默认的模型配置。
        
        Returns:
            默认模型配置对象，若不存在则返回 None。
        """
        self.ensure_configuration_schema()
        return self.db.query(ModelConfiguration).filter(
            ModelConfiguration.is_active == True,
            ModelConfiguration.is_default == True
        ).first()

    def get_configuration_by_provider_model(self, provider: str, model: str) -> Optional[ModelConfiguration]:
        """
        根据供应商和模型名称获取配置。
        
        Args:
            provider: 供应商名称。
            model: 模型名称。
            
        Returns:
            模型配置对象，若不存在则返回 None。
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
        获取指定供应商的默认配置，若无默认配置则返回第一个激活配置。
        
        Args:
            provider: 供应商名称。
            
        Returns:
            模型配置对象，若不存在则返回 None。
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
        规范化配置数据字典，处理字段格式和空值。
        
        Args:
            config_data: 原始配置数据。
            
        Returns:
            规范化后的配置数据。
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
        if "max_tokens" in normalized:
            val = normalized.get("max_tokens")
            normalized["max_tokens"] = int(val) if val is not None else None

        return normalized

    def create_configuration(self, config_data: Dict) -> ModelConfiguration:
        """
        创建新的模型配置。
        
        Args:
            config_data: 配置数据字典。
            
        Returns:
            新创建的模型配置对象。
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

    CONFIG_UPDATE_ALLOWED_FIELDS = {
        "provider", "model", "api_base", "api_key", "description",
        "is_default", "is_active", "max_tokens", "temperature",
        "top_p", "frequency_penalty", "presence_penalty",
    }

    def update_configuration(self, config_id: int, config_data: Dict) -> Optional[ModelConfiguration]:
        """
        更新指定 ID 的模型配置。

        Args:
            config_id: 配置 ID。
            config_data: 更新数据字典。

        Returns:
            更新后的模型配置对象，若不存在则返回 None。
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
                if key != "id" and key in self.CONFIG_UPDATE_ALLOWED_FIELDS:
                    setattr(config, key, value)
                elif key != "id":
                    logger.warning(f"拒绝更新不允许的配置字段: {key}")
            config.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(config)

        return config

    def delete_configuration(self, config_id: int) -> bool:
        """
        软删除指定 ID 的模型配置。
        
        Args:
            config_id: 配置 ID。
            
        Returns:
            删除成功返回 True，不存在返回 False。
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
        删除指定供应商的所有配置。
        
        Args:
            provider: 供应商名称。
            
        Returns:
            删除的配置数量。
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
        设置指定配置为默认配置。
        
        Args:
            config_id: 配置 ID。
            
        Returns:
            更新后的模型配置对象，若不存在则返回 None。
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

    def get_model_defaults(self, provider: str, model: str) -> Dict:
        """
        获取指定模型的默认参数值。

        Args:
            provider: 供应商名称。
            model: 模型名称。

        Returns:
            默认参数字典，包含 temperature、top_k、max_tokens_limit。
        """
        key = (self.normalize_provider(provider), self.normalize_model(model))
        defaults = self._model_capability_defaults.get(key, {})
        spec = defaults.get("model_spec", {})
        max_output_tokens = None
        if isinstance(spec, dict):
            max_output_tokens = spec.get("max_output_tokens")
        elif isinstance(spec, str):
            try:
                import json
                parsed = json.loads(spec)
                max_output_tokens = parsed.get("max_output_tokens")
            except (TypeError, ValueError):
                pass
        return {
            "temperature": defaults.get("temperature", 0.7),
            "top_k": defaults.get("top_k", 0.9),
            "max_tokens_limit": max_output_tokens,
        }

    def batch_update_status(self, config_ids: List[int], status: str) -> int:
        """
        批量更新模型配置的 status 字段。

        Args:
            config_ids: 配置 ID 列表。
            status: 新的状态值。

        Returns:
            更新的记录数。
        """
        self.ensure_configuration_schema()
        if not config_ids:
            return 0

        now = datetime.now(timezone.utc)
        configs = self.db.query(ModelConfiguration).filter(
            ModelConfiguration.id.in_(config_ids)
        ).all()

        for config in configs:
            config.status = status
            config.updated_at = now

        self.db.commit()
        return len(configs)

    def initialize_model_defaults(self) -> int:
        """
        为已有的 ModelConfiguration 记录填充默认的能力参数。
        仅在字段为 NULL 时更新，不覆盖用户已自定义的值。

        Returns:
            更新的配置数量。
        """
        self.ensure_configuration_schema()
        configs = self.db.query(ModelConfiguration).all()
        updated_count = 0

        for config in configs:
            key = (self.normalize_provider(config.provider), self.normalize_model(config.model))
            defaults = self._model_capability_defaults.get(key)
            if not defaults:
                continue

            changed = False
            for field, value in defaults.items():
                current = getattr(config, field, None)
                if current is None:
                    setattr(config, field, value)
                    changed = True

            if changed:
                config.updated_at = datetime.now(timezone.utc)
                updated_count += 1

        if updated_count > 0:
            self.db.commit()

        return updated_count
