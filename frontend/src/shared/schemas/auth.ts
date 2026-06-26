/**
 * 认证相关表单校验 Schema。
 * 使用 zod 定义可复用校验规则，前端即时反馈，后端不可绕过。
 */
import { z } from 'zod';

/**
 * 访问密钥登录表单 Schema。
 * - 必填且去除首尾空白
 * - 长度 >= 20（与后端 OPENAWA_API_KEY 最小长度约束对齐）
 */
export const apiKeySchema = z.object({
  apiKey: z
    .string()
    .trim()
    .min(1, '请输入访问密钥')
    .min(20, '认证失败'),
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
