"""以完全隔离的数据目录启动 Playwright E2E 后端。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


E2E_API_KEY = "openawa-e2e-api-key-at-least-32-characters"
JWT_SECRET = "openawa-e2e-jwt-secret-key-at-least-32-chars"
CSRF_SECRET = "openawa-e2e-csrf-secret-key-at-least-32-chars"
ENCRYPTION_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


def _configure_environment(runtime_dir: Path) -> int:
    """配置只作用于当前 E2E 子进程的隔离运行环境。"""
    backend_port = int(os.getenv("OPENAWA_E2E_BACKEND_PORT", "18000"))
    frontend_port = int(os.getenv("OPENAWA_E2E_FRONTEND_PORT", "15173"))
    database_path = runtime_dir / "openawa-e2e.db"
    workspace_path = runtime_dir / "workspace"
    workspace_path.mkdir(parents=True, exist_ok=True)

    isolated_values = {
        "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
        "VECTOR_DB_PATH": str(runtime_dir / "qdrant"),
        "INITIALIZED_MARKER_PATH": str(runtime_dir / ".initialized"),
        "DATA_DIR": str(runtime_dir / "data"),
        "OPENAWA_ENV_LOCAL_PATH": str(runtime_dir / ".env.local"),
        "OPENAWA_INIT_LOCK_PATH": str(runtime_dir / ".init.lock"),
        "LOG_DIR": str(runtime_dir / "logs"),
        "WORKSPACE_DIR": str(workspace_path),
        "ACP_ALLOWED_WORKDIRS": str(workspace_path),
        "OPENAWA_API_KEY": os.getenv("OPENAWA_E2E_API_KEY", E2E_API_KEY),
        "JWT_SECRET_KEY": JWT_SECRET,
        "CSRF_SECRET_KEY": CSRF_SECRET,
        "ENCRYPTION_KEY": ENCRYPTION_KEY,
        "OPENAWA_OWNER_PASSWORD": os.getenv("OPENAWA_ADMIN_PASSWORD", "OpenAwAE2e1"),
        "TESTING": "true",
        "ENVIRONMENT": "development",
        "ALLOWED_ORIGINS": (
            f"http://127.0.0.1:{frontend_port},"
            f"http://localhost:{frontend_port},"
            f"http://127.0.0.1:{backend_port}"
        ),
    }
    os.environ.update(isolated_values)
    return backend_port


def main() -> None:
    """创建临时运行目录并阻塞运行 Uvicorn，退出后自动清理。"""
    project_root = Path(__file__).resolve().parents[4]
    backend_dir = project_root / "backend"
    sys.path.insert(0, str(backend_dir))

    with tempfile.TemporaryDirectory(prefix="openawa-playwright-") as temp_dir:
        runtime_dir = Path(temp_dir)
        backend_port = _configure_environment(runtime_dir)
        os.chdir(backend_dir)

        import uvicorn

        uvicorn.run(
            "main:app",
            host="127.0.0.1",
            port=backend_port,
            log_level="info",
        )


if __name__ == "__main__":
    main()
