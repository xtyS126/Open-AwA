"""
访问密钥生成工具。

用法：
    python generate_api_key.py              # 生成新密钥并写入 .env.local
    python generate_api_key.py --show       # 仅生成并打印，不写入文件
    python generate_api_key.py --force      # 强制替换已有密钥
"""

import argparse
import logging
import re
import secrets
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


BACKEND_DIR = Path(__file__).resolve().parent
ENV_LOCAL = BACKEND_DIR / ".env.local"
KEY_NAME = "OPENAWA_API_KEY"


def _read_existing_key() -> str | None:
    """从 .env.local 读取现有 OPENAWA_API_KEY，不存在则返回 None。"""
    if not ENV_LOCAL.exists():
        return None
    content = ENV_LOCAL.read_text(encoding="utf-8")
    match = re.search(rf"^{KEY_NAME}=(.+)$", content, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return None



def generate_key() -> str:
    """生成带 sk- 前缀的 43 字符随机密钥。"""
    return "sk-" + secrets.token_urlsafe(32)


def persist_key(new_key: str) -> None:
    """将密钥写入 .env.local（替换已有行或追加），并设置仅 owner 可读写权限。"""
    if ENV_LOCAL.exists() and ENV_LOCAL.stat().st_size > 0:
        content = ENV_LOCAL.read_text(encoding="utf-8")
        if re.search(rf"^{KEY_NAME}=", content, re.MULTILINE):
            content = re.sub(
                rf"^{KEY_NAME}=.*$",
                f"{KEY_NAME}={new_key}",
                content,
                flags=re.MULTILINE,
            )
            ENV_LOCAL.write_text(content, encoding="utf-8")
            _restrict_permissions(ENV_LOCAL)
        else:
            with open(ENV_LOCAL, "a", encoding="utf-8") as f:
                f.write(f"\n{KEY_NAME}={new_key}\n")
            _restrict_permissions(ENV_LOCAL)
    else:
        ENV_LOCAL.parent.mkdir(parents=True, exist_ok=True)
        ENV_LOCAL.write_text(f"{KEY_NAME}={new_key}\n", encoding="utf-8")
        _restrict_permissions(ENV_LOCAL)


def _restrict_permissions(path: Path) -> None:
    """将文件权限设为仅 owner 可读写（Unix: 0o600, Windows: 隐藏文件）。"""
    try:
        # Unix: 仅 owner 可读写
        import stat
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except Exception as e:
        logger.warning("设置文件权限失败（Windows 下可忽略）: %s", e)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Open-AwA 访问密钥生成工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python generate_api_key.py           # 生成新密钥\n"
            "  python generate_api_key.py --show    # 仅显示不保存\n"
            "  python generate_api_key.py --force   # 强制替换已有密钥\n"
        ),
    )
    parser.add_argument(
        "--show", action="store_true",
        help="仅生成并打印密钥，不写入 .env.local",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="强制替换已有密钥（默认：已有密钥则拒绝覆盖）",
    )
    args = parser.parse_args()

    existing = _read_existing_key()
    if existing and not args.force and not args.show:
        print(f"已存在访问密钥: {existing}")
        print(f"文件: {ENV_LOCAL}")
        print()
        print("如需替换，请使用 --force 参数:")
        print("  python generate_api_key.py --force")
        sys.exit(0)

    new_key = generate_key()

    if args.show:
        print(f"访问密钥: {new_key}")
        print()
        print("将此密钥设置为环境变量或在 .env.local 中添加:")
        print(f"  {KEY_NAME}={new_key}")
        return

    try:
        persist_key(new_key)
        print(f"访问密钥已生成并写入 {ENV_LOCAL}")
        if existing:
            print(f"旧密钥: {existing}")
        print(f"新密钥: {new_key}")
        print()
        print("请重启服务以使用新密钥。")
        print("登录页面输入此密钥即可访问系统。")
    except PermissionError:
        print(f"无法写入 {ENV_LOCAL}（权限不足）。")
        print()
        print("请用管理员权限运行，或手动将以下内容添加到 .env.local：")
        print(f"  {KEY_NAME}={new_key}")
        print()
        print("或在环境变量中设置：")
        print(f"  $env:OPENAWA_API_KEY=\"{new_key}\"  (PowerShell)")
        sys.exit(1)


if __name__ == "__main__":
    main()
