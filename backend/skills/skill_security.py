"""
技能安全扫描器 — 在技能安装前执行静态分析。

参考 SkillFortify（2026）的威胁分类体系和 Anthropic Agent Skills 安全最佳实践。
检测 6 大类威胁模式：提示注入、数据外泄、代码执行、文件系统滥用、记忆投毒、依赖劫持。

用法:
    scanner = SkillSecurityScanner()
    result = scanner.scan_skill_package(Path("/path/to/skill"))
    if not result.is_safe:
        for threat in result.threats:
            print(f"[{threat.severity}] {threat.category}: {threat.description}")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


# ---------------------------------------------------------------------------
# 威胁严重度
# ---------------------------------------------------------------------------

class ThreatSeverity(str, Enum):
    CRITICAL = "critical"   # 立即阻止安装
    HIGH = "high"           # 需用户确认
    MEDIUM = "medium"       # 记录警告
    LOW = "low"             # 仅记录


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class Threat:
    """单个安全威胁记录。"""
    category: str
    severity: ThreatSeverity
    description: str
    file_path: str = ""
    line_number: int = 0
    matched_pattern: str = ""


@dataclass
class ScanResult:
    """安全扫描结果。"""
    is_safe: bool
    threats: List[Threat] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    scanned_files: int = 0
    scan_duration_ms: float = 0.0

    @property
    def critical_count(self) -> int:
        return sum(1 for t in self.threats if t.severity == ThreatSeverity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for t in self.threats if t.severity == ThreatSeverity.HIGH)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_safe": self.is_safe,
            "threats": [
                {
                    "category": t.category,
                    "severity": t.severity.value,
                    "description": t.description,
                    "file_path": t.file_path,
                    "line_number": t.line_number,
                }
                for t in self.threats
            ],
            "warnings": self.warnings,
            "scanned_files": self.scanned_files,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
        }


# ---------------------------------------------------------------------------
# 威胁模式库
# ---------------------------------------------------------------------------

# 6 大类威胁模式，参考 SkillFortify + ClawHavoc + Snyk 分析
_THREAT_RULES: List[Dict[str, Any]] = [
    # 1. 提示注入 — 试图覆盖 Agent 系统指令
    {
        "category": "prompt_injection",
        "severity": ThreatSeverity.CRITICAL,
        "patterns": [
            r"ignore\s+(all\s+)?(previous|above|prior)\s+instructions?",
            r"system\s*prompt\s*(override|replacement|hijack)",
            r"you\s+are\s+now\s+(a\s+)?(different|new|another)",
            r"forget\s+(everything|all)\s+(you\s+know|above)",
            r"<system>\s*</system>",
            r"\[system\].*\[/system\]",
            r"override\s+system\s+prompt",
            r"disregard\s+(all\s+)?(previous|above|prior)",
            r"new\s+system\s+prompt\s*:",
        ],
        "description": "检测到可能的提示注入模式，试图覆盖 Agent 系统指令",
    },
    # 2. 数据外泄 — 将敏感数据发送到外部
    {
        "category": "data_exfiltration",
        "severity": ThreatSeverity.CRITICAL,
        "patterns": [
            r"curl\s+.*https?://",
            r"requests\.post\s*\(.*https?://",
            r"httpx\.post\s*\(.*https?://",
            r"send\s*\(.*email",
            r"upload\s*\(.*file",
            r"\.env\b.*(read|send|upload|post)",
            r"secret|password|token.*(send|post|upload)",
            r"exfiltrat",
            r"send.*(credentials?|secret|token|key)",
            r"webhook.*https?://",
        ],
        "description": "检测到可能的数据外泄行为",
    },
    # 3. 代码执行 — 危险的动态代码执行
    {
        "category": "code_execution",
        "severity": ThreatSeverity.HIGH,
        "patterns": [
            r"\bexec\s*\(",
            r"\beval\s*\(",
            r"\bcompile\s*\(",
            r"subprocess\.(call|run|Popen|check_output)",
            r"os\.system\s*\(",
            r"os\.popen\s*\(",
            r"__import__\s*\(",
        ],
        "description": "检测到危险的动态代码执行模式",
    },
    # 4. 文件系统滥用 — 危险的删除/修改操作
    {
        "category": "file_system_abuse",
        "severity": ThreatSeverity.MEDIUM,
        "patterns": [
            r"\brm\s+-rf\b",
            r"shutil\.rmtree",
            r"os\.remove\s*\(",
            r"delete.*(recursive|all|everything)",
            r"\.\./\.\./\.\./",
            r"/etc/(passwd|shadow|sudoers)",
            r"C:\\Windows\\System32",
            r"format\s+[cdefgh]:",
        ],
        "description": "检测到危险的文件系统操作",
    },
    # 5. 记忆投毒 — 写入 Agent 持久记忆文件
    {
        "category": "memory_poisoning",
        "severity": ThreatSeverity.HIGH,
        "patterns": [
            r"\bSOUL\.md\b",
            r"\bMEMORY\.md\b",
            r"\bCLAUDE\.md\b",
            r"write.*memory.*file",
            r"persist.*instruction",
            r"modify.*system.*prompt",
            r"append.*to.*\.md.*memory",
        ],
        "description": "检测到可能的记忆投毒行为，试图修改 Agent 持久记忆",
    },
    # 6. 依赖劫持 — 未经授权的依赖安装
    {
        "category": "dependency_hijack",
        "severity": ThreatSeverity.HIGH,
        "patterns": [
            r"\bpip\s+install\b",
            r"\bnpm\s+install\b",
            r"\bpip3\s+install\b",
            r"\byarn\s+add\b",
            r"\bapt-get\s+install\b",
            r"\bbrew\s+install\b",
            r"post_install\b",
            r"pre_install\b",
        ],
        "description": "检测到未经声明的依赖安装行为",
    },
    # 7. 权限提升
    {
        "category": "privilege_escalation",
        "severity": ThreatSeverity.CRITICAL,
        "patterns": [
            r"\bsudo\b",
            r"\bchmod\s+[0-7]*7[0-7]*7\b",
            r"\bchown\s+root\b",
            r"\bsetuid\b",
            r"\bsetgid\b",
        ],
        "description": "检测到权限提升尝试",
    },
]

# 需要扫描的文件扩展名
_SCANNABLE_EXTENSIONS = frozenset({
    ".md", ".yaml", ".yml", ".py", ".sh", ".bash", ".js", ".ts",
    ".json", ".toml", ".cfg", ".ini", ".txt", ".xml", ".html",
})


# ---------------------------------------------------------------------------
# 扫描器
# ---------------------------------------------------------------------------

class SkillSecurityScanner:
    """
    技能安全扫描器。

    用法:
        scanner = SkillSecurityScanner()
        result = scanner.scan_skill_package(skill_dir)
        if not result.is_safe:
            print(f"发现 {len(result.threats)} 个安全威胁")
    """

    def __init__(self, strict_mode: bool = False):
        """
        Args:
            strict_mode: 若为 True，MEDIUM 级别威胁也会导致 is_safe=False。
                         默认仅 CRITICAL 级别阻止安装。
        """
        self.strict_mode = strict_mode

    def scan_skill_package(self, skill_dir: Path) -> ScanResult:
        """
        扫描技能包中的所有文件。

        Args:
            skill_dir: 技能目录路径。

        Returns:
            ScanResult 包含所有检测到的威胁。
        """
        import time
        start = time.time()
        threats: List[Threat] = []
        warnings: List[str] = []
        scanned_files = 0

        if not skill_dir.is_dir():
            warnings.append(f"技能目录不存在: {skill_dir}")
            return ScanResult(
                is_safe=True, threats=[], warnings=warnings,
                scanned_files=0, scan_duration_ms=0,
            )

        for file_path in skill_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in _SCANNABLE_EXTENSIONS:
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except (OSError, PermissionError):
                warnings.append(f"无法读取文件: {file_path}")
                continue

            scanned_files += 1
            rel_path = str(file_path.relative_to(skill_dir)).replace("\\", "/")
            file_threats = self._scan_content(content, rel_path)
            threats.extend(file_threats)

        # 安全检查：文件名遍历攻击
        for file_path in skill_dir.rglob("*"):
            rel = str(file_path.relative_to(skill_dir))
            if ".." in rel or rel.startswith("/"):
                threats.append(Threat(
                    category="path_traversal",
                    severity=ThreatSeverity.CRITICAL,
                    description=f"路径遍历攻击: {rel}",
                    file_path=rel,
                ))

        # 安全检查：可疑的隐藏文件
        for hidden in skill_dir.rglob(".*"):
            if hidden.is_file() and hidden.name not in (".gitignore", ".gitkeep"):
                threats.append(Threat(
                    category="hidden_file",
                    severity=ThreatSeverity.LOW,
                    description=f"发现隐藏文件: {hidden.name}",
                    file_path=str(hidden.relative_to(skill_dir)),
                ))

        duration = (time.time() - start) * 1000

        # 判断是否安全
        if self.strict_mode:
            is_safe = not any(
                t.severity in (ThreatSeverity.CRITICAL, ThreatSeverity.HIGH, ThreatSeverity.MEDIUM)
                for t in threats
            )
        else:
            is_safe = not any(t.severity == ThreatSeverity.CRITICAL for t in threats)

        logger.bind(
            event="skill_security_scan",
            skill_dir=str(skill_dir),
            is_safe=is_safe,
            threat_count=len(threats),
            scanned_files=scanned_files,
            duration_ms=round(duration, 1),
        ).info("技能安全扫描完成")

        return ScanResult(
            is_safe=is_safe,
            threats=threats,
            warnings=warnings,
            scanned_files=scanned_files,
            scan_duration_ms=round(duration, 1),
        )

    def scan_skill_config(self, config: dict) -> ScanResult:
        """
        扫描技能配置字典中的危险声明。

        检查 permissions 是否声明了高危权限、dependencies 是否可疑等。

        Args:
            config: 技能配置字典。

        Returns:
            ScanResult 包含检测到的配置级威胁。
        """
        threats: List[Threat] = []
        warnings: List[str] = []

        # 检查权限声明
        permissions = config.get("permissions", [])
        if isinstance(permissions, list):
            dangerous_perms = {"system:config", "user:manage", "skill:install", "plugin:install", "command:execute"}
            for perm in permissions:
                if perm in dangerous_perms:
                    threats.append(Threat(
                        category="dangerous_permission",
                        severity=ThreatSeverity.HIGH,
                        description=f"技能声明了高危权限: {perm}",
                    ))

        # 检查依赖声明
        dependencies = config.get("dependencies", [])
        if isinstance(dependencies, list):
            if len(dependencies) > 20:
                warnings.append(f"技能声明了 {len(dependencies)} 个依赖项，建议控制在 20 以内")

            for dep in dependencies:
                if isinstance(dep, str):
                    # 检测可疑的依赖名
                    suspicious = ["hack", "exploit", "backdoor", "steal", "sniff", "inject"]
                    if any(s in dep.lower() for s in suspicious):
                        threats.append(Threat(
                            category="suspicious_dependency",
                            severity=ThreatSeverity.HIGH,
                            description=f"可疑的依赖名称: {dep}",
                        ))

        is_safe = not any(t.severity in (ThreatSeverity.CRITICAL, ThreatSeverity.HIGH) for t in threats)

        return ScanResult(
            is_safe=is_safe,
            threats=threats,
            warnings=warnings,
            scanned_files=0,
        )

    def _scan_content(self, content: str, file_path: str) -> List[Threat]:
        """对文件内容执行所有威胁规则扫描。"""
        threats: List[Threat] = []

        for rule in _THREAT_RULES:
            for pattern in rule["patterns"]:
                try:
                    for match in re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE):
                        line_number = content[:match.start()].count("\n") + 1
                        threats.append(Threat(
                            category=rule["category"],
                            severity=rule["severity"],
                            description=rule["description"],
                            file_path=file_path,
                            line_number=line_number,
                            matched_pattern=match.group(0)[:80],
                        ))
                except re.error:
                    logger.warning(f"威胁规则正则错误: {pattern}")
                    continue

        return threats
