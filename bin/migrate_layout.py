"""
项目目录重组迁移脚本。

功能：
    将 Open-AwA 根目录重组为 lib/ var/ bin/ assets/ deploy/ 五个统一目录。
    仅负责文件/目录移动与目录创建，路径替换与构建配置更新由人工后续执行。

用法：
    python bin/migrate_layout.py --dry-run    # 输出迁移计划但不实际执行
    python bin/migrate_layout.py --apply      # 实际执行迁移

设计原则：
    - 幂等：源不存在则跳过，目标已存在则记录冲突不覆盖
    - 可追溯：每次操作打印日志
    - 安全：不删除任何文件，仅移动
    - 中文注释、无 emoji、完整类型标注
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# ============================================================================
# 项目根目录定位：bin/migrate_layout.py 的 parents[1] 即为项目根
# parents[0]=bin/  parents[1]=项目根/
# ============================================================================
_SCRIPT_FILE: Path = Path(__file__).resolve()
PROJECT_ROOT: Path = _SCRIPT_FILE.parents[1]


# ============================================================================
# 目录创建清单：迁移前需确保这些目标目录存在
# ============================================================================
DIRECTORIES_TO_CREATE: list[str] = [
    "lib",
    "var",
    "var/data",
    "var/logs",
    "var/workspace",
    "var/plugins",
    "var/pets",
    "bin",
    "assets",
    "assets/design",
    "deploy",
    "deploy/nginx",
    "docs/reports",
]


@dataclass(frozen=True)
class MoveOperation:
    """单个移动操作的定义。

    Attributes:
        source: 源路径（相对项目根）
        destination: 目标路径（相对项目根）
        category: 操作分类（lib/var/bin/assets/deploy/docs）
        is_optional: True 表示源不存在时静默跳过（运行时数据常见）
        description: 人类可读的操作说明
    """

    source: str
    destination: str
    category: str
    is_optional: bool
    description: str


# ============================================================================
# 文件/目录移动清单：按 category 分组，顺序执行
# ============================================================================
MOVE_OPERATIONS: list[MoveOperation] = [
    # ---------- lib/：子项目迁入 ----------
    MoveOperation(
        source="backend",
        destination="lib/backend",
        category="lib",
        is_optional=False,
        description="后端 Python 项目迁入 lib/",
    ),
    MoveOperation(
        source="frontend",
        destination="lib/frontend",
        category="lib",
        is_optional=False,
        description="前端 React 项目迁入 lib/",
    ),
    MoveOperation(
        source="desktop",
        destination="lib/desktop",
        category="lib",
        is_optional=False,
        description="Electron 桌面壳迁入 lib/",
    ),
    MoveOperation(
        source="Android",
        destination="lib/Android",
        category="lib",
        is_optional=False,
        description="Android 原生项目迁入 lib/",
    ),
    MoveOperation(
        source="openawa",
        destination="lib/openawa",
        category="lib",
        is_optional=False,
        description="CLI 工具包迁入 lib/",
    ),

    # ---------- var/：运行时数据迁入（全部 optional，gitignored 数据可能不存在） ----------
    MoveOperation(
        source="backend/openawa.db",
        destination="var/data/openawa.db",
        category="var",
        is_optional=True,
        description="SQLite 主数据库迁入 var/data/",
    ),
    MoveOperation(
        source="backend/openawa.db-shm",
        destination="var/data/openawa.db-shm",
        category="var",
        is_optional=True,
        description="SQLite WAL 共享内存文件迁入 var/data/",
    ),
    MoveOperation(
        source="backend/openawa.db-wal",
        destination="var/data/openawa.db-wal",
        category="var",
        is_optional=True,
        description="SQLite WAL 日志文件迁入 var/data/",
    ),
    MoveOperation(
        source="backend/openawa_e2e.db",
        destination="var/data/openawa_e2e.db",
        category="var",
        is_optional=True,
        description="E2E 测试数据库迁入 var/data/",
    ),
    MoveOperation(
        source="backend/openawa_e2e_debug.db",
        destination="var/data/openawa_e2e_debug.db",
        category="var",
        is_optional=True,
        description="E2E 调试数据库迁入 var/data/",
    ),
    MoveOperation(
        source="backend/logs",
        destination="var/logs",
        category="var",
        is_optional=True,
        description="后端运行时日志迁入 var/logs/",
    ),
    MoveOperation(
        source="backend/workspace",
        destination="var/workspace",
        category="var",
        is_optional=True,
        description="后端工作区迁入 var/workspace/",
    ),
    MoveOperation(
        source="backend/uploads",
        destination="var/data/uploads",
        category="var",
        is_optional=True,
        description="后端上传文件迁入 var/data/uploads/",
    ),
    MoveOperation(
        source="backend/data/qdrant",
        destination="var/data/qdrant",
        category="var",
        is_optional=True,
        description="Qdrant 向量数据库迁入 var/data/qdrant/",
    ),
    MoveOperation(
        source="backend/data/issue_reports",
        destination="var/data/issue_reports",
        category="var",
        is_optional=True,
        description="问题反馈落盘目录迁入 var/data/issue_reports/",
    ),
    MoveOperation(
        source="backend/data/task_runtime",
        destination="var/data/task_runtime",
        category="var",
        is_optional=True,
        description="任务运行时 transcript 迁入 var/data/task_runtime/",
    ),
    MoveOperation(
        source="backend/data/models",
        destination="var/data/models",
        category="var",
        is_optional=True,
        description="本地模型缓存迁入 var/data/models/",
    ),
    MoveOperation(
        source="backend/data/pets",
        destination="var/data/pets",
        category="var",
        is_optional=True,
        description="宠物内置资源缓存迁入 var/data/pets/",
    ),
    MoveOperation(
        source="openawa/openawa.db",
        destination="var/data/openawa-cli.db",
        category="var",
        is_optional=True,
        description="CLI 工具数据库迁入 var/data/",
    ),

    # ---------- bin/：可执行脚本迁入 ----------
    MoveOperation(
        source="dev.bat",
        destination="bin/dev.bat",
        category="bin",
        is_optional=False,
        description="开发启动脚本迁入 bin/",
    ),
    MoveOperation(
        source="backend/generate_api_key.py",
        destination="bin/generate_api_key.py",
        category="bin",
        is_optional=False,
        description="API Key 生成工具迁入 bin/",
    ),
    MoveOperation(
        source="scripts/deploy.ps1",
        destination="bin/deploy.ps1",
        category="bin",
        is_optional=False,
        description="Windows 部署脚本迁入 bin/",
    ),
    MoveOperation(
        source="scripts/install.ps1",
        destination="bin/install.ps1",
        category="bin",
        is_optional=False,
        description="Windows 安装脚本迁入 bin/",
    ),

    # ---------- assets/design/：设计稿迁入 ----------
    MoveOperation(
        source="open-awa-canvas",
        destination="assets/design/open-awa-canvas",
        category="assets",
        is_optional=False,
        description="设计稿迁入 assets/design/",
    ),

    # ---------- deploy/：Docker 与 nginx 配置迁入 ----------
    MoveOperation(
        source="Dockerfile",
        destination="deploy/Dockerfile",
        category="deploy",
        is_optional=False,
        description="后端 Dockerfile 迁入 deploy/",
    ),
    MoveOperation(
        source="docker-compose.yml",
        destination="deploy/docker-compose.yml",
        category="deploy",
        is_optional=False,
        description="基础 docker-compose 配置迁入 deploy/",
    ),
    MoveOperation(
        source="docker-compose.prod.yml",
        destination="deploy/docker-compose.prod.yml",
        category="deploy",
        is_optional=False,
        description="生产 docker-compose 覆盖配置迁入 deploy/",
    ),
    MoveOperation(
        source="docker-compose.quick.yml",
        destination="deploy/docker-compose.quick.yml",
        category="deploy",
        is_optional=False,
        description="零配置 docker-compose 配置迁入 deploy/",
    ),
    MoveOperation(
        source="docker-compose.postgres.yml",
        destination="deploy/docker-compose.postgres.yml",
        category="deploy",
        is_optional=False,
        description="PostgreSQL docker-compose 配置迁入 deploy/",
    ),
    MoveOperation(
        source="nginx.conf",
        destination="deploy/nginx.conf",
        category="deploy",
        is_optional=False,
        description="Nginx 基础配置迁入 deploy/",
    ),
    MoveOperation(
        source="docker/entrypoint.sh",
        destination="deploy/entrypoint.sh",
        category="deploy",
        is_optional=False,
        description="后端容器入口脚本迁入 deploy/",
    ),
    MoveOperation(
        source="docker/init-ssl.sh",
        destination="deploy/init-ssl.sh",
        category="deploy",
        is_optional=False,
        description="SSL 证书初始化脚本迁入 deploy/",
    ),
    MoveOperation(
        source="docker/nginx/ssl.conf",
        destination="deploy/nginx/ssl.conf",
        category="deploy",
        is_optional=False,
        description="Nginx SSL 子配置迁入 deploy/nginx/",
    ),

    # ---------- docs/reports/：合并 reports/ ----------
    MoveOperation(
        source="reports/ai-calling-security-audit.md",
        destination="docs/reports/ai-calling-security-audit.md",
        category="docs",
        is_optional=False,
        description="AI 调用安全审计报告合并入 docs/reports/",
    ),
    MoveOperation(
        source="reports/code-review-fix-plan.md",
        destination="docs/reports/code-review-fix-plan.md",
        category="docs",
        is_optional=False,
        description="代码审查修复计划合并入 docs/reports/",
    ),
    MoveOperation(
        source="reports/frontend-refactoring-plan.md",
        destination="docs/reports/frontend-refactoring-plan.md",
        category="docs",
        is_optional=False,
        description="前端重构方案合并入 docs/reports/",
    ),
    MoveOperation(
        source="reports/project-review-2026-06-13.md",
        destination="docs/reports/project-review-2026-06-13.md",
        category="docs",
        is_optional=False,
        description="项目复盘报告合并入 docs/reports/",
    ),
]


# ============================================================================
# 路径替换规则（仅文档化，不由本脚本执行）
# 迁移完成后由人工按此清单逐项更新代码与配置文件中的硬编码路径
# ============================================================================
PATH_REPLACEMENT_RULES: list[dict[str, str]] = [
    # ---------- 后端路径常量 ----------
    {
        "file": "lib/backend/config/settings.py",
        "rule": "_PROJECT_DIR 改为 Path(__file__).resolve().parents[3]；新增 _VAR_DIR / _DATA_DIR / _LOG_DIR / _WORKSPACE_DIR / _PLUGINS_DATA_DIR / _PETS_DATA_DIR；DATABASE_URL 指向 var/data/openawa.db；VECTOR_DB_PATH 指向 var/data/qdrant；LOG_DIR 指向 var/logs",
    },
    {
        "file": "lib/backend/main.py",
        "rule": "_project_root 路径深度调整（parents[2]）；_FRONTEND_DIST 改为 _project_root / 'lib' / 'frontend' / 'dist'；_avatars_dir 改为绝对路径指向 var/data/uploads/avatars",
    },
    {
        "file": "lib/backend/core/initialization.py",
        "rule": "_DEFAULT_MARKER_DIR 改为 Path('var/data')；注释中 backend/data 改为 var/data",
    },
    {
        "file": "lib/backend/pets/asset_pack.py",
        "rule": "注释中 backend/data/pets/builtin 改为 var/data/pets/builtin；若代码写入该路径则同步更新",
    },
    {
        "file": "lib/backend/api/routes/acp.py",
        "rule": "注释中 backend/workspace 改为 var/workspace；ACP_ALLOWED_WORKDIRS 默认值同步更新",
    },
    {
        "file": "lib/backend/tests/test_settings_paths.py",
        "rule": "expected_path 改为 Path(__file__).resolve().parents[3] / 'var' / 'data' / 'openawa.db'",
    },
    # ---------- 构建配置 ----------
    {
        "file": "deploy/Dockerfile",
        "rule": "COPY frontend/ → COPY lib/frontend/；COPY backend/ → COPY lib/backend/；COPY openawa/ → COPY lib/openawa/；COPY docker/entrypoint.sh → COPY deploy/entrypoint.sh；mkdir -p /app/data /app/logs /app/backend/workspace → mkdir -p /app/var/data /app/var/logs /app/var/workspace；ENV LOG_DIR / DATABASE_URL / VECTOR_DB_PATH 路径前缀改为 /app/var/",
    },
    {
        "file": "deploy/docker-compose.yml",
        "rule": "build.dockerfile: Dockerfile → deploy/Dockerfile；build.dockerfile: frontend/Dockerfile → lib/frontend/Dockerfile；volumes: /app/data → /app/var/data；/app/logs → /app/var/logs；/app/openawa/uploads → /app/var/uploads；/app/backend/workspace → /app/var/workspace；environment 中 DATABASE_URL / VECTOR_DB_PATH / LOG_DIR 同步更新",
    },
    {
        "file": "deploy/docker-compose.prod.yml",
        "rule": "./docker/nginx/ssl.conf → ./deploy/nginx/ssl.conf",
    },
    {
        "file": "deploy/docker-compose.quick.yml",
        "rule": "同 docker-compose.yml 的 volumes 与 environment 路径更新；build.dockerfile: Dockerfile → deploy/Dockerfile",
    },
    {
        "file": "deploy/entrypoint.sh",
        "rule": "ENV_LOCAL_FILE=/app/data/.env.local → /app/var/data/.env.local；mkdir -p /app/data → mkdir -p /app/var/data",
    },
    {
        "file": "pyproject.toml",
        "rule": "[tool.setuptools] packages=['openawa'] → [tool.setuptools.packages.find] where=['lib'] include=['backend*','openawa*']；[tool.coverage.run] source=['openawa'] → source=['lib/openawa']",
    },
    {
        "file": "lib/frontend/vite.config.ts",
        "rule": "cacheDir: path.resolve(__dirname, '..', '.vite-cache') → path.resolve(__dirname, '..', '..', '.vite-cache')（保持项目根 .vite-cache）",
    },
    {
        "file": "lib/desktop/scripts/build-frontend.ts",
        "rule": "path.resolve(__dirname, '..', '..', 'frontend') → path.resolve(__dirname, '..', '..', '..', 'lib', 'frontend')",
    },
    {
        "file": "lib/desktop/scripts/dev.ts",
        "rule": "path.resolve(__dirname, '..', '..', 'frontend') → path.resolve(__dirname, '..', '..', '..', 'lib', 'frontend')",
    },
    # ---------- 脚本与启动文件 ----------
    {
        "file": "bin/dev.bat",
        "rule": "pushd \"%~dp0backend\" → pushd \"%~dp0lib\\backend\"；pushd \"%~dp0frontend\" → pushd \"%~dp0lib\\frontend\"；frontend\\node_modules 路径前缀加 lib\\",
    },
    {
        "file": "bin/deploy.ps1",
        "rule": "compose 文件路径加 deploy/ 前缀；docker/init-ssl.sh → deploy/init-ssl.sh",
    },
    {
        "file": "bin/install.ps1",
        "rule": "$ProjectDir\\backend\\requirements.txt → $ProjectDir\\lib\\backend\\requirements.txt；$ProjectDir\\frontend → $ProjectDir\\lib\\frontend；sys.path.insert(0, 'backend') → 'lib/backend'",
    },
    {
        "file": "bin/generate_api_key.py",
        "rule": "BACKEND_DIR = Path(__file__).resolve().parent → BACKEND_DIR = Path(__file__).resolve().parent.parent / 'lib' / 'backend'",
    },
    {
        "file": "scripts/install.sh",
        "rule": "../backend → ../lib/backend；./backend → ./lib/backend；$PROJECT_DIR/frontend → $PROJECT_DIR/lib/frontend",
    },
    # ---------- .gitignore ----------
    {
        "file": ".gitignore",
        "rule": "添加 var/ 整体忽略；移除 backend/openawa_e2e*.db / backend/data/* / backend/uploads/ / backend/logs 等旧条目；Android/Open-AwA-Android/* → lib/Android/Open-AwA-Android/*；openawa/* → lib/openawa/*；frontend/* → lib/frontend/*",
    },
    # ---------- 文档 ----------
    {
        "file": "README.md / CLAUDE.md / AGENTS.md / docs/架构/*.md / docs/指南/*.md",
        "rule": "cd backend → cd lib/backend；cd frontend → cd lib/frontend；backend/openawa.db → var/data/openawa.db；backend/data → var/data；backend/logs → var/logs；backend/workspace → var/workspace；dev.bat → bin/dev.bat；scripts/deploy.ps1 → bin/deploy.ps1；scripts/install.ps1 → bin/install.ps1；backend/generate_api_key.py → bin/generate_api_key.py",
    },
]


def _resolve(rel_path: str) -> Path:
    """将相对项目根的路径解析为绝对 Path 对象。"""
    return (PROJECT_ROOT / rel_path).resolve()


def _ensure_directories(dry_run: bool) -> int:
    """创建所有目标目录。返回成功创建的目录数。"""
    created_count: int = 0
    print("\n" + "=" * 70)
    print("  阶段 1/3：创建目标目录")
    print("=" * 70)
    for rel_dir in DIRECTORIES_TO_CREATE:
        target: Path = _resolve(rel_dir)
        if target.exists():
            print(f"  [SKIP]   目录已存在: {rel_dir}")
            continue
        if dry_run:
            print(f"  [DRY]    将创建目录: {rel_dir}")
        else:
            target.mkdir(parents=True, exist_ok=True)
            print(f"  [DONE]   已创建目录: {rel_dir}")
        created_count += 1
    return created_count


def _execute_move(op: MoveOperation, dry_run: bool) -> str:
    """执行单个移动操作，返回状态字符串（OK / SKIP / CONFLICT / DRY）。

    状态语义：
        OK       - 成功移动
        SKIP     - 源不存在（optional 操作常见）
        CONFLICT - 目标已存在，不覆盖
        DRY      - dry-run 模式下计划移动
    """
    src: Path = _resolve(op.source)
    dst: Path = _resolve(op.destination)

    if not src.exists():
        if op.is_optional:
            return "SKIP"
        return f"MISSING_SRC"

    if dst.exists():
        return "CONFLICT"

    if dry_run:
        return "DRY"

    # 确保目标父目录存在
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return "OK"


def _run_moves(operations: Iterable[MoveOperation], dry_run: bool) -> dict[str, int]:
    """执行移动操作列表，返回按状态统计的字典。"""
    print("\n" + "=" * 70)
    print("  阶段 2/3：移动文件与目录")
    print("=" * 70)

    stats: dict[str, int] = {"OK": 0, "SKIP": 0, "CONFLICT": 0, "DRY": 0, "MISSING_SRC": 0}

    # 按 category 分组打印
    current_category: str = ""
    for op in operations:
        if op.category != current_category:
            current_category = op.category
            print(f"\n  ---- [{current_category}] ----")

        status: str = _execute_move(op, dry_run)

        if status == "SKIP":
            print(f"  [SKIP]    {op.source} -> {op.destination}  (源不存在，optional 跳过)")
        elif status == "CONFLICT":
            print(f"  [CONFLICT]{op.source} -> {op.destination}  (目标已存在，不覆盖)")
        elif status == "MISSING_SRC":
            print(f"  [MISSING] {op.source} -> {op.destination}  (源不存在但非 optional，请检查)")
        elif status == "DRY":
            print(f"  [DRY]     {op.source} -> {op.destination}  (计划移动)")
        else:
            print(f"  [OK]      {op.source} -> {op.destination}")

        stats[status] = stats.get(status, 0) + 1

    return stats


def _print_path_replacement_rules() -> None:
    """打印路径替换规则清单（仅文档化，不执行）。"""
    print("\n" + "=" * 70)
    print("  阶段 3/3：路径替换规则（仅文档化，需人工后续执行）")
    print("=" * 70)
    print("  本脚本不执行路径替换。迁移完成后请按以下规则逐项更新代码与配置：\n")
    for idx, rule in enumerate(PATH_REPLACEMENT_RULES, 1):
        print(f"  [{idx:02d}] 文件: {rule['file']}")
        print(f"       规则: {rule['rule']}")
        print()


def _print_summary(created_count: int, move_stats: dict[str, int], dry_run: bool) -> None:
    """打印迁移汇总。"""
    print("\n" + "=" * 70)
    if dry_run:
        print("  DRY-RUN 汇总（未实际执行）")
    else:
        print("  APPLY 汇总（已实际执行）")
    print("=" * 70)
    print(f"  计划创建目录数: {created_count}")
    print(f"  移动操作总数:   {sum(move_stats.values())}")
    print(f"    - OK (成功):       {move_stats.get('OK', 0)}")
    print(f"    - DRY (计划):      {move_stats.get('DRY', 0)}")
    print(f"    - SKIP (源缺失):   {move_stats.get('SKIP', 0)}")
    print(f"    - CONFLICT (冲突): {move_stats.get('CONFLICT', 0)}")
    print(f"    - MISSING_SRC:     {move_stats.get('MISSING_SRC', 0)}")

    if dry_run:
        print("\n  确认无误后执行: python bin/migrate_layout.py --apply")
    else:
        if move_stats.get("CONFLICT", 0) > 0:
            print("\n  [WARN] 存在目标冲突，请人工排查未覆盖的目录。")
        if move_stats.get("MISSING_SRC", 0) > 0:
            print("\n  [WARN] 存在源缺失但非 optional 的操作，请人工补齐。")
        print("\n  [DONE] 文件移动完成。接下来请按阶段 3 的路径替换规则更新代码与配置。")


def main() -> int:
    """主入口：解析参数并执行迁移。"""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Open-AwA 项目目录重组迁移脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python bin/migrate_layout.py --dry-run    # 输出计划\n"
            "  python bin/migrate_layout.py --apply      # 实际执行\n"
        ),
    )
    mode_group: argparse._MutuallyExclusiveGroup = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="仅输出迁移计划，不实际修改文件",
    )
    mode_group.add_argument(
        "--apply",
        action="store_true",
        help="实际执行迁移（文件移动与目录创建）",
    )
    args: argparse.Namespace = parser.parse_args()

    dry_run: bool = args.dry_run

    print("=" * 70)
    print("  Open-AwA 项目目录重组迁移")
    print(f"  项目根: {PROJECT_ROOT}")
    print(f"  模式:   {'DRY-RUN (仅计划)' if dry_run else 'APPLY (实际执行)'}")
    print("=" * 70)

    # 阶段 1：创建目标目录
    created_count: int = _ensure_directories(dry_run)

    # 阶段 2：移动文件与目录
    move_stats: dict[str, int] = _run_moves(MOVE_OPERATIONS, dry_run)

    # 阶段 3：打印路径替换规则（始终打印，作为人工后续执行清单）
    _print_path_replacement_rules()

    # 汇总
    _print_summary(created_count, move_stats, dry_run)

    return 0


if __name__ == "__main__":
    sys.exit(main())
