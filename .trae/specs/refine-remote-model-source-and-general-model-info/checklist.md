# Checklist

## 模型列表获取
- [x] 通用设置页初始化时不会自动发起远端模型列表请求
- [x] 通用设置中的模型选项不再来自本地计费配置拼装结果
- [x] 通用设置中的模型选项仅展示供应商远端返回的模型
- [x] 同一供应商重复进入或切换时可复用缓存，避免重复请求
- [x] 供应商配置变更后，相关远端模型缓存会失效并重新拉取

## 通用设置参数区
- [x] AI 参数配置区中的“最大 Tokens”输入 `div` 已删除
- [x] 选择模型后，页面会联动显示该模型在计费配置中的最大 Tokens 信息
- [x] 温度、Top K / Top P 等现有参数交互不因本次改动失效

## 模型详情展示
- [x] 在原“最大 Tokens”区域下方展示所选模型的完整模型信息
- [x] 展示内容来自计费配置里的模型级字段与能力字段，而不是供应商级信息
- [x] 当远端模型缺少本地计费配置映射时，页面有明确空态或提示

## 验证
- [x] 相关前端测试覆盖惰性加载、远端来源、缓存、模型详情联动等关键路径
- [x] 前端类型检查通过
- [x] 通用设置与 API 配置之间的模型联动流程人工验证通过

## 运行结果

- RTL：`npm run test -- src/__tests__/features/settings/SettingsPage.test.tsx src/__tests__/features/settings/modelsApi.test.ts` 通过，`2` 个测试文件、`5` 个测试用例全部通过
- TypeScript：`npm run typecheck` 通过
- 测试覆盖：`SettingsPage.test.tsx` 明确断言“初始化不请求远端模型”“仅保留远端结果并忽略本地回退”“重新读取命中缓存不重复请求”“模型详情展示当前最大 Tokens、上下文窗口、价格与能力字段”
- 缓存失效：`SettingsPage.tsx` 的缓存签名包含 `provider.id`、`base_url/api_endpoint`、`has_api_key`、`configuration_count`，且在 API 配置创建、保存、导入模型、批量删除模型、删除供应商、重新获取模型时均调用 `invalidateRemoteModelCache()`
- 人工核验：通用设置中的远端模型读取入口仅暴露为“加载远端模型/重新读取”按钮；API 配置变更后会先失效缓存再重新进入读取流程，联动路径与 spec 一致
