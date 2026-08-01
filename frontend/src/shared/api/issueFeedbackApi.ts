/**
 * 问题反馈 API 模块。封装用户问题反馈提交端点。自 api.ts 拆分而来。
 */
import { api } from './client'
import type { IssueFeedbackPayload, IssueFeedbackSubmitResponse } from './types'

export const issueFeedbackAPI = {
  submit: (payload: IssueFeedbackPayload) =>
    api
      .post<IssueFeedbackSubmitResponse>('/feedback/issue', payload)
      .then((r) => r.data),
}
