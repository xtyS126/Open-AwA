"""可选的宿主机代理引导的 Docker runtime 辅助工具。"""

from __future__ import annotations

import os
import shutil
import socket
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, MutableMapping

_DEFAULT_PROXY_HOST = "host.docker.internal"
_DEFAULT_PROXY_PORT = 7897
_DEFAULT_PROXY_TIMEOUT = 1.0
_DEFAULT_RUNTIME_ROOT = "/app/runtime"
_DEFAULT_TEMPLATE_PATH = "/app/config.example.toml"
_DEFAULT_NO_PROXY_ENTRIES = ("127.0.0.1", "localhost", "host.docker.internal")
_PROXY_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def bootstrap_runtime_root(
    *,
    runtime_root: Path,
    template_path: Path,
    env: MutableMapping[str, str] | None = None,
) -> None:
    """缺失时创建带 config/data/logs 的隔离 runtime 根目录。

    当 ``env`` 中设置了 ``OPENBILICLAW_SEED_OLLAMA_DEFAULTS``（Docker
    compose 文件默认开启），新创建的 config 会预填两个值，使内置
    Ollama sidecar 开箱即用：

      * ``[llm.ollama] base_url`` → ``OPENBILICLAW_OLLAMA_BASE_URL``
        （默认 ``http://ollama:11434/v1`` —— compose 服务名）
      * ``[llm.embedding] provider`` → ``ollama``
      * ``[llm.embedding] model`` → ``OPENBILICLAW_EMBEDDING_MODEL``
        （默认 ``bge-m3``）
      * ``[llm.embedding] base_url`` → ``OPENBILICLAW_OLLAMA_BASE_URL``

    已存在的 ``config.toml`` 绝不会被覆盖——已经搭建了自己 embedding
    栈的用户会保留他们的选择。
    """
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "data").mkdir(parents=True, exist_ok=True)
    (runtime_root / "logs").mkdir(parents=True, exist_ok=True)

    config_path = runtime_root / "config.toml"
    if config_path.exists() or not template_path.exists():
        return

    shutil.copyfile(template_path, config_path)

    resolved_env = env if env is not None else os.environ
    if str(resolved_env.get("OPENBILICLAW_SEED_OLLAMA_DEFAULTS", "")).strip():
        ollama_base = (
            resolved_env.get("OPENBILICLAW_OLLAMA_BASE_URL", "").strip() or "http://ollama:11434/v1"
        )
        embedding_model = resolved_env.get("OPENBILICLAW_EMBEDDING_MODEL", "").strip() or "bge-m3"
        _seed_ollama_defaults(config_path, ollama_base, embedding_model)


def _seed_ollama_defaults(
    config_path: Path,
    ollama_base_url: str,
    embedding_model: str,
) -> None:
    """在新复制的模板 config 中修改 [llm.ollama] 下的 ``base_url`` 以及
    [llm.embedding] 下的 provider/model。

    基于行的编辑器：config 模板对我们涉及的字段仅使用单行字符串
    值，因此一次小型原地编辑足矣，避免仅为此时引入 TOML 写入依赖。
    """
    text = config_path.read_text(encoding="utf-8")
    text = _set_toml_string(text, "llm.ollama", "base_url", ollama_base_url)
    text = _set_toml_string(text, "llm.embedding", "provider", "ollama")
    text = _set_toml_string(text, "llm.embedding", "model", embedding_model)
    text = _set_toml_string(text, "llm.embedding", "base_url", ollama_base_url)
    config_path.write_text(text, encoding="utf-8")


