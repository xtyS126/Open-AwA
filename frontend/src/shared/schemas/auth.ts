/**
 * 认证相关表单校验 Schema。
 * 使用 zod 定义可复用校验规则，前端即时反馈，后端不可绕过。
 */
import { z } from 'zod';

/**
 * 访问密钥登录表单 Schema。
 * - 必填且去除首尾空白
 * - 至少 1 个字符（兼容 API Key 与密码两种登录方式：API Key 通常 40+ 字符，
 *   密码可能短至 8 位，统一不设最小长度上限，由后端认证顺序裁决）
 */
export const apiKeySchema = z.object({
  apiKey: z
    .string()
    .trim()
    .min(1, '请输入访问密钥或密码'),
});

export type ApiKeyFormValues = z.infer<typeof apiKeySchema>;

/**
 * 密码修改表单 Schema。
 * - 三个字段均必填
 * - newPassword 与 confirmPassword 必须一致
 * refine 的 path 指向 confirmPassword，使错误定位到确认密码输入框。
 */
export const passwordChangeSchema = z
  .object({
    oldPassword: z.string().min(1, '请填写所有密码字段'),
    newPassword: z.string().min(1, '请填写所有密码字段'),
    confirmPassword: z.string().min(1, '请填写所有密码字段'),
  })
  .refine((data) => data.newPassword === data.confirmPassword, {
    message: '两次输入的新密码不一致',
    path: ['confirmPassword'],
  });

export type PasswordChangeFormValues = z.infer<typeof passwordChangeSchema>;
