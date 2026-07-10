"""
AI 驱动命令系统，支持 Markdown 定义的命令模板。

参考 OpenCode .opencode/command/*.md 设计：
- 命令通过 Markdown + Frontmatter 定义
- 支持 !`command` shell 注入语法
- 支持指定模型、subtask 模式
- 命令发现：从 .open-awa/commands/ 目录加载
"""

import asyncio
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from security.command_whitelist import ALLOWED_COMMANDS as _ALLOWED_COMMANDS


@dataclass
class CommandDefinition:
    """AI 命令定义"""
    name: str
    description: str = ""
    model: Optional[str] = None       # 指定使用的模型
    subtask: bool = False             # 是否作为子任务运行
    template: str = ""                # Markdown 模板内容
    source_file: Optional[str] = None

    @staticmethod
    def _run_platform_builtin(args: List[str]) -> Optional[str]:
        """执行不依赖 shell 的平台内建命令，保持 shell=False 的安全边界。"""
        if not args or os.name != "nt":
            return None

        command = args[0].lower()
        if command == "echo":
            return " ".join(args[1:])
        if command == "pwd":
            return os.getcwd()
        return None

    def render_template(self, context: Optional[Dict[str, Any]] = None) -> str:
        """
        渲染命令模板。

        支持的语法：
        - !`command` — 执行 shell 命令并注入输出
        - {{variable}} — 注入上下文变量
        """
        rendered = self.template

        # 处理 !`command` 语法
        rendered = self._expand_shell_commands(rendered)

        # 处理 {{variable}} 语法
        if context:
            for key, value in context.items():
                rendered = rendered.replace(f"{{{{{key}}}}}", str(value))

        return rendered

    @staticmethod
    def _expand_shell_commands(template: str) -> str:
        """展开模板中的 !`command` shell 命令（仅允许安全命令白名单）"""

        def _run_shell(match: re.Match) -> str:
            command_str = match.group(1).strip()
            if not command_str:
                return "(空命令)"

            # 安全白名单校验：提取命令名并检查是否在白名单中
            try:
                args = shlex.split(command_str)
            except ValueError as e:
                return f"(无法解析命令: {e})"

            if not args:
                return "(空命令)"

            cmd_name = os.path.basename(args[0])  # 防止路径遍历
            if cmd_name not in _ALLOWED_COMMANDS:
                return (
                    f"(命令被阻止: {cmd_name} 不在安全白名单中。"
                    f"允许的命令: {', '.join(sorted(_ALLOWED_COMMANDS))})"
                )

            builtin_output = CommandDefinition._run_platform_builtin(args)
            if builtin_output is not None:
                return builtin_output if builtin_output else "(no output)"

            try:
                result = subprocess.run(
                    args,
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=os.getcwd(),
                )
                output = result.stdout.strip()
                if result.returncode != 0:
                    output += f"\n(stderr: {result.stderr.strip()})"
                return output if output else "(no output)"
            except subprocess.TimeoutExpired:
                return f"(命令超时: {command_str})"
            except FileNotFoundError:
                return f"(命令未找到: {cmd_name})"
            except Exception as e:
                return f"(命令执行失败: {e})"

        return re.sub(r'!`([^`]+)`', _run_shell, template)

    @staticmethod
    def parse_from_markdown(filepath: str) -> Optional["CommandDefinition"]:
        """
        从 Markdown 文件解析命令定义。

        Frontmatter 字段：
        - description: 命令描述
        - model: 指定模型
        - subtask: 是否子任务

        Body: 命令模板内容
        """
        try:
            content = Path(filepath).read_text(encoding="utf-8")
        except Exception as exc:
            # 文件读取失败时降级为 None，记录 debug 便于排查命令定义加载问题
            logger.debug(f"[command_executor] 命令定义文件读取失败: {filepath}, error={exc}")
            return None

        # 解析 frontmatter
        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", content, re.DOTALL)
        if not frontmatter_match:
            return None

        try:
            import yaml
            frontmatter = yaml.safe_load(frontmatter_match.group(1)) or {}
        except Exception:
            frontmatter = {}

        body = frontmatter_match.group(2).strip() if frontmatter_match.group(2) else ""

        # 从文件名推断名称
        name = Path(filepath).stem

        return CommandDefinition(
            name=name,
            description=frontmatter.get("description", ""),
            model=frontmatter.get("model"),
            subtask=frontmatter.get("subtask", False),
            template=body,
            source_file=filepath,
        )


