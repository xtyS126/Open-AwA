#!/usr/bin/env python3
"""综合测试报告生成脚本

汇总后端（pytest）和前端（vitest）的测试数据，
生成 Markdown 格式的综合测试报告。

仅依赖 Python 标准库，无需安装第三方包。

用法示例：
    # 使用默认路径生成报告
    python scripts/generate_test_report.py

    # 指定输出路径和覆盖率报告路径
    python scripts/generate_test_report.py \
        --output docs/reports/test-report-custom.md \
        --backend-cov backend/reports/backend-coverage \
        --frontend-cov frontend/coverage
"""

import argparse
import datetime
import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree


# ============================================================
# 数据模型：测试统计结果
# ============================================================

class TestStatistics:
    """测试统计数据容器"""

    def __init__(self, label: str):
        self.label = label
        self.total: int = 0
        self.passed: int = 0
        self.failed: int = 0
        self.skipped: int = 0
        self.error: int = 0
        self.duration: float = 0.0
        self.coverage_pct: Optional[float] = None
        self.source_available: bool = True

    @property
    def pass_rate(self) -> Optional[float]:
        """通过率"""
        if self.total == 0:
            return None
        return (self.passed / self.total) * 100

    @property
    def status_emoji(self) -> str:
        """根据覆盖率返回状态图标"""
        if self.coverage_pct is None:
            return "⚪"
        if self.coverage_pct >= 80:
            return "🟢"
        elif self.coverage_pct >= 60:
            return "🟡"
        else:
            return "🔴"


# ============================================================
# HTML 解析器：从 coverage.py 报告中提取覆盖率
# ============================================================

class CoveragePyHTMLParser(HTMLParser):
    """解析 coverage.py 生成的 HTML 报告，提取总体覆盖率"""

    def __init__(self):
        super().__init__()
        self.overall_pct: Optional[float] = None
        self._in_footer = False
        self._in_pc_cov = False
        self._title_text = ""

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        attr_dict = dict(attrs)
        cls = attr_dict.get("class", "")

        if tag == "div" and "footer" in cls:
            self._in_footer = True

        if tag == "span" and "pc_cov" in cls:
            self._in_pc_cov = True

    def handle_endtag(self, tag: str):
        if tag == "div":
            self._in_footer = False
        if tag == "span":
            self._in_pc_cov = False

    def handle_data(self, data: str):
        if self._in_pc_cov:
            match = re.search(r"(\d+)%", data.strip())
            if match:
                self.overall_pct = int(match.group(1))


class IstanbulHTMLParser(HTMLParser):
    """解析 Istanbul/NYC（vitest v8）生成的 HTML 覆盖率报告"""

    def __init__(self):
        super().__init__()
        self.overall_pct: Optional[float] = None
        self._current_tag = ""
        self._in_strong = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        self._current_tag = tag
        if tag == "strong":
            self._in_strong = True

    def handle_endtag(self, tag: str):
        self._current_tag = ""
        if tag == "strong":
            self._in_strong = False

    def handle_data(self, data: str):
        stripped = data.strip()
        if self._in_strong and "%" in stripped:
            match = re.search(r"([\d.]+)\s*%", stripped)
            if match:
                pct = float(match.group(1))
                if self.overall_pct is None or pct > self.overall_pct:
                    self.overall_pct = pct


# ============================================================
# 覆盖率数据提取函数
# ============================================================

