"""
openawa user 命令 — 用户管理。
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


@click.group(name="user")
def user():
    """
    用户管理命令组。
    """
    pass


@user.command(name="list")
@click.option("--role", default=None, help="按角色筛选（admin/developer/viewer）")
def list_users(role):
    """
    列出所有用户。
    """
    project_dir = _get_project_dir()
    backend_dir = project_dir / "backend"
    if backend_dir.is_dir():
        sys.path.insert(0, str(backend_dir))

    click.echo("[INFO] 查询用户列表...")

    try:
        try:
            from openawa.db.models import User
        except ImportError:
            from db.models import User
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        # 获取数据库路径
        db_url = os.getenv("DATABASE_URL", f"sqlite:///{project_dir}/backend/openawa.db")
        engine = create_engine(db_url, connect_args={"check_same_thread": False})
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        try:
            query = db.query(User)
            if role:
                query = query.filter(User.role == role)
            users = query.all()

            if not users:
                click.echo("  (无用户)")
                return

            click.echo(f"  {'ID':<6} {'用户名':<20} {'角色':<12} {'邮箱'}")
            click.echo(f"  {'-'*6} {'-'*20} {'-'*12} {'-'*30}")
            for u in users:
                click.echo(f"  {u.id:<6} {u.username:<20} {u.role or 'N/A':<12} {u.email or 'N/A'}")
            click.echo(f"\n  共 {len(users)} 个用户")
        finally:
            db.close()
    except Exception as e:
        click.echo(f"[ERR] 查询失败: {e}", err=True)


@user.command(name="create")
@click.option("--username", prompt=True, help="用户名")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True, help="密码")
@click.option("--email", default=None, help="邮箱")
@click.option("--role", default="developer", type=click.Choice(["admin", "developer", "viewer"]), help="角色")
def create_user(username, password, email, role):
    """
    创建新用户。
    """
    project_dir = _get_project_dir()
    backend_dir = project_dir / "backend"
    if backend_dir.is_dir():
        sys.path.insert(0, str(backend_dir))

    click.echo(f"[INFO] 创建用户: {username}")

    try:
        try:
            from openawa.db.models import User
        except ImportError:
            from db.models import User
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from passlib.hash import pbkdf2_sha256
        import secrets

        db_url = os.getenv("DATABASE_URL", f"sqlite:///{project_dir}/backend/openawa.db")
        engine = create_engine(db_url, connect_args={"check_same_thread": False})
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        try:
            # 检查是否已存在
            existing = db.query(User).filter(User.username == username).first()
            if existing:
                click.echo(f"[ERR] 用户 '{username}' 已存在", err=True)
                return

            new_user = User(
                username=username,
                email=email,
                role=role,
                password_hash=pbkdf2_sha256.hash(password),
            )
            db.add(new_user)
            db.commit()
            click.echo(f"[DONE] 用户 '{username}' 创建成功 (角色: {role})")
        finally:
            db.close()
    except Exception as e:
        click.echo(f"[ERR] 创建失败: {e}", err=True)


@user.command(name="delete")
@click.argument("username")
@click.option("--force", is_flag=True, help="跳过确认，直接删除")
def delete_user(username, force):
    """
    删除指定用户。
    """
    project_dir = _get_project_dir()
    backend_dir = project_dir / "backend"
    if backend_dir.is_dir():
        sys.path.insert(0, str(backend_dir))

    if not force:
        if not click.confirm(f"确认删除用户 '{username}'？此操作不可撤销"):
            click.echo("操作已取消")
            return

    click.echo(f"[INFO] 删除用户: {username}")

    try:
        try:
            from openawa.db.models import User
        except ImportError:
            from db.models import User
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        db_url = os.getenv("DATABASE_URL", f"sqlite:///{project_dir}/backend/openawa.db")
        engine = create_engine(db_url, connect_args={"check_same_thread": False})
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        try:
            target = db.query(User).filter(User.username == username).first()
            if not target:
                click.echo(f"[ERR] 用户 '{username}' 不存在", err=True)
                return
            db.delete(target)
            db.commit()
            click.echo(f"[DONE] 用户 '{username}' 已删除")
        finally:
            db.close()
    except Exception as e:
        click.echo(f"[ERR] 删除失败: {e}", err=True)
