"""
openawa config 子命令 — 查看和修改 Open-AwA 配置。
"""
import click
import json
import os


@click.group(name="config")
def config():
    """
    查看和修改配置项。
    """
    pass


@config.command(name="list")
def config_list():
    """
    列出所有配置项。
    """
    try:
        import sys
        sys.path.insert(0, ".")
        from backend.config.settings import Settings

        settings = Settings()
        config_dict = {}
        for key in dir(settings):
            if key.isupper():
                value = getattr(settings, key, None)
                # 脱敏处理
                if any(s in key for s in ("KEY", "SECRET", "TOKEN", "PASSWORD")):
                    if isinstance(value, str) and value:
                        value = value[:4] + "****" if len(value) > 4 else "****"
                config_dict[key] = str(value) if value is not None else ""

        click.echo(json.dumps(config_dict, ensure_ascii=False, indent=2))
    except ImportError as e:
        click.echo(f"无法导入配置模块: {e}", err=True)


@config.command(name="get")
@click.argument("key")
def config_get(key: str):
    """
    获取指定配置项的值。
    """
    try:
        import sys
        sys.path.insert(0, ".")
        from backend.config.settings import Settings

        settings = Settings()
        value = getattr(settings, key, None)
        if value is None:
            click.echo(f"配置项 '{key}' 不存在")
        else:
            click.echo(f"{key}={value}")
    except ImportError as e:
        click.echo(f"无法导入配置模块: {e}", err=True)


@config.command(name="set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str):
    """
    设置配置项（写入 .env.local）。
    """
    env_path = os.path.join(os.getcwd(), ".env.local")
    try:
        # 读取现有内容
        lines = []
        found = False
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

        # 更新或追加
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}=") or line.strip().startswith(f"# {key}="):
                lines[i] = f"{key}={value}\n"
                found = True
                break

        if not found:
            lines.append(f"\n{key}={value}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        click.echo(f"已设置 {key}={value}")
    except Exception as e:
        click.echo(f"设置失败: {e}", err=True)


@config.command(name="show")
def config_show():
    """
    显示当前有效配置（脱敏输出）。
    """
    try:
        import sys
        sys.path.insert(0, ".")
        from backend.config.settings import Settings

        settings = Settings()
        click.echo("=== Open-AwA 配置 ===")
        click.echo(f"DATABASE_URL: {getattr(settings, 'DATABASE_URL', 'N/A')}")
        click.echo(f"VECTOR_DB_PATH: {getattr(settings, 'VECTOR_DB_PATH', 'N/A')}")
        click.echo(f"API_V1_STR: {getattr(settings, 'API_V1_STR', '/api')}")
        click.echo(f"DEBUG: {getattr(settings, 'DEBUG', False)}")

        sensitive_keys = ["SECRET_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
        for key in sensitive_keys:
            val = getattr(settings, key, None)
            displayed = "****" if val else "(未设置)"
            click.echo(f"{key}: {displayed}")
    except ImportError as e:
        click.echo(f"无法导入配置模块: {e}", err=True)
