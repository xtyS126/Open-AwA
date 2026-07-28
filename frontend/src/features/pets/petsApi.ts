/**
 * 宠物 API 模块 —— 封装 /api/pets 端点的后端通信。
 * 与 skillsApi.ts 一致，使用共享的 axios 实例（默认导出 api）。
 */
import api from '@/shared/api/api'
import type {
  PetListResponse,
  PetActiveResponse,
  PetResponse,
} from './types'

/** 对宠物 ID（含冒号，如 builtin:codex / custom:...）做 URL 编码，避免路由解析异常 */
function encodeId(id: string): string {
  return encodeURIComponent(id)
}

/** 获取全部宠物列表（内置 + 自定义） */
export async function listPets(): Promise<PetListResponse> {
  const response = await api.get<PetListResponse>('/pets')
  return response.data
}

/** 获取当前激活宠物；pet_id 为 null 表示未启用宠物 */
export async function getActivePet(): Promise<PetActiveResponse> {
  const response = await api.get<PetActiveResponse>('/pets/active')
  return response.data
}

/** 设置当前激活宠物：传入宠物 slug 形式的 pet_id；传 "disable" 字符串关闭宠物 */
export async function setActivePet(petId: string): Promise<PetActiveResponse> {
  const response = await api.put<PetActiveResponse>('/pets/active', { pet_id: petId })
  return response.data
}

/** 删除指定宠物（仅自定义宠物可删，id 形如 custom:...） */
export async function deletePet(id: string): Promise<void> {
  await api.delete(`/pets/${encodeId(id)}`)
}

/** 获取宠物 manifest JSON */
export async function getPetManifest(id: string): Promise<Record<string, unknown>> {
  const response = await api.get<Record<string, unknown>>(`/pets/${encodeId(id)}/manifest`)
  return response.data
}

/** 构造精灵表图片 URL，可直接用于 <img src> 或 Image.src */
export function getPetSpritesheetUrl(id: string): string {
  return `/pets/${encodeId(id)}/spritesheet`
}

/** 导入宠物所需文件集合：文件模式需 manifest + spritesheet，归档模式仅需 archive */
export interface ImportPetFiles {
  /** pet.json 清单文件（文件模式必填） */
  manifest?: File | null
  /** 精灵表图片文件（文件模式必填） */
  spritesheet?: File | null
  /** zip 归档文件（归档模式必填） */
  archive?: File | null
}

/** 导入自定义宠物：文件模式（manifest_file + spritesheet_file）或 zip 归档模式（archive） */
export async function importPet(files: ImportPetFiles): Promise<PetResponse> {
  const formData = new FormData()
  let hasField = false
  if (files.archive) {
    formData.append('archive', files.archive)
    hasField = true
  } else {
    if (files.manifest) {
      formData.append('manifest_file', files.manifest)
      hasField = true
    }
    if (files.spritesheet) {
      formData.append('spritesheet_file', files.spritesheet)
      hasField = true
    }
  }
  if (!hasField) {
    throw new Error('请提供导入文件（pet.json + 精灵表，或 zip 归档）')
  }
  // Content-Type 由浏览器根据 FormData 自动设置为 multipart/form-data
  const response = await api.post<PetResponse>('/pets/import', formData)
  return response.data
}