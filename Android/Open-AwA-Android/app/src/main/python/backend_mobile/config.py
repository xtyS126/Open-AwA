"""
backend_mobile 配置模块

移动端内嵌后端的配置：数据库路径、密钥、CORS 等。
与桌面版 backend/config/settings.py 的差异：
- 数据库使用应用私有目录下的 SQLite
- 密钥在首次启动时生成并持久化到 SharedPreferences（通过文件桥接）
- CORS 允许 WebView 同源访问
"""

import os
import secrets
import threading
from pathlib import Path
from typing import Optional


class MobileSettings:
    """
    移动端配置（单例）

    所有字段在首次访问时初始化，线程安全。
    """

    _instance: Optional["MobileSettings"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "MobileSettings":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """初始化配置（仅执行一次）"""
        # 应用数据目录：Chaquopy 启动时通过环境变量 OPENAWA_DATA_DIR 注入
        # 默认fallback到当前工作目录（仅用于桌面调试）
        self.data_dir: Path = Path(
            os.environ.get("OPENAWA_DATA_DIR", ".")
        ).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 数据库文件路径
        self.database_path: Path = self.data_dir / "openawa_mobile.db"
        self.database_url: str = f"sqlite:///{self.database_path}"

        # 密钥文件路径（持久化生成的密钥）
        self.secret_key_path: Path = self.data_dir / "secret.key"

        # JWT 密钥：首次启动生成并持久化
        self.jwt_secret_key: str = self._load_or_create_secret("jwt")
        # CSRF 密钥
        self.csrf_secret_key: str = self._load_or_create_secret("csrf")
        # 加密密钥（Fernet 兼容，32 字节 base64）
        self.encryption_key: str = self._load_or_create_secret("encryption", length=44)
        # API Key（前端登录凭证，移动端单用户场景，首次启动生成并持久化）
        # 通过 EmbeddedBackend.getApiKey() 暴露给 Kotlin 层，前端启动时自动持久化
        self.api_key: str = self._load_or_create_secret("api_key", length=32)

        # JWT 配置
        self.access_token_expire_minutes: int = 60 * 24 * 7  # 7 天
        self.access_token_cookie_name: str = "openawa_access_token"
        self.csrf_cookie_name: str = "openawa_csrf_token"
        self.csrf_header_name: str = "X-CSRF-Token"

        # CORS 配置：移动端 WebView 同源访问，但仍允许调试时跨域
        self.cors_allow_origins: list[str] = ["*"]
        self.cors_allow_credentials: bool = True

        # 环境标识
        self.environment: str = "mobile"
        self.platform: str = "android"
        self.version: str = "1.0.0-mobile"

        # 默认管理员账号（首次启动时自动创建）
        self.default_admin_username: str = "admin"
        self.default_admin_password: str = "admin123"  # 仅移动端调试用，桌面版应警告

    def _load_or_create_secret(self, name: str, length: int = 64) -> str:
        """
        从文件加载密钥，不存在则生成新密钥并持久化

        参数：
            name: 密钥用途标识（jwt/csrf/encryption）
            length: 密钥长度（字节）
        """
        # 多密钥合并存储到一个文件，每行 "name:secret"
        secrets_file = self.secret_key_path
        secrets_map: dict[str, str] = {}
        try:
            if secrets_file.exists():
                for line in secrets_file.read_text(encoding="utf-8").splitlines():
                    if ":" in line:
                        key, value = line.split(":", 1)
                        secrets_map[key.strip()] = value.strip()
        except OSError:
            # 文件读取失败时重新生成
            pass

        if name in secrets_map:
            return secrets_map[name]

        # 生成新密钥
        new_secret = secrets.token_urlsafe(length)
        secrets_map[name] = new_secret
        try:
            secrets_file.write_text(
                "\n".join(f"{k}:{v}" for k, v in secrets_map.items()),
                encoding="utf-8",
            )
        except OSError:
            # 文件写入失败时仅内存保留（重启后失效）
            pass

        return new_secret

    def __repr__(self) -> str:
        return (
            f"MobileSettings(data_dir={self.data_dir}, "
            f"database_url={self.database_url}, "
            f"version={self.version})"
        )


def get_settings() -> MobileSettings:
    """获取配置单例"""
    return MobileSettings()
