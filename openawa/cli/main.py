"""
Open-AwA 统一命令行入口。
用法: openawa [serve|migrate|doctor|user|config]
"""
import sys
import os
import click


def _ensure_project_path():
    """
    将项目根目录加入 sys.path，确保可以导入 backend 或 openawa 包。
    """
    # pip 安装模式下 openawa 包已在 site-packages
    # 开发模式下需要在项目根目录运行
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    # 同时尝试加入 backend 目录（开发模式）
    backend_dir = os.path.join(cwd, "backend")
    if os.path.isdir(backend_dir) and backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)


@click.group()
@click.version_option(version="1.0.0", prog_name="openawa")
@click.pass_context
def cli(ctx):
    """
    Open-AwA AI Agent 平台管理工具。

    管理 Open-AwA 服务的启动、数据库迁移、系统诊断和用户管理。
    """
    _ensure_project_path()
    ctx.ensure_object(dict)


# 注册子命令
from openawa.cli.serve import serve
from openawa.cli.migrate import migrate
from openawa.cli.doctor import doctor
from openawa.cli.user import user

cli.add_command(serve)
cli.add_command(migrate)
cli.add_command(doctor)
cli.add_command(user)


if __name__ == "__main__":
    cli()