class CommandExecutor:
    """
    AI 命令执行器。

    负责：
    1. 从目录发现命令定义
    2. 渲染命令模板
    3. 执行命令并调用 LLM
    """

    def __init__(self, commands_dir: Optional[str] = None):
        self._commands: Dict[str, CommandDefinition] = {}
        self._commands_dir = commands_dir
        self._llm_call: Optional[Callable] = None  # async def(prompt, **kwargs) -> str

    def set_llm_call(self, llm_call: Callable) -> None:
        """设置 LLM 调用函数"""
        self._llm_call = llm_call

    def discover_commands(self, commands_dir: Optional[str] = None) -> int:
        """
        从目录发现命令定义。

        扫描 *.md 文件，解析 frontmatter 和模板内容。
        """
        search_dir = commands_dir or self._commands_dir
        if not search_dir:
            return 0

        search_path = Path(search_dir)
        if not search_path.exists():
            logger.debug(f"命令目录不存在: {search_dir}")
            return 0

        count = 0
        for md_file in search_path.glob("*.md"):
            # 跳过 README 等非命令文件
            if md_file.stem.lower() in ("readme", "index"):
                continue

            definition = CommandDefinition.parse_from_markdown(str(md_file))
            if definition:
                self._commands[definition.name] = definition
                count += 1
                logger.debug(f"已发现命令: {definition.name} ({md_file})")

        if count > 0:
            logger.info(f"从 {search_dir} 发现了 {count} 个命令")
        return count

    def register_builtin(self, definition: CommandDefinition) -> None:
        """注册内建命令"""
        self._commands[definition.name] = definition

    def get_command(self, name: str) -> Optional[CommandDefinition]:
        """获取指定的命令定义"""
        return self._commands.get(name)

    def list_commands(self) -> List[CommandDefinition]:
        """列出所有可用命令"""
        return list(self._commands.values())

    def render_command(
        self,
        name: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        渲染命令模板。

        Args:
            name: 命令名称
            context: 模板变量上下文

        Returns:
            渲染后的提示文本
        """
        command = self._commands.get(name)
        if not command:
            logger.warning(f"命令不存在: {name}")
            return None

        try:
            return command.render_template(context)
        except Exception as e:
            logger.error(f"渲染命令模板失败 [{name}]: {e}")
            return None

    async def execute(
        self,
        name: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        执行 AI 命令。

        1. 渲染模板
        2. 调用 LLM
        3. 返回结果

        Args:
            name: 命令名称
            context: 执行上下文

        Returns:
            LLM 执行结果
        """
        command = self._commands.get(name)
        if not command:
            return None

        prompt = command.render_template(context)

        if not self._llm_call:
            logger.error("CommandExecutor 未配置 LLM 调用函数")
            return None

        try:
            kwargs = {}
            if command.model:
                kwargs["model"] = command.model

            result = await self._llm_call(prompt=prompt, **kwargs)
            return result
        except Exception as e:
            logger.error(f"执行命令 [{name}] 失败: {e}")
            return None


# 内建命令定义
BUILTIN_COMMANDS = [
    CommandDefinition(
        name="commit",
        description="生成 git commit message 并提交",
        template="""请基于以下 git diff 生成一个符合 Conventional Commits 规范的提交信息。

要求：
- 类型前缀：[New]/[Fix]/[Optimization]/[Refactoring]/[Documentation]/[Test]/[Configuration]
- 清晰描述变更内容
- 解释为什么做这个变更（从用户视角）

## GIT DIFF
!`git diff`

## GIT STATUS
!`git status --short`

请输出提交信息（单行）。""",
    ),
    CommandDefinition(
        name="changelog",
        description="生成变更日志",
        template="""请基于 git log 生成变更日志。

格式：按日期分组，每条包含类型标签和简短描述。

## GIT LOG
!`git log --oneline -20`

请生成 Markdown 格式的变更日志。""",
    ),
    CommandDefinition(
        name="review",
        description="代码审查",
        subtask=True,
        template="""请审查以下代码变更，检查：
1. 正确性：逻辑错误、边界情况
2. 安全：注入风险、权限问题
3. 性能：不必要的循环、阻塞调用
4. 可维护性：命名、注释、代码结构

## GIT DIFF
!`git diff`

请输出结构化的审查报告。""",
    ),
]
