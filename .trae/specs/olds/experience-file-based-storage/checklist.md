# Checklist

## 范围与目标
- [x] 规格范围聚焦于修复经验页 500、切换到 `memory_skill` Markdown 文件源、改造 `experience-extractor`
- [x] 未引入用户未明确要求的高成本扩展能力

## 后端接口
- [x] 后端可列出 `memory_skill` 目录下所有 Markdown 文件
- [x] 后端可读取单个 Markdown 文件完整内容
- [x] 后端可保存编辑后的 Markdown 内容
- [x] 目录不存在时不会返回 500，而是自动创建或安全返回空结果
- [x] 文件不存在时返回明确错误而非未捕获异常
- [x] 非法文件路径会被拒绝，且不会访问目录外文件

## experience-extractor
- [x] `experience-extractor` 提取结果保存到 `memory_skill` 目录
- [x] 新生成的经验以 Markdown 文件形式落盘
- [x] 保存结果包含足够的成功信息用于确认

## 前端经验页
- [x] 经验页展示的是 `memory_skill` 中的 Markdown 文件，而不是旧数据库记录
- [x] 页面可以打开且不再因旧接口异常而不可用
- [x] 用户可以查看单个 Markdown 文件内容
- [x] 用户可以编辑并保存 Markdown 内容
- [x] 空目录、加载失败、保存失败时页面有明确反馈
- [x] 访问 `/experience` 时 `main` 区域不再空白
- [x] 侧边栏“经验”菜单可以稳定命中已注册页面组件

## 验证
- [x] 手动验证经验页加载、查看、编辑、保存主流程
- [x] 手动验证 `experience-extractor` 生成文件主流程
- [x] 已运行并通过项目已有的相关测试/类型检查/构建命令