def extract_coverage_from_html(html_path: Path) -> Optional[float]:
    """从 HTML 覆盖率报告中提取总体覆盖率百分比

    支持 coverage.py 和 Istanbul/NYC 两种 HTML 格式。
    如果无法解析则返回 None。
    """
    if not html_path.exists():
        return None

    try:
        content = html_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    # 策略 1: 通过正则从文本中匹配覆盖率百分比
    # coverage.py 格式: <span class="pc_cov">45%</span>
    cov_match = re.search(r'class="pc_cov"[^>]*>\s*(\d+)\s*%', content)
    if cov_match:
        return int(cov_match.group(1))

    # 策略 2: coverage.py title 格式: Coverage for xxx: 45%
    title_match = re.search(
        r"<title>[^<]*?(\d+)\s*%[^<]*</title>", content, re.IGNORECASE
    )
    if title_match:
        return int(title_match.group(1))

    # 策略 3: Istanbul/NYC 格式
    # <span class="strong">45.2% </span>
    istanbul_match = re.search(
        r'class="strong"[^>]*>\s*([\d.]+)\s*%', content
    )
    if istanbul_match:
        return float(istanbul_match.group(1))

    # 策略 4: 使用 CoveragePyHTMLParser 解析
    parser = CoveragePyHTMLParser()
    try:
        parser.feed(content)
        if parser.overall_pct is not None:
            return parser.overall_pct
    except Exception:
        pass

    # 策略 5: 使用 IstanbulHTMLParser 解析
    parser2 = IstanbulHTMLParser()
    try:
        parser2.feed(content)
        if parser2.overall_pct is not None:
            return parser2.overall_pct
    except Exception:
        pass

    return None


def extract_coverage_from_json(json_path: Path) -> Optional[float]:
    """从 JSON 覆盖率报告中提取总体覆盖率

    支持 coverage.py JSON 和 Istanbul/v8 JSON 两种格式。
    """
    if not json_path.exists():
        return None

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    # coverage.py JSON 格式: {"totals": {"percent_covered": 45.0}}
    if isinstance(data, dict):
        totals = data.get("totals")
        if isinstance(totals, dict):
            pct = totals.get("percent_covered")
            if pct is not None:
                return round(float(pct), 1)

        # Istanbul JSON 格式: {"total": {"lines": {"pct": 45.2}}}
        total = data.get("total")
        if isinstance(total, dict):
            for metric in ("lines", "statements"):
                metric_data = total.get(metric)
                if isinstance(metric_data, dict):
                    pct = metric_data.get("pct")
                    if pct is not None:
                        return round(float(pct), 1)

    return None


def extract_coverage_from_cobertura(xml_path: Path) -> Optional[float]:
    """从 Cobertura XML 覆盖率报告中提取总体行覆盖率"""
    if not xml_path.exists():
        return None

    try:
        tree = ElementTree.parse(str(xml_path))
        root = tree.getroot()
        # 查找 lines-covered / lines-valid
        lines_valid = root.get("lines-valid")
        lines_covered = root.get("lines-covered")
        if lines_valid and lines_covered:
            valid = int(lines_valid)
            covered = int(lines_covered)
            if valid > 0:
                return round((covered / valid) * 100, 1)
    except Exception:
        pass

    return None


def find_coverage_data(coverage_dir: Path) -> Optional[float]:
    """在覆盖率报告目录中查找所有可能的覆盖率数据源"""
    if not coverage_dir.exists() or not coverage_dir.is_dir():
        return None

    # 优先级: JSON > HTML > XML
    json_path = coverage_dir / "coverage.json"
    result = extract_coverage_from_json(json_path)
    if result is not None:
        return result

    html_path = coverage_dir / "index.html"
    result = extract_coverage_from_html(html_path)
    if result is not None:
        return result

    # 尝试 coverage.py 的 coverage.json 文件名
    for fname in coverage_dir.glob("*.json"):
        result = extract_coverage_from_json(fname)
        if result is not None:
            return result

    # 尝试 Cobertura XML
    xml_path = coverage_dir / "cobertura-coverage.xml"
    result = extract_coverage_from_cobertura(xml_path)
    if result is not None:
        return result

    return None


# ============================================================
# 测试文件统计
# ============================================================

def count_test_files(directory: Path, pattern: str) -> List[Path]:
    """统计测试文件数量"""
    if not directory.exists():
        return []
    return sorted(directory.rglob(pattern))


