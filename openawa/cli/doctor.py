"""
openawa doctor 命令 — 系统诊断与健康检查。
"""
import os
import sys
import subprocess
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


def _check_python() -> tuple[bool, str]:
    """检查 Python 版本。"""
    version = sys.version_info
    if version >= (3, 11):
        return True, f"Python {version.major}.{version.minor}.{version.micro} [OK]"
    return False, f"Python {version.major}.{version.minor}.{version.micro} [需要 >= 3.11]"


def _check_node() -> tuple[bool, str]:
    """检查 Node.js 是否可用。"""
    try:
        result = subprocess.run(
            ["node", "--version"], capture_output=True, text=True, timeout=10
        )
        version = result.stdout.strip()
        return True, f"Node.js {version} [OK]"
    except FileNotFoundError:
        return False, "Node.js 未安装 [缺失]"
    except Exception as e:
        return False, f"Node.js 检查失败: {e}"


def _check_db(project_dir: Path) -> tuple[bool, str]:
    """检查数据库连接和表状态。"""
    backend_dir = project_dir / "backend"
    try:
        if backend_dir.is_dir():
            sys.path.insert(0, str(backend_dir))

        from openawa.db.models import engine, init_db, Base
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        expected = len(Base.metadata.sorted_tables)
        return True, f"数据库连接正常，{len(tables)}/{expected} 个表已创建 [OK]"
    except ImportError:
        try:
            from db.models import engine, Base
            from sqlalchemy import inspect
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            expected = len(Base.metadata.sorted_tables)
            return True, f"数据库连接正常（开发模式），{len(tables)}/{expected} 个表已创建 [OK]"
        except Exception as e:
            return False, f"数据库连接失败: {e}"
    except Exception as e:
        return False, f"数据库检查失败: {e}"


def _check_frontend(project_dir: Path) -> tuple[bool, str]:
    """检查前端构建状态。"""
    dist_dir = project_dir / "frontend" / "dist"
    if dist_dir.is_dir() and (dist_dir / "index.html").exists():
        return True, "前端已构建 [OK]"
    return False, "前端未构建，运行 'npm run build' 或 'openawa serve --build-frontend' [缺失]"


def _check_deps(project_dir: Path) -> tuple[bool, str]:
    """检查关键依赖是否可导入。"""
    required = {
        "fastapi": "FastAPI Web 框架",
        "uvicorn": "ASGI 服务器",
        "sqlalchemy": "数据库 ORM",
        "litellm": "多模型适配器",
        "chromadb": "向量数据库",
    }
    missing = []
    for module, desc in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(f"{module} ({desc})")

    if missing:
        return False, f"缺少依赖: {', '.join(missing)}"
    return True, "所有核心依赖可用 [OK]"


