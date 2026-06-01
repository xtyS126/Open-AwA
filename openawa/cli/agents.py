"""
openawa agents 子命令 — 管理 Agent/工作区。
"""
import click
import json
from loguru import logger


@click.group(name="agents")
def agents():
    """
    管理 Agent（工作区）的创建、查看和删除。
    """
    pass


@agents.command(name="list")
@click.option("--workspace", "-w", default="default", help="工作区 ID")
@click.option("--json-output", is_flag=True, help="JSON 格式输出")
def list_agents(workspace: str, json_output: bool):
    """
    列出所有 Agent/工作区。
    """
    try:
        import sys
        sys.path.insert(0, ".")
        from backend.core.workspace.manager import WorkspaceManager

        manager = WorkspaceManager()
        workspaces = manager.list_workspaces()

        if json_output:
            click.echo(json.dumps(workspaces, ensure_ascii=False, indent=2))
        else:
            for ws in workspaces:
                status = "[x]" if ws.get("enabled", True) else "[ ]"
                click.echo(f"{status} {ws['id'][:12]}  {ws['name']}  ({ws['agent_type']})")
    except ImportError as e:
        click.echo(f"无法导入后端模块: {e}", err=True)


@agents.command(name="create")
@click.option("--name", "-n", required=True, help="Agent 名称")
@click.option("--type", "-t", "agent_type", default="general", help="Agent 类型 (general/code/qa/writing/planning/custom)")
@click.option("--description", "-d", default="", help="Agent 描述")
def create_agent(name: str, agent_type: str, description: str):
    """
    创建新 Agent/工作区。
    """
    try:
        import sys
        sys.path.insert(0, ".")
        from backend.core.workspace.manager import WorkspaceManager

        manager = WorkspaceManager()
        result = manager.create_workspace(
            name=name,
            agent_type=agent_type,
            description=description,
        )
        click.echo(f"Agent 已创建: {result['id'][:12]}  {result['name']}")
    except ImportError as e:
        click.echo(f"无法导入后端模块: {e}", err=True)
    except Exception as e:
        click.echo(f"创建失败: {e}", err=True)


@agents.command(name="delete")
@click.argument("agent_id")
@click.option("--force", "-f", is_flag=True, help="强制删除，不确认")
def delete_agent(agent_id: str, force: bool):
    """
    删除指定 Agent/工作区。
    """
    if not force:
        if not click.confirm(f"确认删除 Agent '{agent_id}'？此操作不可撤销。"):
            click.echo("已取消")
            return
    try:
        import sys
        sys.path.insert(0, ".")
        from backend.core.workspace.manager import WorkspaceManager

        manager = WorkspaceManager()
        success = manager.delete_workspace(agent_id)
        if success:
            click.echo(f"Agent '{agent_id}' 已删除")
        else:
            click.echo(f"删除失败: Agent 不存在或为默认工作区", err=True)
    except ImportError as e:
        click.echo(f"无法导入后端模块: {e}", err=True)


@agents.command(name="logs")
@click.argument("agent_id", required=False)
@click.option("--limit", "-n", default=10, help="显示条数")
def agent_logs(agent_id: str, limit: int):
    """
    查看 Agent 执行日志。
    """
    click.echo("执行日志功能需连接运行中的后端服务")
