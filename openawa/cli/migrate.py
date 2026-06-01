"""
openawa migrate 命令 — 数据库迁移管理。
"""
import os
import sys
from pathlib import Path

import click


def _get_project_dir() -> Path:
    """获取项目根目录。"""
    cwd = Path.cwd()
    if (cwd / "backend").is_dir():
        return cwd
    if (cwd / "openawa").is_dir():
        return cwd
    return Path(__file__).resolve().parents[2]


@click.command(name="migrate")
@click.option("--dry-run", is_flag=True, help="仅显示将要执行的迁移，不实际执行")
def migrate(dry_run):
    """
    执行数据库迁移，创建或更新数据库表结构。
    使用 SQLAlchemy 的 create_all 机制，安全幂等。
    """
    project_dir = _get_project_dir()
    backend_dir = project_dir / "backend"
    if backend_dir.is_dir():
        sys.path.insert(0, str(backend_dir))

    click.echo("[INFO] 初始化数据库...")

    if dry_run:
        click.echo("[DRY-RUN] 将创建所有缺失的数据库表")
        try:
            from db.models import Base
            for table in Base.metadata.sorted_tables:
                click.echo(f"  - {table.name}")
        except ImportError:
            click.echo("[ERR] 无法加载数据库模型，请确认在项目根目录运行")
        return

    try:
        # 尝试 openawa 包模式
        from openawa.db.models import engine, init_db
        init_db()
        click.echo("[DONE] 数据库迁移完成（openawa 包模式）")
    except ImportError:
        try:
            # 回退到 backend 开发模式
            from db.models import engine, init_db
            init_db()
            click.echo("[DONE] 数据库迁移完成（开发模式）")
        except ImportError:
            # 直接尝试在 backend 目录运行
            backend_dir = project_dir / "backend"
            if backend_dir.is_dir():
                import subprocess
                result = subprocess.run(
                    [sys.executable, "-c",
                     "import sys; sys.path.insert(0, 'backend'); "
                     "from db.models import init_db; init_db(); "
                     "print('数据库迁移完成')"],
                    cwd=str(project_dir),
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    click.echo("[DONE] 数据库迁移完成")
                else:
                    click.echo(f"[ERR] 迁移失败: {result.stderr}", err=True)
            else:
                click.echo("[ERR] 无法定位数据库模块，请确认在项目根目录运行", err=True)
