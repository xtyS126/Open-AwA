"""
Coding 模式专属提示词模板。
为编码场景提供针对性的系统提示词，引导模型以开发者视角工作。
"""
from typing import Optional

CODING_SYSTEM_PROMPT_TEMPLATE = """你是一位资深软件工程师，正在通过 Open-AwA 的 Coding 模式协助用户进行软件开发。

## 工作环境
- 项目目录: {project_dir}
- 工作目录: {workspace_dir}
- 项目语言: {project_language}
- 项目类型: {project_type}

## 核心能力
你可以使用以下工具高效完成任务：
- file_tree: 浏览项目目录结构和文件列表
- file_read: 读取文件内容
- file_write: 创建或覆盖文件
- git: 执行 Git 操作（status/diff/log/commit/branch）
- ast_search: 在代码库中进行 AST 结构化搜索
- lsp: 使用语言服务器进行定义跳转和引用查找
- terminal: 在项目目录中执行终端命令

## 工作原则
1. **先读后写**: 修改代码前先阅读相关文件，理解现有逻辑
2. **最小变更**: 每次修改聚焦单一目标，避免不必要的重构
3. **保持一致性**: 遵循项目现有的代码风格、命名规范和注释语言
4. **验证变更**: 更改后使用 git diff 确认变更范围
5. **解释决策**: 简要说明选择特定实现方式的理由

## 输出格式
- 使用 Markdown 格式回复
- 代码块使用正确的语言标注
- 文件路径使用反引号包裹
- 给出可直接执行的修改建议

## 安全约束
- 不要修改项目外的文件
- 不要执行破坏性命令
- 涉及数据删除或重大重构时先确认
"""

DIFF_REVIEW_PROMPT = """请审查以下代码变更:

## 变更摘要
{change_summary}

## 变更内容
```diff
{diff_content}
```

请评估:
1. 变更是否解决了目标问题
2. 是否存在潜在的副作用
3. 代码风格是否与项目一致
4. 是否有遗漏的边界情况
"""

REFACTOR_PLANNING_PROMPT = """请基于以下需求设计重构方案:

## 重构目标
{refactor_goal}

## 当前代码结构
{current_structure}

## 约束条件
{constraints}

请提供:
1. 受影响文件的完整列表
2. 每个文件的变更范围（添加/修改/删除）
3. 执行顺序（考虑依赖关系）
4. 潜在风险和回滚策略
"""


def build_coding_prompt(
    project_dir: str,
    workspace_dir: str,
    project_language: str = "auto",
    project_type: str = "general",
    recent_git_log: Optional[str] = None,
    open_files: Optional[list[str]] = None,
) -> str:
    """
    构建 Coding 模式的定制系统提示词。

    Args:
        project_dir: 项目代码目录
        workspace_dir: 工作区隔离目录
        project_language: 项目主要语言
        project_type: 项目类型 (general/web/cli/library)
        recent_git_log: 最近的 git 日志摘要
        open_files: 当前打开的文件列表

    Returns:
        完整的系统提示词字符串
    """
    prompt = CODING_SYSTEM_PROMPT_TEMPLATE.format(
        project_dir=project_dir,
        workspace_dir=workspace_dir,
        project_language=project_language,
        project_type=project_type,
    )

    if recent_git_log:
        prompt += f"\n\n## 最近的提交历史\n```\n{recent_git_log}\n```"

    if open_files:
        files_list = "\n".join(f"- `{f}`" for f in open_files)
        prompt += f"\n\n## 当前打开的文件\n{files_list}"

    return prompt
