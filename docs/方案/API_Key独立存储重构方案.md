# API Key 独立存储重构方案

## 现状问题

`ModelConfiguration` 表同时承担两种职责，用 `model='custom-model'` 魔法值区分：

| 职责 | 存什么 | 问题 |
|------|--------|------|
| Provider 凭据 | `api_key`, `api_endpoint` | 藏在 `model='custom-model'` 记录里 |
| Model 配置 | `model`, `temperature`, `top_k` 等 | 创建时需从 gateway 继承 api_key |

**涉及范围**（`custom-model` 引用点）：

| 文件 | 用途 |
|------|------|
| `backend/billing/models.py:116-117` | `ModelConfiguration.api_key` / `api_endpoint` 列 |
| `backend/billing/pricing_manager.py:1150-1157` | `_get_gateway_config()` 查 `model='custom-model'` |
| `backend/billing/pricing_manager.py:1225-1235` | 凭据继承逻辑 |
| `backend/core/executor.py:791` | `custom-model` 占位符识别 |
| `frontend/SettingsPage.tsx:1219` | `handleCreateProvider` 硬编码 `'custom-model'` |
| `frontend/SettingsPage.tsx:2440` | 列表过滤 `custom-model` |
| `backend/tests/test_pricing_manager.py` | 测试依赖 `custom-model` |

---

## 目标架构

新增独立的 `ProviderCredential` 表，Provider 级凭据与 Model 级配置完全分离：

```
┌─────────────────────────┐     ┌─────────────────────────┐
│   ProviderCredential    │     │   ModelConfiguration    │
├─────────────────────────┤     ├─────────────────────────┤
│ id (PK)                 │     │ id (PK)                 │
│ provider (UNIQUE)       │◄────│ credential_id (FK)      │
│ display_name            │     │ provider                │
│ api_key (encrypted)     │     │ model                   │
│ api_endpoint            │     │ display_name            │
│ icon                    │     │ temperature / top_k ... │
│ is_active               │     │ is_active / is_default  │
│ created_at / updated_at │     │ ...                     │
└─────────────────────────┘     └─────────────────────────┘
```

**关键变更**：
- `ModelConfiguration.api_key` / `api_endpoint` → 移除，改为 `credential_id` FK
- 不再需要 `model='custom-model'` 这个 hack
- Provider API Key 管理独立于模型配置

---

## 实施步骤

### Phase 1：后端 — 新建 ProviderCredential

**1.1 新建模型**（`backend/billing/models.py`）

```python
class ProviderCredential(Base):
    __tablename__ = "provider_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=True)
    api_key: Mapped[str] = mapped_column(Text, nullable=True)     # Fernet 加密
    api_endpoint: Mapped[str] = mapped_column(String(500), nullable=True)
    icon: Mapped[str] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = ...
    updated_at: Mapped[datetime] = ...
```

**1.2 ModelConfiguration 新增 FK**

```python
credential_id: Mapped[int] = mapped_column(Integer, ForeignKey("provider_credentials.id"), nullable=True)
```

（暂时保留现有 `api_key`/`api_endpoint` 列作为过渡，Phase 3 移除）

**1.3 DB Migration**（`pricing_manager.py`）

```python
def ensure_credential_schema(self):
    # 1. CREATE TABLE provider_credentials
    # 2. ALTER TABLE model_configurations ADD COLUMN credential_id
    # 3. 数据迁移：custom-model 记录 → provider_credentials
    # 4. UPDATE model_configurations SET credential_id = ...
```

### Phase 2：后端 — 凭据解析重构

**2.1 新增 `PricingManager` 方法**

| 方法 | 说明 |
|------|------|
| `get_provider_credential(provider)` | 替代 `_get_gateway_config`，查新表 |
| `upsert_provider_credential(provider, data)` | 创建/更新凭据 |
| `resolve_api_credentials(provider)` | 统一入口：返回 `(api_key, api_endpoint)` |

**2.2 修改凭据继承**（`_normalize_configuration_payload`）

```python
# 旧：从 model='custom-model' 继承
gateway = self._get_gateway_config(provider)

# 新：从 ProviderCredential 表继承
credential = self.get_provider_credential(provider)
if credential:
    normalized["credential_id"] = credential.id
```

**2.3 修改 Executor**（`backend/core/executor.py`）