def _set_toml_string(content: str, section: str, key: str, value: str) -> str:
    """将 ``[section]`` 下的 ``key = "..."`` 替换为 ``key = "<value>"``。

    缺失时同时追加 section 头和 key/value 对，因此该辅助函数在
    部分模板上幂等。忽略注释行和内联表。
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    new_line = f'{key} = "{escaped}"'
    section_header = f"[{section}]"

    lines = content.splitlines()
    in_section = False
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == section_header
            continue
        if not in_section or stripped.startswith("#") or "=" not in stripped:
            continue
        lhs = stripped.split("=", 1)[0].strip()
        if lhs == key:
            indent = raw_line[: len(raw_line) - len(raw_line.lstrip())]
            lines[index] = f"{indent}{new_line}"
            trailing_newline = "\n" if content.endswith("\n") else ""
            return "\n".join(lines) + trailing_newline

    # Section/key 不存在：在末尾追加一个新块。
    suffix: list[str] = []
    if not content.endswith("\n"):
        suffix.append("")
    suffix.append(section_header)
    suffix.append(new_line)
    return content + "\n".join(suffix) + "\n"


def can_connect(host: str, port: int, timeout: float) -> bool:
    """返回 TCP 端点是否可达。"""
    with socket.create_connection((host, port), timeout=timeout):
        return True


def resolve_optional_proxy_env(
    env: dict[str, str] | os._Environ[str],
    *,
    can_connect: Callable[[str, int, float], bool] = can_connect,
    proxy_host: str = _DEFAULT_PROXY_HOST,
    proxy_port: int = _DEFAULT_PROXY_PORT,
    timeout: float = _DEFAULT_PROXY_TIMEOUT,
) -> dict[str, str]:
    """当宿主机侧 Clash 代理可达时返回代理 env 更新。"""
    if any(str(env.get(key, "")).strip() for key in _PROXY_KEYS):
        return {}

    if not can_connect(proxy_host, proxy_port, timeout):
        return {}

    proxy_url = f"http://{proxy_host}:{proxy_port}"
    no_proxy = _merge_no_proxy(env.get("NO_PROXY", "") or env.get("no_proxy", ""))
    return {
        "HTTP_PROXY": proxy_url,
        "HTTPS_PROXY": proxy_url,
        "ALL_PROXY": proxy_url,
        "http_proxy": proxy_url,
        "https_proxy": proxy_url,
        "all_proxy": proxy_url,
        "NO_PROXY": no_proxy,
        "no_proxy": no_proxy,
    }


def _merge_no_proxy(current: str) -> str:
    """将所需的本地旁路主机合并进 no_proxy。"""
    entries = [item.strip() for item in current.split(",") if item.strip()]
    for entry in _DEFAULT_NO_PROXY_ENTRIES:
        if entry not in entries:
            entries.append(entry)
    return ",".join(entries)


def is_running_in_container(env: MutableMapping[str, str] | None = None) -> bool:
    """返回当前进程是否在容器 runtime 中运行。

    下方的主机代理自动检测仅在容器内安全——
    容器内 ``host.docker.internal`` 确实指向宿主机且是通往互联网的
    唯一路径。在原生 macOS 开发机上，Docker Desktop 仍会解析该名称——
    因此若没有此门禁，引导器会把每个出站请求路由到宿主机的
    Clash 代理，破坏 Bilibili 调用（以及任何不容忍 Clash 路由的请求）。
    """
    resolved_env = env if env is not None else os.environ
    if str(resolved_env.get("OPENBILICLAW_IN_CONTAINER", "")).strip():
        return True
    # Docker 写入 /.dockerenv；Podman 写入 /run/.containerenv。
    return Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()


def bootstrap_runtime_environment(
    env: MutableMapping[str, str],
    *,
    can_connect: Callable[[str, int, float], bool] = can_connect,
    in_container: Callable[[MutableMapping[str, str]], bool] = is_running_in_container,
) -> None:
    """原地引导隔离 runtime 根目录和可选代理 env。"""
    runtime_root = Path(env.get("OPENBILICLAW_PROJECT_ROOT", _DEFAULT_RUNTIME_ROOT))
    template_path = Path(env.get("OPENBILICLAW_CONFIG_TEMPLATE", _DEFAULT_TEMPLATE_PATH))
    bootstrap_runtime_root(
        runtime_root=runtime_root,
        template_path=template_path,
        env=env,
    )
    env.setdefault("OPENBILICLAW_PROJECT_ROOT", str(runtime_root))

    # 代理自动检测仅在容器 runtime 内安全。
    if not in_container(env):
        return

    proxy_host = env.get("OPENBILICLAW_PROXY_HOST", _DEFAULT_PROXY_HOST).strip()
    proxy_port = int(env.get("OPENBILICLAW_PROXY_PORT", str(_DEFAULT_PROXY_PORT)))
    timeout = float(env.get("OPENBILICLAW_PROXY_TIMEOUT", str(_DEFAULT_PROXY_TIMEOUT)))
    env.update(
        resolve_optional_proxy_env(
            dict(env),
            can_connect=can_connect,
            proxy_host=proxy_host,
            proxy_port=proxy_port,
            timeout=timeout,
        )
    )


def main(argv: list[str] | None = None) -> int:
    """引导可选代理设置，然后 exec 目标命令。"""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise SystemExit("usage: python -m openbiliclaw.docker_runtime <command> [args...]")

    bootstrap_runtime_environment(os.environ)
    os.execvpe(args[0], args, os.environ)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
