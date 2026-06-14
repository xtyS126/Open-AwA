/**
 * API 配置 Tab 容器组件
 * 管理 API 配置相关的所有状态和数据获取逻辑
 *
 * 将供应商表单逻辑提取到 useProviderForm Hook，
 * 将模型配置逻辑提取到 useModelConfig Hook，
 * 本组件负责组合两者并渲染 UI。
 */
import { lazy, Suspense, useCallback } from 'react'
import { useSharedSettingsData } from '@/features/settings/hooks/useSharedSettingsData'
import { useProviderForm, type ApiProviderFormState } from '@/features/settings/containers/ProviderFormContainer'
import { useModelConfig } from '@/features/settings/containers/ModelConfigContainer'
import { modelsAPI } from '@/features/settings/modelsApi'
import type { ConnectivityTestResult } from '@/features/settings/modelsApi'

// 懒加载组件，减少首屏 bundle 体积
const ApiSettings = lazy(() => import('@/features/settings/components/ApiSettings').then(m => ({ default: m.ApiSettings })))
const CreateProviderModal = lazy(() => import('@/features/settings/modals/CreateProviderModal').then(m => ({ default: m.CreateProviderModal })))
const DeleteConfirmModal = lazy(() => import('@/features/settings/modals/DeleteConfirmModal').then(m => ({ default: m.DeleteConfirmModal })))
const ImportModelsModal = lazy(() => import('@/features/settings/modals/ImportModelsModal').then(m => ({ default: m.ImportModelsModal })))
const DeleteModelsModal = lazy(() => import('@/features/settings/modals/DeleteModelsModal').then(m => ({ default: m.DeleteModelsModal })))

/** 懒加载组件的加载占位符 */
function TabLoadingFallback() {
  return <div style={{ padding: '2rem', textAlign: 'center', color: '#9ca3af' }}>加载中...</div>
}

