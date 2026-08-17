import { codingApi } from '@/features/coding/codingApi'

// @ts-expect-error 普通字符串没有通过工作台项目 ID 品牌校验。
void codingApi.gitStatus('project-123')