```python
# 旧逻辑
if normalized_model in {"custom-model", ...}:
    # 从 selected_models 选模型

# 新逻辑
# 不再需要！model 不会是 'custom-model'
# 直接查 ModelConfiguration + ProviderCredential
```

**2.4 修改 API 路由**（`backend/billing/routers/billing.py`）

- 新增 `POST /api/billing/credentials/{provider}` — 创建/更新 Provider 凭据
- 新增 `GET /api/billing/credentials/{provider}` — 获取 Provider 凭据（不含解密后的 api_key）
- `GET /api/billing/configurations` — 响应中 `api_key`/`api_endpoint` 改为从 `credential_id` 解析

**2.5 `serialize_configuration` 改造**

```python
def serialize_configuration(config, ...):
    credential = pricing_manager.get_provider_credential(config.provider) if config.credential_id else None
    return {
        ...
        "has_api_key": bool(credential and credential.api_key),
        "api_endpoint": credential.api_endpoint if credential else config.api_endpoint,
        ...
    }
```

### Phase 3：前端改造

**3.1 新增 API 模块**（`frontend/src/features/settings/modelsApi.ts`）

```typescript
// 新增
saveProviderCredential(provider: string, data: {
  api_key?: string; api_endpoint?: string; display_name?: string; icon?: string
}): Promise<...>

getProviderCredential(provider: string): Promise<ProviderCredential>
```

**3.2 修改 SettingsPage**

| 改动 | 说明 |
|------|------|
| `handleCreateProvider` | 调用 `saveProviderCredential` 替代 `createConfiguration({model:'custom-model'})` |
| `handleSaveProviderConfig` | 调用 `saveProviderCredential` 替代 `updateConfiguration(gatewayConfigId, ...)` |
| `handleImportModels` | 不再需要 API Key 继承逻辑（后端自动处理） |
| 模型列表过滤 | 移除 `.filter(c => c.model !== 'custom-model')` |
| Provider 面板 | 改用 credential API 读取/写入 API Key |

### Phase 4：数据迁移与清理

**4.1 自动迁移**（启动时）

```python
def migrate_to_credential_table(self):
    """一次性迁移：custom-model 配置 → provider_credentials"""
    gateways = self.db.query(ModelConfiguration).filter(
        ModelConfiguration.model == "custom-model"
    ).all()
    for gw in gateways:
        cred = ProviderCredential(
            provider=gw.provider,
            display_name=gw.display_name,
            api_key=gw.api_key,
            api_endpoint=gw.api_endpoint,
            icon=gw.icon,
        )
        self.db.add(cred)
        # 更新同 provider 的所有 model 配置指向新凭据
        ...
    # 标记 gateway 配置为 inactive
    ...
```

**4.2 清理**（稳定运行后）

- 移除 `ModelConfiguration.api_key` / `api_endpoint` 列
- 删除 `model='custom-model'` 的历史记录
- 移除 `_get_gateway_config` 方法
- 移除 executor 中 `custom-model` 占位符逻辑

### Phase 5：测试更新

| 文件 | 改动 |
|------|------|
| `test_pricing_manager.py` | `custom-model` → 使用 `ProviderCredential` fixture |
| `test_provider_endpoint_resolution.py` | 同上 |
| `SettingsPage.test.tsx` | `model:'custom-model'` → credential mock |

---

## 风险评估

| 风险 | 等级 | 应对 |
|------|------|------|
| 数据迁移丢失 API Key | 高 | 迁移前备份，两阶段迁移（先双写再清理） |
| Executor 无法解析凭据 | 高 | Phase 2 保留 `ModelConfiguration.api_key` 回退 |
| 前端兼容性 | 中 | API 响应保持 `has_api_key`/`api_endpoint` 字段不变 |
| 测试大量改动 | 低 | 逐个测试文件更新，Phase 5 最后执行 |

## 预估工作量

| Phase | 内容 | 文件数 | 估时 |
|-------|------|--------|------|
| 1 | 新建模型 + Migration | 2 | 1h |
| 2 | 后端凭据解析重构 | 3 | 2h |
| 3 | 前端改造 | 2 | 1.5h |
| 4 | 数据迁移脚本 | 1 | 0.5h |
| 5 | 测试更新 | 3 | 1h |
| **合计** | | **~10** | **~6h** |
