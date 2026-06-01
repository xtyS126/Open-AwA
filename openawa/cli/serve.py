"""
openawa serve 命令 — 启动 Open-AwA 后端服务（支持前后端一体化部署和后台常驻）。
"""
import os
import sys
import time
import signal
import subprocess
from pathlib import Path

import click


def _get_project_dir() -> Path:
    """
    获取项目根目录（开发模式）或包安装目录。
    """
    # pip 安装模式：在 openawa 包目录的上两级
    package_dir = Path(__file__).resolve().parents[2]
    if (package_dir / "backend").is_dir():
        return package_dir
    # 开发模式：当前工作目录
    cwd = Path.cwd()
    if (cwd / "backend").is_dir():
        return cwd
    if (cwd / "main.py").is_dir() or (cwd / "openawa").is_dir():
        return cwd
    return package_dir


def _find_frontend_dist(project_dir: Path) -> Path | None:
    """
    查找前端构建产物目录。
    优先级：frontend/dist/ > 包内置 dist/
    """
    candidates = [
        project_dir / "frontend" / "dist",
        project_dir / "dist",
    ]
    for candidate in candidates:
        if candidate.is_dir() and (candidate / "index.html").exists():
            return candidate
    return None


def _build_frontend(project_dir: Path) -> bool:
    """
    构建前端（npm run build），返回是否成功。
    """
    frontend_dir = project_dir / "frontend"
    if not frontend_dir.is_dir():
        click.echo("[WARN] 未找到前端目录，跳过前端构建", err=True)
        return True

    if not (frontend_dir / "node_modules").is_dir():
        click.echo("[INFO] 安装前端依赖...")
        try:
            subprocess.run(
                ["npm", "install"],
                cwd=str(frontend_dir),
                check=True,
                capture_output=False,
            )
        except subprocess.CalledProcessError:
            click.echo("[ERR] 前端依赖安装失败", err=True)
            return False

    click.echo("[INFO] 构建前端...")
    try:
        subprocess.run(
            ["npm", "run", "build"],
            cwd=str(frontend_dir),
            check=True,
            capture_output=False,
            env={**os.environ, "NODE_ENV": "production"},
        )
        return True
    except subprocess.CalledProcessError:
        click.echo("[ERR] 前端构建失败", err=True)
        return False


def _load_app():
    """
    加载 FastAPI app 实例。
    优先使用 openawa 包（pip 安装模式），回退到 backend（开发模式）。
    """
    try:
        from openawa.main import app
        click.echo("[INFO] 使用 openawa 包模式启动")
        return app
    except ImportError:
        pass

    try:
        from main import app
        click.echo("[INFO] 使用 backend 开发模式启动")
        return app
    except ImportError:
        pass

    raise click.ClickException(
        "无法加载 Open-AwA 应用。请确保在项目根目录下运行，或已通过 pip 安装 openawa 包。"
    )


@click.command(name="serve")
@click.option("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
@click.option("--port", default=8000, type=int, help="监听端口（默认 8000）")
@click.option("--workers", default=1, type=int, help="工作进程数（默认 1）")
@click.option("--daemon/--no-daemon", default=False, help="后台常驻模式（默认关闭）")
@click.option("--pid-file", default=None, help="PID 文件路径（后台模式使用）")
@click.option("--log-file", default=None, help="日志文件路径（后台模式使用）")
@click.option("--reload/--no-reload", default=False, help="开发热重载（默认关闭）")
@click.option("--skip-frontend-build/--build-frontend", default=False, help="跳过前端构建（默认在无 dist 时自动构建）")
@click.option("--env", default="production", help="运行环境（development/production）")
def serve(host, port, workers, daemon, pid_file, log_file, reload, skip_frontend_build, env):
    """
    启动 Open-AwA 后端服务。

    开发模式自动构建前端并通过 Vite 代理提供热更新；
    生产模式将前端构建产物作为静态文件由后端直接提供。
    """
    project_dir = _get_project_dir()
    click.echo(f"[INFO] 项目目录: {project_dir}")

    # 设置环境变量
    os.environ.setdefault("BACKEND_HOST", host)
    os.environ.setdefault("BACKEND_PORT", str(port))
    os.environ.setdefault("ENVIRONMENT", env)

    # 前端处理：生产模式下检查是否需要构建
    if env == "production" or not reload:
        frontend_dist = _find_frontend_dist(project_dir)
        if not frontend_dist and not skip_frontend_build:
            if not _build_frontend(project_dir):
                raise click.ClickException("前端构建失败，无法启动服务")
            frontend_dist = _find_frontend_dist(project_dir)
        if frontend_dist:
            click.echo(f"[INFO] 前端静态文件: {frontend_dist}")

    # 构建 uvicorn 启动参数
    import uvicorn

    uvicorn_kwargs = {
        "host": host,
        "port": port,
        "workers": workers if not reload else 1,
        "log_level": "info",
        "reload": reload,
    }

    # 后台常驻模式
    if daemon:
        _start_daemon(host, port, workers, pid_file, log_file, reload, env, project_dir)
        return

    click.echo(f"[INFO] 启动服务 http://{host}:{port}")
    click.echo("[INFO] 按 Ctrl+C 停止服务")

    if reload:
        # 开发模式：直接从 backend 目录启动
        backend_dir = project_dir / "backend"
        uvicorn.run(
            "main:app",
            host=host,
            port=port,
            reload=True,
            reload_dirs=[str(backend_dir)] if backend_dir.is_dir() else None,
            log_level="info",
        )
    else:
        uvicorn.run(
            "openawa.main:app",
            host=host,
            port=port,
            workers=workers,
            log_level="info",
        )


def _start_daemon(host, port, workers, pid_file, log_file, reload, env, project_dir):
    """
    以后台守护进程模式启动服务。
    """
    if pid_file is None:
        pid_file = str(project_dir / "openawa.pid")
    if log_file is None:
        log_file = str(project_dir / "openawa.log")

    click.echo(f"[INFO] 后台启动服务 http://{host}:{port}")
    click.echo(f"[INFO] PID 文件: {pid_file}")
    click.echo(f"[INFO] 日志文件: {log_file}")

    # 构建 uvicorn 命令
    python_exe = sys.executable
    cmd = [
        python_exe, "-m", "uvicorn",
        "openawa.main:app",
        "--host", host,
        "--port", str(port),
        "--workers", str(workers),
        "--log-level", "info",
    ]

    if reload:
        cmd.append("--reload")

    # 启动后台进程
    with open(log_file, "a") as log_fp:
        process = subprocess.Popen(
            cmd,
            stdout=log_fp,
            stderr=subprocess.STDOUT,
            cwd=str(project_dir),
            start_new_session=True,
        )

    # 写入 PID 文件
    with open(pid_file, "w") as pf:
        pf.write(str(process.pid))

    click.echo(f"[INFO] 服务已启动 (PID: {process.pid})")
    click.echo(f"[INFO] 使用 'kill {process.pid}' 或删除 {pid_file} 来停止服务")