export function ApiTabContainer() {
  // 共享数据
  const {
    configurations,
    providers,
    setProviders,
    loadModelsData,
    invalidateTabCache,
  } = useSharedSettingsData()

  // 供应商表单逻辑（提取到独立 Hook）
  const providerFormState = useProviderForm({
    configurations,
    setProviders,
    loadModelsData,
    invalidateTabCache,
  })

  // 提取稳定的 setter 引用，避免 useCallback 依赖整个 providerFormState 对象
  const { setProviderForm } = providerFormState

  // 模型配置逻辑（提取到独立 Hook）
  const modelConfigState = useModelConfig({
    configurations,
    providerFormProvider: providerFormState.providerForm.provider,
    loadModelsData,
  })

  // 包装 onProviderFormChange，使其与 ApiSettings 的回调签名匹配（仅接受 updater 函数）
  const handleProviderFormChange = useCallback((
    updater: (prev: ApiProviderFormState) => ApiProviderFormState
  ) => {
    setProviderForm(updater)
  }, [setProviderForm])

  // 连通性测试回调
  const handleTestConnectivity = useCallback(async (
    provider: string,
    apiKey: string,
    baseUrl?: string
  ): Promise<ConnectivityTestResult> => {
    const response = await modelsAPI.testProviderConnectivity(provider, apiKey, baseUrl)
    return response.data as ConnectivityTestResult
  }, [])

  return (
    <>
      {providerFormState.message && (
        <div className={`message ${providerFormState.message.type}`}>
          {providerFormState.message.text}
        </div>
      )}
      <Suspense fallback={<TabLoadingFallback />}>
        <ApiSettings
          loadingApiProviders={providerFormState.loadingApiProviders}
          loadingProviderDetail={providerFormState.loadingProviderDetail}
          loadingProviderModels={providerFormState.loadingProviderModels}
          providerModelsError={providerFormState.providerModelsError}
          providers={providers}
          selectedProviderId={providerFormState.selectedProviderId}
          providerForm={providerFormState.providerForm}
          providerApiKeyInputRef={providerFormState.providerApiKeyInputRef as React.RefObject<HTMLInputElement>}
          providerStatuses={providerFormState.providerStatuses}
          loadingProviderStatuses={providerFormState.loadingProviderStatuses}
          ollamaModels={providerFormState.ollamaModels}
          loadingOllama={providerFormState.loadingOllama}
          ollamaError={providerFormState.ollamaError}
          saving={providerFormState.saving}
          deletingProvider={providerFormState.deletingProvider}
          showApiKey={providerFormState.showApiKey}
          onToggleShowApiKey={() => providerFormState.setShowApiKey(prev => !prev)}
          configurations={configurations}
          expandedModelConfigs={modelConfigState.expandedModelConfigs}
          modelEditParams={modelConfigState.modelEditParams}
          savingModelConfig={modelConfigState.savingModelConfig}
          selectedForDeletion={providerFormState.selectedForDeletion}
          onOpenCreateProviderModal={providerFormState.handleOpenCreateProviderModal}
          onProviderFormChange={handleProviderFormChange}
          onLoadProviderDetail={providerFormState.loadProviderDetail}
          onSaveProviderConfig={providerFormState.handleSaveProviderConfig}
          onOpenDeleteConfirmModal={providerFormState.handleOpenDeleteConfirmModal}
          onFetchModels={providerFormState.fetchProviderModels}
          onDiscoverOllama={providerFormState.handleDiscoverOllamaModels}
          onCheckProviderStatuses={providerFormState.handleCheckProviderStatuses}
          onToggleModelConfig={modelConfigState.toggleModelConfig}
          onSaveModelConfig={modelConfigState.handleSaveModelConfig}
          onResetModelConfig={modelConfigState.handleResetModelConfig}
          onUpdateModelEditParam={modelConfigState.updateModelEditParam}
          onSelectionChange={(modelName, checked) => {
            if (checked) {
              providerFormState.setSelectedForDeletion(prev => [...prev, modelName])
            } else {
              providerFormState.setSelectedForDeletion(prev => prev.filter(m => m !== modelName))
            }
          }}
          onOpenDeleteModelsModal={() => providerFormState.setShowDeleteModelsModal(true)}
          onTestConnectivity={handleTestConnectivity}
        />
      </Suspense>

      <Suspense fallback={null}>
        <CreateProviderModal
          isOpen={providerFormState.showCreateProviderModal}
          addProviderForm={providerFormState.addProviderForm}
          creatingProvider={providerFormState.creatingProvider}
          onClose={providerFormState.handleCloseCreateProviderModal}
          onChangeForm={providerFormState.setAddProviderForm}
          onCreate={providerFormState.handleCreateProvider}
        />
      </Suspense>

      <Suspense fallback={null}>
        <DeleteConfirmModal
          isOpen={providerFormState.showDeleteConfirmModal}
          providerName={providerFormState.providerForm.display_name.trim() || providerFormState.providerForm.provider}
          deletingProvider={providerFormState.deletingProvider}
          onClose={providerFormState.handleCloseDeleteConfirmModal}
          onConfirm={providerFormState.confirmDeleteProvider}
        />
      </Suspense>

      <Suspense fallback={null}>
        <ImportModelsModal
          isOpen={providerFormState.showImportModal}
          fetchedRemoteModels={providerFormState.fetchedRemoteModels}
          modalSelectedModels={providerFormState.modalSelectedModels}
          importing={providerFormState.importing}
          onClose={() => providerFormState.setShowImportModal(false)}
          onToggleModel={(modelName, checked) => {
            if (checked) {
              providerFormState.setModalSelectedModels(prev => [...prev, modelName])
            } else {
              providerFormState.setModalSelectedModels(prev => prev.filter(m => m !== modelName))
            }
          }}
          onImport={providerFormState.handleImportModels}
        />
      </Suspense>

      <Suspense fallback={null}>
        <DeleteModelsModal
          isOpen={providerFormState.showDeleteModelsModal}
          selectedCount={providerFormState.selectedForDeletion.length}
          deletingModels={providerFormState.deletingModels}
          onClose={() => providerFormState.setShowDeleteModelsModal(false)}
          onConfirm={providerFormState.handleBatchDeleteModels}
        />
      </Suspense>
    </>
  )
}