def find_new_test_files(
    repo_root: Path, since_days: int = 30
) -> Tuple[List[str], List[str]]:
    """通过 git 查找近期新增的测试文件

    返回 (backend_new, frontend_new) 两个列表。
    """
    backend_new: List[str] = []
    frontend_new: List[str] = []

    try:
        result = subprocess.run(
            [
                "git", "-C", str(repo_root),
                "log", "--diff-filter=A", "--name-only",
                "--pretty=format:", f"--since={since_days}.days",
                "--", "backend/tests/test_*.py", "frontend/src/__tests__/**/*.test.*",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("backend/tests/"):
                    backend_new.append(line)
                elif line.startswith("frontend/"):
                    frontend_new.append(line)
    except Exception:
        pass

    # 去重
    backend_new = sorted(set(backend_new))
    frontend_new = sorted(set(frontend_new))

    return backend_new, frontend_new


def get_pytest_results(pytest_output_path: Optional[Path]) -> Optional[TestStatistics]:
    """解析 pytest 输出获取测试统计（尝试多种来源）"""
    stats = TestStatistics("后端 (pytest)")
    stats.source_available = False

    # 策略 1: 从 pytest JSON 报告读取
    json_path = Path("backend") / "reports" / "test-results.json"
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            summary = data.get("summary", data)
            stats.total = summary.get("total", 0)
            stats.passed = summary.get("passed", 0)
            stats.failed = summary.get("failed", 0)
            stats.skipped = summary.get("skipped", 0)
            stats.error = summary.get("error", summary.get("errors", 0))
            stats.duration = summary.get("duration", 0)
            stats.source_available = True
            return stats
        except Exception:
            pass

    # 策略 2: 从 coverage.py 的 status.json 读取
    status_path = Path("backend") / "reports" / "backend-coverage" / "status.json"
    if status_path.exists():
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
            stats.source_available = True
            return stats
        except Exception:
            pass

    return stats


# ============================================================
# 报告生成
# ============================================================

def collect_all_stats(
    repo_root: Path,
    backend_cov_path: Optional[Path],
    frontend_cov_path: Optional[Path],
) -> Dict[str, Any]:
    """收集所有测试统计数据"""
    result: Dict[str, Any] = {}

    # --- 后端统计 ---
    backend_stats = TestStatistics("后端 (pytest)")
    backend_tests_dir = repo_root / "backend" / "tests"
    backend_test_files = count_test_files(backend_tests_dir, "test_*.py")
    backend_stats.total = len(backend_test_files)

    # 尝试获取 pytest 实际运行结果
    pytest_results = get_pytest_results(None)
    if pytest_results and pytest_results.source_available:
        backend_stats = pytest_results

    # 后端覆盖率
    if backend_cov_path and backend_cov_path.exists():
        cov = find_coverage_data(backend_cov_path)
        if cov is not None:
            backend_stats.coverage_pct = cov
    else:
        # 尝试默认路径
        default_bc_path = repo_root / "backend" / "reports" / "backend-coverage"
        if default_bc_path.exists():
            cov = find_coverage_data(default_bc_path)
            if cov is not None:
                backend_stats.coverage_pct = cov

    result["backend"] = backend_stats
    result["backend_files"] = backend_test_files

    # --- 前端统计 ---
    frontend_stats = TestStatistics("前端 (vitest)")
    frontend_tests_dir = repo_root / "frontend" / "src" / "__tests__"
    frontend_test_files = count_test_files(frontend_tests_dir, "*.test.*")
    frontend_stats.total = len(frontend_test_files)

    if frontend_cov_path and frontend_cov_path.exists():
        cov = find_coverage_data(frontend_cov_path)
        if cov is not None:
            frontend_stats.coverage_pct = cov
    else:
        # 尝试默认路径
        default_fc_path = repo_root / "frontend" / "coverage"
        if default_fc_path.exists():
            cov = find_coverage_data(default_fc_path)
            if cov is not None:
                frontend_stats.coverage_pct = cov

    result["frontend"] = frontend_stats
    result["frontend_files"] = frontend_test_files

    # --- E2E 测试统计 ---
    e2e_tests_dir = repo_root / "frontend" / "tests" / "e2e"
    e2e_files = count_test_files(e2e_tests_dir, "*.ts")
    result["e2e"] = {"file_count": len(e2e_files), "files": e2e_files}

    # --- 技能测试统计 ---
    skill_tests_dir = repo_root / "backend" / "skills" / "external" / "api-testing" / "tests"
    skill_files = count_test_files(skill_tests_dir, "test_*.py")
    result["skills"] = {"file_count": len(skill_files), "files": skill_files}

    # --- 新增测试文件（由调用方注入） ---
    result["new_backend"] = []
    result["new_frontend"] = []
    result["new_total"] = 0

    return result


def format_coverage_bar(pct: Optional[float], width: int = 20) -> str:
    """生成覆盖率进度条"""
    if pct is None:
        return "░" * width + " 数据不可用"
    filled = int(round(pct / 100 * width))
    empty = width - filled
    return ("█" * filled) + ("░" * empty) + f" {pct:.1f}%"


def format_coverage_status(pct: Optional[float]) -> str:
    """格式化覆盖率状态"""
    if pct is None:
        return "⚠️ 数据不可用"
    if pct >= 80:
        return f"🟢 优秀 ({pct:.1f}%)"
    elif pct >= 60:
        return f"🟡 良好 ({pct:.1f}%)"
    elif pct >= 40:
        return f"🟠 需改进 ({pct:.1f}%)"
    else:
        return f"🔴 不足 ({pct:.1f}%)"


def generate_markdown_report(
    stats: Dict[str, Any],
    repo_root: Path,
    output_path: Path,
) -> str:
    """生成 Markdown 格式的综合测试报告"""
    now = datetime.datetime.now()
    report_date = now.strftime("%Y-%m-%d")
    report_time = now.strftime("%Y-%m-%d %H:%M:%S")

    backend: TestStatistics = stats["backend"]
    frontend: TestStatistics = stats["frontend"]
    backend_files: List[Path] = stats["backend_files"]
    frontend_files: List[Path] = stats["frontend_files"]
    e2e_info: Dict = stats["e2e"]
    skills_info: Dict = stats["skills"]
    new_backend: List[str] = stats["new_backend"]
    new_frontend: List[str] = stats["new_frontend"]
    new_total: int = stats["new_total"]

    lines: List[str] = []

    # ==================== 标题与元信息 ====================
    lines.append(f"# 综合测试报告")
    lines.append("")
    lines.append(f"**生成时间**：{report_time}")
    lines.append(f"**报告周期**：{report_date}")
    lines.append(f"**项目**：Open-AwA")
    lines.append("")

    # ==================== 1. 执行摘要 ====================
    lines.append("---")
    lines.append("")
    lines.append("## 📋 执行摘要")
    lines.append("")

    total_test_files = (
        len(backend_files)
        + len(frontend_files)
        + e2e_info["file_count"]
        + skills_info["file_count"]
    )

    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|-----|")
    lines.append(f"| 测试文件总数 | {total_test_files} |")
    lines.append(f"| 后端测试文件 | {len(backend_files)} |")
    lines.append(f"| 前端测试文件 | {len(frontend_files)} |")
    lines.append(f"| E2E 测试文件 | {e2e_info['file_count']} |")
    lines.append(f"| 技能测试文件 | {skills_info['file_count']} |")
    lines.append(f"| 后端覆盖率 | {format_coverage_status(backend.coverage_pct)} |")
    lines.append(f"| 前端覆盖率 | {format_coverage_status(frontend.coverage_pct)} |")
    if new_total > 0:
        lines.append(f"| 近期新增测试 | {new_total} 个文件 |")
    lines.append("")

    # ==================== 2. 各层级测试统计 ====================
    lines.append("---")
    lines.append("")
    lines.append("## 📊 各层级测试统计")
    lines.append("")

    lines.append("### 2.1 后端测试 (pytest)")
    lines.append("")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|-----|")
    lines.append(f"| 测试文件数 | {len(backend_files)} |")
    lines.append(f"| 覆盖率 | {format_coverage_bar(backend.coverage_pct)} |")
    lines.append("")

    # 后端测试文件分类
    backend_modules = categorize_backend_tests(backend_files)
    if backend_modules:
        lines.append("**后端测试模块分布**：")
        lines.append("")
        lines.append(f"| 模块 | 测试文件数 |")
        lines.append(f"|------|-----------|")
        for module, files in sorted(backend_modules.items(), key=lambda x: -len(x[1])):
            lines.append(f"| {module} | {len(files)} |")
        lines.append("")

    lines.append("### 2.2 前端测试 (vitest)")
    lines.append("")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|-----|")
    lines.append(f"| 测试文件数 | {len(frontend_files)} |")
    lines.append(f"| 覆盖率 | {format_coverage_bar(frontend.coverage_pct)} |")
    lines.append("")

    # 前端测试文件分类
    frontend_modules = categorize_frontend_tests(frontend_files)
    if frontend_modules:
        lines.append("**前端测试模块分布**：")
        lines.append("")
        lines.append(f"| 模块 | 测试文件数 |")
        lines.append(f"|------|-----------|")
        for module, files in sorted(frontend_modules.items(), key=lambda x: -len(x[1])):
            lines.append(f"| {module} | {len(files)} |")
        lines.append("")

    lines.append("### 2.3 E2E 测试 (Playwright)")
    lines.append("")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|-----|")
    lines.append(f"| 测试文件数 | {e2e_info['file_count']} |")
    if e2e_info["files"]:
        for f in e2e_info["files"]:
            lines.append(f"| - {f.name} | |")
    lines.append("")

    lines.append("### 2.4 技能测试")
    lines.append("")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|-----|")
    lines.append(f"| 测试文件数 | {skills_info['file_count']} |")
    if skills_info["files"]:
        for f in skills_info["files"]:
            lines.append(f"| - {f.name} | |")
    lines.append("")

    # ==================== 3. 测试资产清单 ====================
    lines.append("---")
    lines.append("")
    lines.append("## 📦 测试资产清单")
    lines.append("")

    lines.append("### 3.1 后端测试文件列表")
    lines.append("")
    lines.append('<details>')
    lines.append('<summary>展开查看全部 {0} 个后端测试文件</summary>'.format(len(backend_files)))
    lines.append("")
    for f in backend_files:
        rel_path = f.relative_to(repo_root)
        lines.append(f"- `{rel_path}`")
    lines.append("")
    lines.append('</details>')
    lines.append("")

    lines.append("### 3.2 前端测试文件列表")
    lines.append("")
    lines.append('<details>')
    lines.append('<summary>展开查看全部 {0} 个前端测试文件</summary>'.format(len(frontend_files)))
    lines.append("")
    for f in frontend_files:
        rel_path = f.relative_to(repo_root)
        lines.append(f"- `{rel_path}`")
    lines.append("")
    lines.append('</details>')
    lines.append("")

    # ==================== 4. 近期新增测试文件 ====================
    lines.append("---")
    lines.append("")
    lines.append("## 🆕 近期新增测试文件（30 天内）")
    lines.append("")

    if new_total == 0:
        lines.append("> 近 30 天内无新增测试文件。")
        lines.append("")
    else:
        lines.append(f"共新增 **{new_total}** 个测试文件：")
        lines.append("")
        if new_backend:
            lines.append("**后端新增**：")
            for f in new_backend:
                lines.append(f"- `{f}`")
            lines.append("")
        if new_frontend:
            lines.append("**前端新增**：")
            for f in new_frontend:
                lines.append(f"- `{f}`")
            lines.append("")

    # ==================== 5. 覆盖率详情 ====================
    lines.append("---")
    lines.append("")
    lines.append("## 📈 覆盖率详情")
    lines.append("")

    lines.append("### 5.1 后端覆盖率")
    lines.append("")
    if backend.coverage_pct is not None:
        lines.append(f"- **语句覆盖率**：{backend.coverage_pct:.1f}%")
        lines.append(f"- **覆盖报告路径**：`backend/reports/backend-coverage/index.html`")
    else:
        lines.append("> ⚠️ 覆盖率数据不可用。请运行 `pytest --cov=. --cov-report=html:reports/backend-coverage` 生成覆盖率报告。")
    lines.append("")

    lines.append("### 5.2 前端覆盖率")
    lines.append("")
    if frontend.coverage_pct is not None:
        lines.append(f"- **语句覆盖率**：{frontend.coverage_pct:.1f}%")
        lines.append(f"- **覆盖报告路径**：`frontend/coverage/index.html`")
    else:
        lines.append("> ⚠️ 覆盖率数据不可用。请运行 `npx vitest run --coverage` 生成覆盖率报告。")
    lines.append("")

    # ==================== 6. 质量检查结果 ====================
    lines.append("---")
    lines.append("")
    lines.append("## ✅ 代码质量检查")
    lines.append("")

    coverage_threshold_pass = True
    if backend.coverage_pct is not None and backend.coverage_pct < 16:
        coverage_threshold_pass = False
    if frontend.coverage_pct is not None and frontend.coverage_pct < 90:
        coverage_threshold_pass = False

    lines.append("| 检查项 | 状态 | 说明 |")
    lines.append("|--------|------|------|")
    lines.append(
        f"| 后端 mypy 零错误 | ⬜ 待检查 | 运行 `mypy backend/ --ignore-missing-imports` |"
    )
    lines.append(
        f"| 后端 bandit 安全扫描 | ⬜ 待检查 | 运行 `bandit -r backend/` |"
    )
    lines.append(
        f"| 前端 TypeScript 零错误 | ⬜ 待检查 | 运行 `npx tsc --noEmit` |"
    )
    lines.append(
        f"| 前端 ESLint 零错误 | ⬜ 待检查 | 运行 `npx eslint src/` |"
    )
    lines.append(
        f"| 前端构建成功 | ⬜ 待检查 | 运行 `npm run build` |"
    )
    lines.append(
        f"| 安全依赖审计 | ⬜ 待检查 | 运行 `pip-audit` / `npm audit` |"
    )
    if coverage_threshold_pass:
        lines.append(f"| 覆盖率阈值检查 | ✅ 通过 | 满足最低覆盖率要求 |")
    else:
        lines.append(f"| 覆盖率阈值检查 | ❌ 未通过 | 低于覆盖率门禁阈值 |")
    lines.append("")

    # ==================== 7. 遗留问题 ====================
    lines.append("---")
    lines.append("")
    lines.append("## ⚠️ 遗留问题")
    lines.append("")

    issues = []
    if backend.coverage_pct is None:
        issues.append("- 后端覆盖率报告未生成，无法评估覆盖率水平")
    if frontend.coverage_pct is None:
        issues.append("- 前端覆盖率报告未生成，无法评估覆盖率水平")
    if not issues:
        # 检查覆盖率阈值
        if backend.coverage_pct is not None and backend.coverage_pct < 80:
            issues.append(f"- 后端覆盖率仅 {backend.coverage_pct:.1f}%，低于推荐水平（80%）")
        if frontend.coverage_pct is not None and frontend.coverage_pct < 90:
            issues.append(
                f"- 前端覆盖率仅 {frontend.coverage_pct:.1f}%，低于 vitest 阈值（90%）"
            )

    if issues:
        for issue in issues:
            lines.append(issue)
    else:
        lines.append("> 暂无遗留问题记录。")
    lines.append("")

    # ==================== 8. 报告说明 ====================
    lines.append("---")
    lines.append("")
    lines.append("## 📝 报告说明")
    lines.append("")
    lines.append("- 本报告由 `scripts/generate_test_report.py` 自动生成")
    lines.append(f"- 报告生成时间：{report_time}")
    lines.append("- 覆盖率数据来源：")
    lines.append("  - 后端：`pytest --cov` 的 HTML 报告（coverage.py）")
    lines.append("  - 前端：`vitest --coverage` 的 HTML/JSON 报告（v8/istanbul）")
    lines.append("- 测试文件统计：基于文件系统扫描（`test_*.py` 和 `*.test.*`）")
    lines.append("- 新增文件检测：使用 `git log --diff-filter=A --since=30.days`")
    lines.append("")

    return "\n".join(lines)


def categorize_backend_tests(files: List[Path]) -> Dict[str, List[Path]]:
    """将后端测试文件按模块分类"""
    modules: Dict[str, List[Path]] = {}
    for f in files:
        name = f.stem  # 去掉 test_ 前缀和 .py 后缀
        if name.startswith("test_"):
            name = name[5:]  # 移除 test_ 前缀

        # 按关键词归类
        module = "其他"
        if "plugin" in name or "hot_update" in name or "extension_protocol" in name:
            module = "插件系统"
        elif "billing" in name or "budget" in name or "pricing" in name or "tokenizer" in name:
            module = "计费系统"
        elif "task_runtime" in name:
            module = "任务运行时"
        elif "memory" in name or "vector_store" in name or "experience" in name:
            module = "记忆/经验"
        elif "security" in name or "permission" in name or "rbac" in name or "sandbox" in name or "config_security" in name or "migrate_db" in name:
            module = "安全"
        elif "weixin" in name or "wechat" in name:
            module = "微信"
        elif "conversation" in name or "chat" in name:
            module = "对话/Chat"
        elif "agent" in name or "planner" in name or "comprehension" in name or "executor" in name or "behavior" in name:
            module = "Agent 核心"
        elif "api" in name or "route" in name or "main_startup" in name or "provider" in name or "litellm" in name:
            module = "API/路由"
        elif "local_search" in name or "local_users" in name:
            module = "本地服务"
        elif "db" in name or "logging" in name or "settings" in name:
            module = "基础设施"
        elif "workflow" in name:
            module = "工作流"
        elif "skill" in name:
            module = "技能系统"
        elif "twitter" in name:
            module = "第三方集成"
        elif "user" in name:
            module = "用户"

        modules.setdefault(module, []).append(f)

    return modules


def categorize_frontend_tests(files: List[Path]) -> Dict[str, List[Path]]:
    """将前端测试文件按功能模块分类"""
    modules: Dict[str, List[Path]] = {}
    for f in files:
        # 用路径来分类（统一使用正斜杠）
        path_str = str(f).replace("\\", "/")
        module = "其他"

        if "features/chat/" in path_str:
            module = "聊天 (Chat)"
        elif "features/billing/" in path_str:
            module = "计费 (Billing)"
        elif "features/plugins/" in path_str:
            module = "插件 (Plugins)"
        elif "features/settings/" in path_str:
            module = "设置 (Settings)"
        elif "features/skills/" in path_str:
            module = "技能 (Skills)"
        elif "features/experiences/" in path_str:
            module = "经验 (Experiences)"
        elif "features/memory/" in path_str:
            module = "记忆 (Memory)"
        elif "features/dashboard/" in path_str:
            module = "仪表盘 (Dashboard)"
        elif "shared/api/" in path_str:
            module = "共享 API"
        elif "shared/store/" in path_str:
            module = "共享 Store"
        elif "shared/components/" in path_str:
            module = "共享组件"
        elif "shared/utils/" in path_str:
            module = "共享工具"
        elif "shared/types/" in path_str:
            module = "共享类型"
        elif "/__tests__/" in path_str and "features/" not in path_str and "shared/" not in path_str:
            module = "页面/根组件"

        modules.setdefault(module, []).append(f)

    return modules


# ============================================================
# 辅助函数
# ============================================================

def safe_print(message: str) -> None:
    """安全的 print 函数，Windows GBK 编码下替换无法编码的字符"""
    try:
        print(message)
    except UnicodeEncodeError:
        # 回退：输出时替换无法编码的字符
        encoding = sys.stdout.encoding or "utf-8"
        print(message.encode(encoding, errors="replace").decode(encoding, errors="replace"))


# ============================================================
# 命令行入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="生成 Open-AwA 项目综合测试报告（Markdown 格式）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  %(prog)s
  %(prog)s --output docs/reports/test-report-custom.md
  %(prog)s --backend-cov backend/reports/backend-coverage --frontend-cov frontend/coverage
  %(prog)s --backend-cov "" --frontend-cov ""   # 跳过覆盖率数据
        """.strip(),
    )

    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出文件路径（默认：docs/reports/test-report-{date}.md）",
    )
    parser.add_argument(
        "--backend-cov",
        type=str,
        default=None,
        help="后端覆盖率报告目录路径（默认：backend/reports/backend-coverage）",
    )
    parser.add_argument(
        "--frontend-cov",
        type=str,
        default=None,
        help="前端覆盖率报告目录路径（默认：frontend/coverage）",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=30,
        help="查找新增测试文件的天数范围（默认：30）",
    )
    parser.add_argument(
        "--no-new-files",
        action="store_true",
        help="跳过新增文件检测（在网络受限环境加速运行）",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="将报告直接输出到标准输出（不写入文件）",
    )

    args = parser.parse_args()

    # 确定仓库根目录
    repo_root = Path(__file__).resolve().parent.parent

    # 确定覆盖率报告路径
    backend_cov_path: Optional[Path] = None
    if args.backend_cov is not None:
        # 显式指定了路径（即使为空字符串也视为"跳过"）
        if args.backend_cov.strip():
            bc = Path(args.backend_cov)
            if not bc.is_absolute():
                bc = repo_root / bc
            backend_cov_path = bc
        # 空字符串 -> 跳过
    else:
        # 未指定，使用默认路径（仅在存在时）
        default_bc = repo_root / "backend" / "reports" / "backend-coverage"
        if default_bc.exists():
            backend_cov_path = default_bc

    frontend_cov_path: Optional[Path] = None
    if args.frontend_cov is not None:
        if args.frontend_cov.strip():
            fc = Path(args.frontend_cov)
            if not fc.is_absolute():
                fc = repo_root / fc
            frontend_cov_path = fc
    else:
        default_fc = repo_root / "frontend" / "coverage"
        if default_fc.exists():
            frontend_cov_path = default_fc

    # 确定输出路径
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = repo_root / output_path
    else:
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        report_dir = repo_root / "docs" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        output_path = report_dir / f"test-report-{date_str}.md"

    # 收集统计数据
    safe_print(f"[INFO] 正在收集测试数据...")
    safe_print(f"  后端覆盖率路径: {backend_cov_path if backend_cov_path else '未指定（自动检测）'}")
    safe_print(f"  前端覆盖率路径: {frontend_cov_path if frontend_cov_path else '未指定（自动检测）'}")

    stats = collect_all_stats(repo_root, backend_cov_path, frontend_cov_path)

    # 新增测试文件检测（可通过 --no-new-files 跳过）
    if not args.no_new_files:
        safe_print(f"[INFO] 正在检测近期新增测试文件（{args.since_days} 天内）...")
        backend_new, frontend_new = find_new_test_files(repo_root, args.since_days)
        stats["new_backend"] = backend_new
        stats["new_frontend"] = frontend_new
        stats["new_total"] = len(backend_new) + len(frontend_new)
    else:
        safe_print("[INFO] 已跳过新增文件检测")

    # 生成 Markdown 报告
    safe_print(f"[INFO] 正在生成测试报告...")
    markdown_content = generate_markdown_report(stats, repo_root, output_path)

    # 输出
    if args.stdout:
        # Windows 控制台可能使用 GBK 编码，需要容错输出
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        try:
            print(markdown_content)
        except UnicodeEncodeError:
            # 回退：输出时替换无法编码的字符
            print(markdown_content.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8", errors="replace"))
    else:
        output_path.write_text(markdown_content, encoding="utf-8")
        safe_print(f"[OK] 测试报告已生成：{output_path}")

        # 打印摘要
        backend: TestStatistics = stats["backend"]
        frontend: TestStatistics = stats["frontend"]
        e2e_info = stats["e2e"]
        skills_info = stats["skills"]
        new_total = stats["new_total"]

        total_files = (
            len(stats["backend_files"])
            + len(stats["frontend_files"])
            + e2e_info["file_count"]
            + skills_info["file_count"]
        )
        safe_print(f"\n  报告摘要：")
        safe_print(f"    测试文件总数：{total_files}")
        safe_print(f"    后端：{len(stats['backend_files'])} | 前端：{len(stats['frontend_files'])}")
        safe_print(f"    E2E：{e2e_info['file_count']} | 技能：{skills_info['file_count']}")
        safe_print(f"    后端覆盖率：{format_coverage_status(backend.coverage_pct)}")
        safe_print(f"    前端覆盖率：{format_coverage_status(frontend.coverage_pct)}")
        if new_total > 0:
            safe_print(f"    近期新增测试：{new_total} 个文件")


if __name__ == "__main__":
    main()