def _check_env() -> tuple[bool, str]:
    """检查环境配置。"""
    issues = []
    if not os.getenv("SECRET_KEY"):
        issues.append("SECRET_KEY 未设置（将自动生成开发密钥）")
    if not os.getenv("DASHSCOPE_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        issues.append("未检测到模型 API Key（DASHSCOPE_API_KEY 或 OPENAI_API_KEY）")

    if issues:
        return False, "; ".join(issues)
    return True, "环境配置正常 [OK]"


CHECKS = [
    ("Python 版本", _check_python),
    ("Node.js", _check_node),
    ("数据库连接", _check_db),
    ("前端构建", _check_frontend),
    ("核心依赖", _check_deps),
    ("环境配置", _check_env),
]


@click.command(name="doctor")
@click.option("--fix", is_flag=True, help="尝试自动修复可修复的问题")
def doctor(fix):
    """
    运行系统诊断，检查各组件健康状态。
    使用 --fix 可尝试自动修复常见问题。
    """
    project_dir = _get_project_dir()
    click.echo(f"[INFO] Open-AwA 系统诊断")
    click.echo(f"[INFO] 项目目录: {project_dir}")
    click.echo()

    all_ok = True
    for name, check_fn in CHECKS:
        try:
            if name in ("数据库连接", "核心依赖"):
                ok, msg = check_fn(project_dir)
            else:
                ok, msg = check_fn() if "Python" in name or "Node" in name or "环境" in name else check_fn(project_dir)
            status = "[OK]" if ok else "[FAIL]"
            click.echo(f"  {status} {name}: {msg}")
            if not ok:
                all_ok = False
        except Exception as e:
            click.echo(f"  [ERR] {name}: 检查异常 - {e}")
            all_ok = False

    click.echo()

    if all_ok:
        click.echo("[DONE] 所有检查通过，系统状态正常")
    else:
        click.echo("[WARN] 部分检查未通过，请根据上述提示修复")

    if fix:
        click.echo()
        click.echo("[INFO] 尝试自动修复...")
        _auto_fix(project_dir)


def _auto_fix(project_dir: Path):
    """自动修复常见问题。"""
    # 检查数据库表
    try:
        sys.path.insert(0, str(project_dir / "backend") if (project_dir / "backend").is_dir() else str(project_dir))
        try:
            from openawa.db.models import init_db
        except ImportError:
            from db.models import init_db
        init_db()
        click.echo("  [FIX] 数据库表已创建/更新")
    except Exception as e:
        click.echo(f"  [SKIP] 数据库修复失败: {e}")

    # 检查前端构建
    dist_dir = project_dir / "frontend" / "dist"
    if not (dist_dir.is_dir() and (dist_dir / "index.html").exists()):
        frontend_dir = project_dir / "frontend"
        if frontend_dir.is_dir():
            click.echo("  [FIX] 尝试构建前端...")
            try:
                subprocess.run(
                    ["npm", "run", "build"],
                    cwd=str(frontend_dir),
                    check=True,
                    env={**os.environ, "NODE_ENV": "production"},
                )
                click.echo("  [DONE] 前端构建成功")
            except subprocess.CalledProcessError:
                click.echo("  [FAIL] 前端构建失败，请手动运行 npm run build")

    # 检查并生成 SECRET_KEY
    env_local = project_dir / ".env.local"
    if not env_local.exists():
        try:
            import secrets
            secret_key = secrets.token_hex(32)
            env_local.write_text(f"SECRET_KEY={secret_key}\n", encoding="utf-8")
            click.echo("  [FIX] 已生成 .env.local 和 SECRET_KEY")
        except Exception as e:
            click.echo(f"  [SKIP] 生成 .env.local 失败: {e}")

    # 检查 pip 依赖
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "check"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            click.echo("  [WARN] pip 依赖存在冲突，请运行 pip check 查看详情")
            # 尝试自动安装缺失的依赖
            requirements = project_dir / "backend" / "requirements.txt"
            if requirements.exists():
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-r", str(requirements), "--quiet"],
                    capture_output=True,
                )
                click.echo("  [FIX] 已尝试安装 requirements.txt 依赖")
    except Exception:
        pass

    # 检查端口占用
    try:
        import socket
        for port, name in [(8000, "后端"), (5173, "前端开发")]:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            if result == 0:
                click.echo(f"  [WARN] 端口 {port} ({name}) 已被占用，可能影响启动")
    except Exception:
        pass

    # 验证 Alembic 迁移脚本可用
    alembic_dir = project_dir / "backend" / "alembic"
    if alembic_dir.is_dir():
        click.echo("  [INFO] Alembic 迁移系统可用，使用 openawa migrate upgrade 同步数据库")
    else:
        click.echo("  [INFO] 正在创建 Alembic 迁移目录...")
        try:
            subprocess.run(
                [sys.executable, "-m", "alembic", "init", str(alembic_dir)],
                cwd=str(project_dir / "backend"),
                capture_output=True,
            )
            click.echo("  [FIX] Alembic 初始化完成")
        except Exception:
            pass
