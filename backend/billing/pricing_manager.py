"""
计费与用量管理模块，负责价格配置、预算控制、用量追踪与报表能力。
这一部分直接关联成本核算、调用统计以及运维观测。
"""

from sqlalchemy import text, or_
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Set, Tuple
from billing.models import ModelPricing, ModelConfiguration, ProviderCredential
from datetime import datetime, timezone
from loguru import logger
from pathlib import Path
import json
from threading import RLock


class PricingManager:
    """
    计费管理器，负责模型价格配置、用量追踪与预算控制。
    提供模型定价的增删改查、供应商配置管理以及默认配置初始化等功能。
    """
    # 仅串行化运行期 schema 检查与迁移标记。请求级 Session 不是线程安全对象，
    # 普通查询和写入仍必须由各自请求持有的 Session 执行。
    _schema_lock = RLock()
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
        校验默认配置的唯一性。从 default_configurations.json 加载配置。

        Returns:
            元组，第一个元素表示是否唯一，第二个元素为重复项列表。

        Raises:
            Exception: 默认配置加载失败（显式传播，校验不能假装通过）。
        """
        from config.config_loader import config_loader
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
            logger.bind(module="pricing_manager", event="url_parse_error").debug(
                f"自定义端点 URL 解析失败: {raw}"
            )

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

    LEGACY_DEFAULT_CONFIGURATION_KEYS = [
        ("openai", "gpt-4"),
        ("openai", "gpt-4o"),
        ("openai", "gpt-4o-mini"),
        ("openai", "gpt-4.1"),
        ("anthropic", "claude-3-haiku"),
        ("anthropic", "claude-3.5-haiku"),
        ("anthropic", "claude-3.5-sonnet"),
        ("google", "gemini-2.0-flash"),
        ("google", "gemini-2.0-flash-lite"),
        ("google", "gemini-2.5-flash"),
        ("google", "gemini-2.5-pro"),
        ("deepseek", "deepseek-chat"),
        ("deepseek", "deepseek-reasoner"),
        ("deepseek", "deepseek-v3"),
        ("deepseek", "deepseek-r1"),
        ("deepseek", "deepseek-v3.1"),
        ("deepseek", "deepseek-v3.2"),
        ("alibaba", "qwen-turbo"),
        ("alibaba", "qwen-plus"),
        ("moonshot", "moonshot-v1-8k"),
        ("zhipu", "glm-4"),
        ("zhipu", "glm-4-plus"),
    ]

    def __init__(self, db: Session):
        """
        初始化计费管理器。

        Args:
            db: 数据库会话对象。
        """
        self.db = db
        self._pricing_schema_ensured = False
        self._config_schema_ensured = False
        self._credential_schema_ensured = False

    def ensure_pricing_schema(self) -> None:
        """
        标记模型定价 schema 已由 Alembic 管理。

        禁止在运行期执行 DDL；部署或升级前必须先执行 Alembic migration。
        """
        with self._schema_lock:
            if self._pricing_schema_ensured:
                return
            self._pricing_schema_ensured = True

    def ensure_credential_schema(self) -> None:
        """
        确保 provider_credentials 表存在，若不存在则创建。
        首次调用后设置标志，后续调用直接返回。
        """
        with self._schema_lock:
            if self._credential_schema_ensured:
                return
            tables = {
                row[0]
                for row in self.db.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
            }
            if "provider_credentials" not in tables:
                self.db.execute(text("""
                    CREATE TABLE provider_credentials (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        provider VARCHAR(50) UNIQUE NOT NULL,
                        display_name VARCHAR(200),
                        api_key TEXT,
                        api_endpoint VARCHAR(500),
                        icon VARCHAR(500),
                        is_active BOOLEAN DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            self.db.commit()
            self._credential_schema_ensured = True

    def ensure_configuration_schema(self) -> None:
        """
        确保模型配置表包含必要的字段，若缺失则动态添加。
        首次调用后设置标志，后续调用直接返回，避免重复 PRAGMA 查询。
        """
        with self._schema_lock:
            if self._config_schema_ensured:
                return
            # 确保 Provider 凭据表先于配置表存在
            self.ensure_credential_schema()

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
            if "input_modality" not in columns:
                self.db.execute(text("ALTER TABLE model_configurations ADD COLUMN input_modality TEXT"))
            if "output_modality" not in columns:
                self.db.execute(text("ALTER TABLE model_configurations ADD COLUMN output_modality TEXT"))
            if "credential_id" not in columns:
                self.db.execute(text("ALTER TABLE model_configurations ADD COLUMN credential_id INTEGER REFERENCES provider_credentials(id)"))

            self.db.commit()
            self._config_schema_ensured = True

    @staticmethod
    def _get_capability_defaults(key: Tuple[str, str]) -> Dict:
        """
        从 model_capabilities.json 加载指定 (provider, model) 的能力默认值。

        Args:
            key: (provider, model) 元组。

        Returns:
            能力默认值字典，该模型无条目时返回空字典。

        Raises:
            Exception: 能力配置文件加载失败（显式传播，禁止静默返回空字典）。
        """
        from config.config_loader import config_loader
        capabilities = config_loader.load_model_capabilities()
        return capabilities.get(key, {})

    def _normalize_pricing_payload(self, pricing_data: Dict) -> Dict:
        """
        规范化定价数据，并补齐能力标记与模态标签的默认值。
        """
        normalized = dict(pricing_data)
        normalized["provider"] = self.normalize_provider(normalized.get("provider"))
        normalized["model"] = self.normalize_model(normalized.get("model"))

        capability_defaults = self._get_capability_defaults(
            (normalized["provider"], normalized["model"])
        )
        normalized.setdefault(
            "supports_vision",
            capability_defaults.get("supports_vision", False)
        )
        normalized.setdefault(
            "is_multimodal",
            capability_defaults.get("is_multimodal", False)
        )
        # 补齐模态标签默认值
        supports_vision = normalized.get("supports_vision", False)
        is_multimodal = normalized.get("is_multimodal", False)

        def _ensure_modality_json(val, default_modalities):
            """确保模态值为 JSON 字符串；若传入 Python list 则自动序列化。"""
            if not val:
                return json.dumps(default_modalities)
            if isinstance(val, list):
                return json.dumps(val)
            # 已是字符串，尝试解析验证
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    return val
            except (TypeError, ValueError):
                pass
            return json.dumps(default_modalities)

        if "input_modality" not in normalized or not normalized["input_modality"]:
            if is_multimodal or supports_vision:
                normalized["input_modality"] = json.dumps(["text", "image"])
            else:
                normalized["input_modality"] = json.dumps(["text"])
        else:
            normalized["input_modality"] = _ensure_modality_json(
                normalized["input_modality"],
                ["text", "image"] if (is_multimodal or supports_vision) else ["text"]
            )

        if "output_modality" not in normalized or not normalized["output_modality"]:
            normalized["output_modality"] = json.dumps(["text"])
        else:
            normalized["output_modality"] = _ensure_modality_json(
                normalized["output_modality"], ["text"]
            )
        return normalized

    def get_pricing(self, provider: str, model: str) -> Optional[ModelPricing]:
        """
        获取指定供应商和模型的价格配置。
        
        Args:
            provider: 供应商名称。
            model: 模型名称。
            
        Returns:
            价格配置对象，若不存在则返回 None。
        """
        self.ensure_pricing_schema()
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
        self.ensure_pricing_schema()
        query = self.db.query(ModelPricing).filter(ModelPricing.is_active == True)
        normalized_provider = self.normalize_provider(provider)
        if normalized_provider:
            query = query.filter(ModelPricing.provider == normalized_provider)
        return query.order_by(ModelPricing.provider, ModelPricing.model).all()

    # 供应商预设 base_url 映射（与前端 PRESET_PROVIDER_BASE_URLS 保持一致）
    _PRESET_BASE_URLS: Dict[str, str] = {
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com/v1",
        "google": "https://generativelanguage.googleapis.com/v1beta",
        "deepseek": "https://api.deepseek.com/v1",
        "alibaba": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "moonshot": "https://api.moonshot.cn/v1",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4",
        "ollama": "http://127.0.0.1:11434/v1",
    }

    @staticmethod
    def _load_pricing_data_providers() -> Dict[str, Dict]:
        """
        从 pricing_data.json 中提取供应商信息，按 provider 分组。
        返回字典：{ provider_id: { name, base_url, models: [...] } }

        文件缺失或读取失败时显式传播异常（配置损坏必须可见，
        禁止静默返回空字典造成目录缺失的假象）。
        """
        pricing_file = Path(__file__).parent.parent / "config" / "pricing" / "pricing_data.json"
        if not pricing_file.exists():
            raise FileNotFoundError(f"定价目录文件缺失: {pricing_file}")
        with open(pricing_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError(f"pricing_data.json 顶层结构必须是列表，实际: {type(data).__name__}")

        provider_names = {
            "openai": "OpenAI",
            "anthropic": "Anthropic",
            "google": "Google",
            "deepseek": "DeepSeek",
            "alibaba": "阿里通义千问",
            "moonshot": "Kimi",
            "zhipu": "智谱AI",
            "ollama": "Ollama",
        }

        grouped: Dict[str, Dict] = {}
        for entry in data:
            if not isinstance(entry, dict):
                continue
            provider = PricingManager.normalize_provider(entry.get("provider"))
            if not provider:
                continue
            if provider not in grouped:
                grouped[provider] = {
                    "name": provider_names.get(provider, provider.upper()),
                    "base_url": PricingManager._PRESET_BASE_URLS.get(provider, ""),
                    "models": [],
                }
            model_name = PricingManager.normalize_model(entry.get("model"))
            if model_name:
                grouped[provider]["models"].append({
                    "name": model_name,
                    "input_price": entry.get("input_price", 0),
                    "output_price": entry.get("output_price", 0),
                    "currency": entry.get("currency", "USD"),
                    "context_window": entry.get("context_window"),
                })

        return grouped

    def get_provider_catalog(self, include_pricing_data: bool = False, configured_only: bool = False) -> List[Dict]:
        """
        获取供应商目录，包含每个供应商的配置信息和已选模型列表。
        同时涵盖 ModelConfiguration 和 ProviderCredential 中的 provider。

        当 include_pricing_data=True 时，还会从 pricing_data.json 中提取
        未在数据库中配置的供应商，合并到返回结果中。
        数据库中的供应商优先级更高（source="database"），
        pricing_data 中的供应商标记为 source="pricing_data"。

        当 configured_only=True 时，仅返回拥有 ProviderCredential 的供应商，
        忽略仅有 ModelConfiguration 但未被用户显式添加的供应商（如默认模板）。

        优化：批量加载 credential 和 configuration，避免循环内对每个 provider
        逐一查询数据库（N+1 → 3 次查询）。
        """
        # 1. 从 ProviderCredential 获取已配置的 provider 列表
        cred_rows = self.db.query(ProviderCredential.provider).filter(
            ProviderCredential.is_active == True
        ).distinct().all()
        cred_provider_ids = {
            self.normalize_provider(row[0])
            for row in cred_rows
            if self.normalize_provider(row[0])
        }

        # 2. 从 ModelConfiguration 获取 provider 列表
        config_rows = self.db.query(ModelConfiguration.provider).filter(
            ModelConfiguration.is_active == True
        ).distinct().all()
        config_provider_ids = {
            self.normalize_provider(row[0])
            for row in config_rows
            if self.normalize_provider(row[0])
        }

        if configured_only:
            # 仅返回用户已显式添加的供应商（有 ProviderCredential 记录）
            db_provider_ids = sorted(cred_provider_ids)
        else:
            # 合并两个来源的供应商
            db_provider_ids = sorted(cred_provider_ids | config_provider_ids)

        provider_names = {
            "openai": "OpenAI",
            "anthropic": "Anthropic",
            "google": "Google",
            "deepseek": "DeepSeek",
            "alibaba": "阿里通义千问",
            "moonshot": "Kimi",
            "zhipu": "智谱AI",
            "ollama": "Ollama",
        }

        # 3. 批量加载所有 provider 的 credential 和 configuration，消除循环内 N+1 查询
        # 性能优化：pricing_data 一次性加载复用，避免在循环内重复读取 JSON 文件（原 N+1 磁盘 I/O）
        result = []
        pricing_providers_cache: Dict[str, Dict] = {}
        if include_pricing_data:
            pricing_providers_cache = self._load_pricing_data_providers()

        if db_provider_ids:
            all_creds = self.db.query(ProviderCredential).filter(
                ProviderCredential.provider.in_(db_provider_ids),
                ProviderCredential.is_active == True
            ).all()
            cred_map: Dict[str, ProviderCredential] = {
                self.normalize_provider(c.provider): c for c in all_creds
            }

            all_configs = self.db.query(ModelConfiguration).filter(
                ModelConfiguration.provider.in_(db_provider_ids),
                ModelConfiguration.is_active == True
            ).all()
            configs_by_provider: Dict[str, List[ModelConfiguration]] = {}
            default_config_map: Dict[str, ModelConfiguration] = {}
            for c in all_configs:
                pid = self.normalize_provider(c.provider)
                configs_by_provider.setdefault(pid, []).append(c)
            for pid, configs in configs_by_provider.items():
                # 优先取 is_default=True，否则取 sort_order 最小的第一个
                default = next((c for c in configs if c.is_default), None)
                if default is None and configs:
                    configs.sort(key=lambda c: (c.sort_order or 0, c.id or 0))
                    default = configs[0]
                default_config_map[pid] = default

            for provider_id in db_provider_ids:
                cred = cred_map.get(provider_id)
                config = default_config_map.get(provider_id)
                configs = configs_by_provider.get(provider_id, [])

                # selected_models 从 ModelConfiguration 聚合
                all_models = []
                for c in configs:
                    all_models.extend(self.parse_selected_models(c.selected_models))
                # 去重
                seen = set()
                selected_models = []
                for m in all_models:
                    if m not in seen:
                        seen.add(m)
                        selected_models.append(m)

                entry = {
                    "id": provider_id,
                    "name": provider_names.get(provider_id, provider_id.upper()),
                    "display_name": cred.display_name if cred else (config.display_name if config else provider_names.get(provider_id, provider_id.upper())),
                    "icon": cred.icon if cred else (config.icon if config else None),
                    "api_endpoint": cred.api_endpoint if cred else (config.api_endpoint if config else None),
                    "base_url": cred.api_endpoint if cred else (config.api_endpoint if config else None),
                    "has_api_key": bool(cred and cred.api_key),  # 仅检查 ProviderCredential
                    "selected_models": selected_models,
                    "configuration_count": len(configs),
                    "source": "database",
                }

                # 合并 pricing_data 中的模型列表（补充信息）
                if include_pricing_data:
                    pd_entry = pricing_providers_cache.get(provider_id)
                    if pd_entry:
                        entry["models"] = pd_entry["models"]
                        entry["model_count"] = len(pd_entry["models"])
                        # 若数据库中没有 base_url，使用预设值
                        if not entry.get("base_url") and pd_entry.get("base_url"):
                            entry["base_url"] = pd_entry["base_url"]
                    else:
                        entry["models"] = []
                        entry["model_count"] = 0

                result.append(entry)

        # 4. 合并 pricing_data.json 中未在数据库中配置的供应商
        if include_pricing_data:
            db_provider_set = set(db_provider_ids)
            for provider_id, pd_entry in pricing_providers_cache.items():
                if provider_id in db_provider_set:
                    continue  # 数据库已有，跳过
                result.append({
                    "id": provider_id,
                    "name": pd_entry["name"],
                    "display_name": pd_entry["name"],
                    "icon": None,
                    "api_endpoint": pd_entry.get("base_url") or None,
                    "base_url": pd_entry.get("base_url") or None,
                    "has_api_key": False,
                    "selected_models": [],
                    "configuration_count": 0,
                    "models": pd_entry["models"],
                    "model_count": len(pd_entry["models"]),
                    "source": "pricing_data",
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
        self.ensure_pricing_schema()
        normalized = self._normalize_pricing_payload(pricing_data)
        pricing = ModelPricing(**normalized)
        self.db.add(pricing)
        self.db.commit()
        self.db.refresh(pricing)
        return pricing

    def update_pricing(self, pricing_id: int, pricing_data: Dict) -> Optional[ModelPricing]:
        """
        更新指定 ID 的价格配置。
        
        Args:
            pricing_id: 价格配置 ID。
            pricing_data: 更新数据字典。
            
        Returns:
            更新后的价格配置对象，若不存在则返回 None。
        """
        self.ensure_pricing_schema()
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
        软删除指定 ID 的价格配置。
        
        Args:
            pricing_id: 价格配置 ID。
            
        Returns:
            删除成功返回 True，不存在返回 False。
        """
        self.ensure_pricing_schema()
        pricing = self.db.query(ModelPricing).filter(ModelPricing.id == pricing_id).first()
        if pricing:
            pricing.is_active = False
            self.db.commit()
            return True
        return False

    def initialize_default_pricing(self) -> int:
        """
        初始化默认价格配置数据。从 pricing_data.json 加载。

        Returns:
            新创建的记录数量。
        """
        self.ensure_pricing_schema()
        from config.config_loader import config_loader
        pricing_data_list = config_loader.load_pricing_data()

        existing_keys = {
            (self.normalize_provider(m.provider), self.normalize_model(m.model))
            for m in self.db.query(
                ModelPricing.provider, ModelPricing.model
            ).all()
        }
        count = 0
        for data in pricing_data_list:
            normalized = self._normalize_pricing_payload(data)
            if (normalized["provider"], normalized["model"]) not in existing_keys:
                pricing = ModelPricing(**normalized)
                self.db.add(pricing)
                count += 1

        self.db.commit()
        return count

    def initialize_default_configurations(self, add_missing: bool = False) -> int:
        """
        初始化默认模型配置数据。从 default_configurations.json 加载。

        Returns:
            新创建的记录数量。

        Args:
            add_missing: 已存在配置时是否补齐缺失的内置默认项。
        """
        self.ensure_configuration_schema()

        existing_count = self.db.query(ModelConfiguration).count()
        if existing_count > 0 and not add_missing:
            return 0

        # 从 config_loader 加载 JSON 配置（支持测试 mock）
        from config.config_loader import config_loader
        configurations = config_loader.load_default_configurations()

        if not configurations:
            return 0

        is_unique, duplicates = self._validate_configurations_uniqueness(configurations)
        if not is_unique:
            duplicate_text = ", ".join(f"{provider}/{model}" for provider, model in duplicates)
            raise ValueError(f"Duplicate default configurations found: {duplicate_text}")

        existing_keys = {
            (config.provider, config.model)
            for config in self.db.query(ModelConfiguration.provider, ModelConfiguration.model).all()
        }
        has_default = self.db.query(ModelConfiguration).filter(
            ModelConfiguration.is_default == True
        ).first() is not None

        count = 0
        for data in configurations:
            normalized = self._normalize_configuration_payload(data)
            if (normalized["provider"], normalized["model"]) in existing_keys:
                continue
            if normalized.get("is_default", False) and has_default:
                normalized["is_default"] = False
            config = ModelConfiguration(**normalized)
            self.db.add(config)
            has_default = has_default or config.is_default
            count += 1

        if count:
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
            for provider, model in self.LEGACY_DEFAULT_CONFIGURATION_KEYS
        ]

        if not conditions:
            return 0

        candidates = self.db.query(ModelConfiguration).filter(
            or_(*conditions),
            ModelConfiguration.api_key.is_(None),
            ModelConfiguration.api_endpoint.is_(None),
            ModelConfiguration.credential_id.is_(None),
        ).all()
        rows = [
            row for row in candidates
            if not self.parse_selected_models(row.selected_models)
        ]

        count = len(rows)
        if count == 0:
            return 0

        for row in rows:
            self.db.delete(row)

        self.db.commit()
        return count

    def refresh_legacy_default_model_selections(self) -> int:
        """将旧内置模型的首选项迁移为当前厂商模板，保留其余用户选择。"""
        self.ensure_configuration_schema()

        from config.config_loader import config_loader
        configurations = config_loader.load_default_configurations()

        current_defaults = {
            self.normalize_provider(item.get("provider")): self.normalize_model(item.get("model"))
            for item in configurations
            if item.get("is_active", True) and item.get("provider") and item.get("model")
        }
        legacy_keys = set(self.LEGACY_DEFAULT_CONFIGURATION_KEYS)
        updated_count = 0

        for config in self.db.query(ModelConfiguration).filter(
            ModelConfiguration.is_active == True
        ).all():
            provider = self.normalize_provider(config.provider)
            current_model = current_defaults.get(provider)
            selected_models = self.parse_selected_models(config.selected_models)
            if not current_model or not selected_models or selected_models[0] == current_model:
                continue

            first_model = self.normalize_model(selected_models[0])
            if (provider, first_model) not in legacy_keys:
                continue

            config.selected_models = self.serialize_selected_models(
                [current_model, *selected_models]
            )
            updated_count += 1

        if updated_count:
            self.db.commit()
        return updated_count

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

        # cherry-studio 兼容字段：缓存读写、按图/按分钟计费单价，均必须为非负数
        for price_field in (
            "cache_read_price", "cache_write_price",
            "per_image_price", "per_minute_price",
        ):
            if price_field in data and data[price_field] is not None:
                if not isinstance(data[price_field], (int, float)) or data[price_field] < 0:
                    errors.append(f"{price_field} must be a non-negative number")

        # max_output_tokens 必须为非负整数
        if "max_output_tokens" in data and data["max_output_tokens"] is not None:
            if not isinstance(data["max_output_tokens"], int) or data["max_output_tokens"] < 0:
                errors.append("max_output_tokens must be a non-negative integer")

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

    # ── Provider 凭据管理 ──────────────────────────────────────────

    def get_provider_credential(self, provider: str) -> Optional[ProviderCredential]:
        """
        获取指定 Provider 的凭据（API Key、Endpoint 等）。
        """
        self.ensure_configuration_schema()
        provider = self.normalize_provider(provider)
        return self.db.query(ProviderCredential).filter(
            ProviderCredential.provider == provider,
            ProviderCredential.is_active == True
        ).first()

    def upsert_provider_credential(self, provider: str, data: Dict) -> ProviderCredential:
        """
        创建或更新 Provider 凭据。
        同时确保该 provider 有活跃的默认 ModelConfiguration，
        防止用户删除 provider 后重新添加凭据时没有可用模型。
        """
        from config.security import encrypt_secret_value
        self.ensure_configuration_schema()
        provider = self.normalize_provider(provider)

        cred = self.get_provider_credential(provider) or self.db.query(ProviderCredential).filter(
            ProviderCredential.provider == provider
        ).first()
        if cred:
            for key in ("display_name", "icon", "api_endpoint"):
                if key in data and data[key] is not None:
                    setattr(cred, key, data[key])
            if "api_key" in data and data["api_key"] is not None:
                raw = data["api_key"].strip()
                cred.api_key = encrypt_secret_value(raw) if raw else None
            cred.is_active = True
            cred.updated_at = datetime.now(timezone.utc)
        else:
            raw_key = (data.get("api_key") or "").strip()
            cred = ProviderCredential(
                provider=provider,
                display_name=data.get("display_name"),
                api_key=encrypt_secret_value(raw_key) if raw_key else None,
                api_endpoint=data.get("api_endpoint"),
                icon=data.get("icon"),
            )
            self.db.add(cred)

        self.db.commit()
        self.db.refresh(cred)

        # 更新所有该 provider 的 ModelConfiguration 的 credential_id 关联
        # 确保序列化时能正确读取 has_api_key 状态
        self.db.query(ModelConfiguration).filter(
            ModelConfiguration.provider == provider,
        ).update({
            ModelConfiguration.credential_id: cred.id
        }, synchronize_session='fetch')
        self.db.commit()

        # 确保存在活跃的 ModelConfiguration（被 delete 后自动恢复）
        active_config = self.db.query(ModelConfiguration).filter(
            ModelConfiguration.provider == provider,
            ModelConfiguration.is_active == True,
        ).first()
        if not active_config:
            default_models = self._get_default_models_for_provider(provider)
            all_model_names = [m["model"] for m in default_models]
            for model_entry in default_models:
                # 检查该模型是否已存在（无论 is_active 状态）
                existing_mc = self.db.query(ModelConfiguration).filter(
                    ModelConfiguration.provider == provider,
                    ModelConfiguration.model == model_entry["model"],
                ).first()
                if existing_mc:
                    # 已存在则重新激活
                    existing_mc.is_active = True
                    existing_mc.credential_id = cred.id if cred else None
                else:
                    mc = ModelConfiguration(
                        provider=provider,
                        model=model_entry["model"],
                        display_name=model_entry.get("display_name", model_entry["model"]),
                        is_active=True,
                        is_default=model_entry.get("is_default", False),
                        selected_models=json.dumps(all_model_names),
                        credential_id=cred.id if cred else None,
                    )
                    self.db.add(mc)
            if default_models:
                self.db.commit()
                logger.info(f"已为 {provider} 恢复默认模型配置 ({len(default_models)} 个模型)")

        return cred

    @staticmethod
    def _get_default_models_for_provider(provider: str) -> list:
        """从默认配置目录读取指定厂商的恢复模型，避免维护第二份过期清单。"""
        from config.config_loader import config_loader
        configurations = config_loader.load_default_configurations()

        provider_defaults = [
            {
                "model": item["model"],
                "display_name": item.get("display_name", item["model"]),
                "is_default": item.get("is_default", False),
            }
            for item in configurations
            if item.get("provider") == provider and item.get("is_active", True)
        ]
        if provider_defaults:
            return provider_defaults
        return [{"model": f"{provider}-default", "display_name": provider, "is_default": True}]

    def get_all_provider_credentials(self) -> List[ProviderCredential]:
        """获取所有激活的 Provider 凭据。"""
        self.ensure_configuration_schema()
        return self.db.query(ProviderCredential).filter(
            ProviderCredential.is_active == True
        ).order_by(ProviderCredential.provider).all()

    # ── Provider 配置查询 ──────────────────────────────────────────

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
            raw_key = normalized["api_key"].strip()
            if raw_key:
                # 加密存储 API 密钥，防止明文泄露
                from config.security import encrypt_secret_value
                normalized["api_key"] = encrypt_secret_value(raw_key)
            else:
                normalized["api_key"] = None
        if "selected_models" in normalized:
            normalized["selected_models"] = self.serialize_selected_models(normalized.get("selected_models"))
        if "max_tokens" in normalized:
            val = normalized.get("max_tokens")
            normalized["max_tokens"] = int(val) if val is not None else None

        # 自动关联 ProviderCredential：若该 provider 已有凭据记录，设置 credential_id
        if "credential_id" not in normalized or normalized.get("credential_id") is None:
            provider = normalized.get("provider", "")
            if provider:
                cred = self.get_provider_credential(provider)
                if cred:
                    normalized["credential_id"] = cred.id

        return normalized

    def create_configuration(self, config_data: Dict) -> ModelConfiguration:
        """
        创建新的模型配置。若存在软删除记录则复用，若存在活跃重复记录则抛出 ValueError。
        
        Args:
            config_data: 配置数据字典。
            
        Returns:
            新创建（或复用）的模型配置对象。
        """
        self.ensure_configuration_schema()
        normalized = self._normalize_configuration_payload(config_data)

        provider = normalized.get("provider") or ""
        model = normalized.get("model") or ""

        existing = self.db.query(ModelConfiguration).filter(
            ModelConfiguration.provider == provider,
            ModelConfiguration.model == model,
        ).first()

        if existing:
            if existing.is_active:
                raise ValueError(
                    f"Configuration for {provider}/{model} already exists and is active"
                )
            # 复用软删除记录
            for key, value in normalized.items():
                if key != "id":
                    setattr(existing, key, value)
            existing.is_active = True
            existing.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(existing)
            return existing

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
                if key != "id":
                    setattr(config, key, value)
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
        硬删除指定供应商的所有配置和凭据。

        物理删除 ModelConfiguration 和 ProviderCredential 行（含已软删除的历史记录），
        确保密钥密文从数据库中彻底清除，避免凭据残留导致安全风险。

        Args:
            provider: 供应商名称。

        Returns:
            删除的配置数量。
        """
        self.ensure_configuration_schema()
        provider_id = self.normalize_provider(provider)
        if not provider_id:
            return 0

        # 统计待删除的配置数量（含已软删除的历史记录）
        configs_count = self.db.query(ModelConfiguration).filter(
            ModelConfiguration.provider == provider_id
        ).count()

        # 物理删除所有模型配置（含 is_active=True/False 的全部记录）
        self.db.query(ModelConfiguration).filter(
            ModelConfiguration.provider == provider_id
        ).delete(synchronize_session=False)

        # 物理删除凭据（含 is_active=True/False 的全部记录），彻底清除密钥密文
        self.db.query(ProviderCredential).filter(
            ProviderCredential.provider == provider_id
        ).delete(synchronize_session=False)

        self.db.commit()
        return configs_count

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
        获取指定模型的默认参数值。从 model_capabilities.json 加载。

        Args:
            provider: 供应商名称。
            model: 模型名称。

        Returns:
            默认参数字典。
        """
        key = (self.normalize_provider(provider), self.normalize_model(model))
        defaults = self._get_capability_defaults(key)
        return {
            "temperature": defaults.get("temperature", 0.7),
            "top_k": defaults.get("top_k", 0.9),
            "frequency_penalty": defaults.get("frequency_penalty", 0.0),
            "presence_penalty": defaults.get("presence_penalty", 0.0),
            "timeout": defaults.get("timeout", 120),
            "retry_count": defaults.get("retry_count", 3),
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
        从 model_capabilities.json 加载默认值。

        Returns:
            更新的配置数量。
        """
        self.ensure_configuration_schema()

        from config.config_loader import config_loader
        capability_defaults_map = config_loader.load_model_capabilities()

        configs = self.db.query(ModelConfiguration).all()
        updated_count = 0

        for config in configs:
            key = (self.normalize_provider(config.provider), self.normalize_model(config.model))
            defaults = capability_defaults_map.get(key)
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

    def reload_from_json(self) -> None:
        """
        清空内存缓存并重新从 JSON 加载。

        供 catalog_sync 同步完成后热加载使用。
        会清空 config_loader 的文件缓存、重置 schema 确保标志，
        然后重新调用 initialize 方法把 JSON 中新增的条目 upsert 到数据库。
        """
        # 清空 config_loader 的缓存，确保下次读取从磁盘加载
        from config.config_loader import config_loader
        config_loader.invalidate_cache()

        # 重置 schema 确保标志，确保下次操作时重新检查 schema
        self._pricing_schema_ensured = False
        self._config_schema_ensured = False
        self._credential_schema_ensured = False

        # 重新初始化默认数据（已存在的条目会被跳过，新增的会被插入）
        self.initialize_default_pricing()
        self.initialize_default_configurations()

        logger.bind(module="pricing_manager", event="reload_from_json").info(
            "已从 JSON 重新加载定价与配置数据"
        )
