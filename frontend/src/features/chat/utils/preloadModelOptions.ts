/**
 * 启动期模型选项预加载工具。
 *
 * 复用 GeneralTabContainer.loadGlobalModelOptions 的核心逻辑，
 * 在认证成功后立即拉取供应商列表与每个供应商的远端模型，
 * 写入 modelStore.modelOptions，并确保 selectedModel 在进入聊天页前已就位。
 *
 * 设计意图：
 * - 首次登录用户（无 localStorage 缓存）进入 /chat 时，selectedModel 不再为空，
 *   parseSelectedModel 能正常解析出 { provider, model }，避免发送消息时报错。
 * - 加载失败不阻塞登录流程，但必须显式暴露到 modelStore.modelError（设置页/聊天页可见），
 *   不静默降级、不隐藏错误。
 */
import { modelsAPI, type ModelConfiguration, type ModelProvider } from '@/features/settings/modelsApi'
import { useModelStore, type ModelOption } from '@/features/chat/store/modelStore'
import { appLogger } from '@/shared/utils/logger'

/** 远端模型选项条目（与 ModelOption 等价，显式列出字段以避免类型推断为 any） */
interface RemoteModelOption {
  id: string
  provider: string
  model: string
  display_name: string
}

/**
 * 构建供应商缓存签名，用于检测供应商配置变化（base_url / api_key 状态等）。
 * 与 GeneralTabContainer.buildProviderCacheSignature 保持一致，
 * 便于后续如果引入跨模块共享缓存时复用同一签名规则。
 */
function buildProviderCacheSignature(provider: ModelProvider): string {
  return [
    provider.id,
    provider.base_url || provider.api_endpoint || '',
    provider.has_api_key ? 'with-key' : 'without-key',
    String(provider.configuration_count || 0),
  ].join('|')
}

/**
 * 根据供应商信息和远端模型列表，构建 ModelOption 列表。
 * 与 GeneralTabContainer.buildRemoteModelOptions 保持一致：
 * - display_name 形如 "供应商显示名 - 模型名"
 * - id 形如 "providerId:modelName"，用于 setSelectedModel 与持久化
 */
function buildRemoteModelOptions(
  provider: ModelProvider,
  remoteModels: Array<{ model: string }>
): RemoteModelOption[] {
  const displayProvider = provider.display_name || provider.name || provider.id
  const uniqueModels = Array.from(
    new Set(remoteModels.map((item) => item.model).filter(Boolean))
  )
  return uniqueModels.map((modelName) => ({
    id: `${provider.id}:${modelName}`,
    provider: provider.id,
    model: modelName,
    display_name: `${displayProvider} - ${modelName}`,
  }))
}

/**
 * 启动期预加载模型选项。
 *
 * 流程：
 * 1. 并行拉取 configurations（用于回退默认模型）与 providers 列表
 * 2. 过滤出有效供应商（已配置凭据且 configuration_count > 0）
 * 3. 并行拉取每个供应商的远端模型，过滤掉 source !== 'remote' 的本地回退结果
 * 4. 合并、去重、排序后写入 modelStore.modelOptions
 * 5. 若 selectedModel 为空或在新列表中失效，自动选中：
 *    - 优先后端标记为 is_default 的 configuration
 *    - 否则回退到第一个可用模型
 *
 * 任意步骤失败均不抛出（不阻塞登录），但失败显式暴露到 modelStore.modelError 并记录日志。
 */
export async function preloadModelOptions(): Promise<void> {
  const modelStore = useModelStore.getState()
  modelStore.setModelLoading(true)
  modelStore.setModelError(null)

  try {
    const [configsRes, providersRes] = await Promise.all([
      modelsAPI.getConfigurations(),
      modelsAPI.getProviders(),
    ])
    const configurations: ModelConfiguration[] = configsRes.data.configurations || []
    const providersList: ModelProvider[] = providersRes.data.providers || []
    const validProviders = providersList.filter(
      (provider) => (provider.configuration_count || 0) > 0 && provider.has_api_key === true
    )

    if (validProviders.length === 0) {
      modelStore.setModelOptions([])
      return
    }

    const providerResults = await Promise.all(
      validProviders.map(async (provider) => {
        try {
          const providerModelsResponse = await modelsAPI.getModelsByProvider(provider.id)
          const providerModelsData = providerModelsResponse.data

          // source !== 'remote' 表示后端无法访问该供应商：显式记录警告（此前静默跳过，用户误以为无模型可选）
          if (providerModelsData.source !== 'remote') {
            appLogger.warning({
              event: 'preload_model_provider_unreachable',
              module: 'preloadModelOptions',
              message: 'provider model list not from remote source, skip',
              extra: {
                provider: provider.id,
                signature: buildProviderCacheSignature(provider),
                source: providerModelsData.source,
              },
            })
            return { provider, options: [] as RemoteModelOption[] }
          }

          const options = buildRemoteModelOptions(provider, providerModelsData.models || [])
          return { provider, options }
        } catch (err) {
          appLogger.warning({
            event: 'preload_model_provider_failed',
            module: 'preloadModelOptions',
            message: 'failed to load models for provider',
            extra: {
              provider: provider.id,
              signature: buildProviderCacheSignature(provider),
              error: err instanceof Error ? err.message : String(err),
            },
          })
          return { provider, options: [] as RemoteModelOption[] }
        }
      })
    )

    const nextOptions: ModelOption[] = providerResults
      .flatMap((result) => result.options)
      .sort((left, right) => left.display_name.localeCompare(right.display_name, 'zh-CN'))

    // setModelOptions 内部会校验 selectedModel 是否仍在新列表中，失效时清空
    modelStore.setModelOptions(nextOptions)

    // 重新读取 store 状态（setModelOptions 可能已清空失效的 selectedModel）
    const currentModel = useModelStore.getState().selectedModel
    const isCurrentModelValid =
      !!currentModel && nextOptions.some((opt) => opt.id === currentModel)

    if (!isCurrentModelValid) {
      if (configurations.length > 0) {
        // 优先使用后端标记为 is_default 的配置
        const defaultConfig = configurations.find((config) => config.is_default) || configurations[0]
        const defaultModelName = defaultConfig.selected_models?.[0] || defaultConfig.model
        const defaultModelId = `${defaultConfig.provider}:${defaultModelName}`
        // setSelectedModel 默认 syncToServer=true，会同步到 /user/preferences
        modelStore.setSelectedModel(defaultModelId)
      } else if (nextOptions.length > 0) {
        // 回退到第一个可用模型
        modelStore.setSelectedModel(nextOptions[0].id)
      }
    }
  } catch (err) {
    appLogger.error({
      event: 'preload_model_options_failed',
      module: 'preloadModelOptions',
      message: 'failed to preload model options during app initialization',
      extra: { error: err instanceof Error ? err.message : String(err) },
    })
    // 失败显式暴露到 modelStore.modelError：设置页/聊天页可见"模型列表加载失败"，不静默回退
    modelStore.setModelError('模型列表预加载失败，请稍后重试')
    // 不抛出，确保登录流程不被阻断（错误已通过 store 状态暴露）
  } finally {
    modelStore.setModelLoading(false)
  }
}
