"""
openawa plugin 子命令 — 管理插件的安装、卸载和状态。
"""
import click
import json
from pathlib import Path


@click.group(name="plugin")
def plugin():
    """
    管理插件的安装、卸载、启用和禁用。
    """
    pass


@plugin.command(name="list")
@click.option("--json-output", is_flag=True, help="JSON 格式输出")
def list_plugins(json_output: bool):
    """
    列出已安装的插件。
    """
    try:
        import sys
        sys.path.insert(0, ".")
        from backend.plugins.plugin_instance import get

        manager = get()
        plugins_list = []

        for p in manager.get_all_plugins():
            info = {
                "id": getattr(p, "id", ""),
                "name": getattr(p, "name", ""),
                "version": getattr(p, "version", "1.0.0"),
                "enabled": getattr(p, "enabled", True),
                "description": getattr(p, "description", ""),
            }
            plugins_list.append(info)

        if json_output:
            click.echo(json.dumps(plugins_list, ensure_ascii=False, indent=2))
        else:
            for p in plugins_list:
                status = "[x]" if p["enabled"] else "[ ]"
                click.echo(f"{status} {p['name']}  v{p['version']}")
    except ImportError as e:
        click.echo(f"无法导入插件模块: {e}", err=True)
    except Exception as e:
        click.echo(f"获取插件列表失败: {e}", err=True)


@plugin.command(name="install")
@click.argument("path_or_url")
def install_plugin(path_or_url: str):
    """
    安装插件（本地路径或远程 URL）。
    """
    click.echo(f"正在安装插件: {path_or_url}")
    try:
        import sys
        sys.path.insert(0, ".")
        from backend.plugins.plugin_instance import get

        manager = get()
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            result = manager.install_from_url(path_or_url)
        else:
            p = Path(path_or_url)
            if not p.exists():
                click.echo(f"文件不存在: {path_or_url}", err=True)
                return
            with open(p, "rb") as f:
                result = manager.install_from_bytes(f.read())

        if result:
            click.echo(f"插件安装成功: {result}")
        else:
            click.echo("插件安装失败", err=True)
    except ImportError as e:
        click.echo(f"无法导入插件模块: {e}", err=True)
    except Exception as e:
        click.echo(f"安装失败: {e}", err=True)


@plugin.command(name="uninstall")
@click.argument("plugin_name")
def uninstall_plugin(plugin_name: str):
    """
    卸载指定插件。
    """
    click.echo(f"正在卸载插件: {plugin_name}")
    try:
        import sys
        sys.path.insert(0, ".")
        from backend.plugins.plugin_instance import get

        manager = get()
        result = manager.uninstall_plugin(plugin_name)
        if result:
            click.echo(f"插件 '{plugin_name}' 已卸载")
        else:
            click.echo(f"卸载失败: 插件 '{plugin_name}' 不存在", err=True)
    except ImportError as e:
        click.echo(f"无法导入插件模块: {e}", err=True)


@plugin.command(name="enable")
@click.argument("plugin_name")
def enable_plugin(plugin_name: str):
    """启用插件。"""
    click.echo(f"启用插件: {plugin_name}")
    try:
        import sys
        sys.path.insert(0, ".")
        from backend.plugins.plugin_instance import get
        manager = get()
        manager.set_enabled(plugin_name, True)
        click.echo(f"插件 '{plugin_name}' 已启用")
    except Exception as e:
        click.echo(f"{e}", err=True)


@plugin.command(name="disable")
@click.argument("plugin_name")
def disable_plugin(plugin_name: str):
    """禁用插件。"""
    click.echo(f"禁用插件: {plugin_name}")
    try:
        import sys
        sys.path.insert(0, ".")
        from backend.plugins.plugin_instance import get
        manager = get()
        manager.set_enabled(plugin_name, False)
        click.echo(f"插件 '{plugin_name}' 已禁用")
    except Exception as e:
        click.echo(f"{e}", err=True)
