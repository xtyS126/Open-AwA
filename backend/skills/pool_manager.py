"""
技能池管理器 — 两层架构的共享技能仓库。
支持技能广播、版本管理和内置技能自动注册。
"""
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from loguru import logger


class SkillPoolManager:
    """
    技能池管理器。
    管理共享技能池中的技能：导入、广播到工作区、更新和删除。
    """

    def __init__(self, pool_dir: Optional[Path] = None):
        self.pool_dir = Path(pool_dir) if pool_dir else Path.home() / ".openawa" / "skill_pool"
        self.pool_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self.pool_dir / "skill.json"

    def get_manifest(self) -> dict:
        """获取技能池清单。"""
        if self._manifest_path.exists():
            return json.loads(self._manifest_path.read_text())
        return {"skills": {}, "version": 1}

    def _save_manifest(self, manifest: dict):
        """保存技能池清单。"""
        self._manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    def list_skills(self) -> list[dict]:
        """列出技能池中的所有技能。"""
        manifest = self.get_manifest()
        skills = []
        for name, info in manifest.get("skills", {}).items():
            skill_dir = self.pool_dir / name
            has_skill_md = (skill_dir / "SKILL.md").exists()
            skills.append({
                "name": name,
                "description": info.get("description", ""),
                "version": info.get("version", "1.0.0"),
                "source": info.get("source", "builtin"),
                "enabled": info.get("enabled", True),
                "has_skill_md": has_skill_md,
                "installed_at": info.get("installed_at", ""),
            })
        return skills

    def has_skill(self, name: str) -> bool:
        """检查技能是否存在。"""
        return (self.pool_dir / name).is_dir()

    def add_builtin_skill(self, name: str, skill_dir: Path) -> bool:
        """
        从内置技能目录添加到技能池。
        """
        if self.has_skill(name):
            return False

        target = self.pool_dir / name
        shutil.copytree(skill_dir, target, dirs_exist_ok=True)

        manifest = self.get_manifest()
        manifest["skills"][name] = {
            "description": f"内置技能: {name}",
            "version": "1.0.0",
            "source": "builtin",
            "enabled": True,
            "installed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_manifest(manifest)

        logger.bind(event="skill_pool_add_builtin", name=name).info("内置技能已添加到技能池")
        return True

    def broadcast_to_workspace(self, skill_name: str, workspace_dir: Path) -> bool:
        """
        将技能池中的技能广播到指定工作区。
        """
        source = self.pool_dir / skill_name
        if not source.is_dir():
            return False

        workspace_skills = workspace_dir / "skills"
        workspace_skills.mkdir(parents=True, exist_ok=True)
        target = workspace_skills / skill_name

        if target.exists():
            logger.bind(event="skill_broadcast_conflict", name=skill_name).warning("目标工作区已存在同名技能")
            return False

        shutil.copytree(source, target)

        # 更新工作区技能清单
        ws_manifest_path = workspace_dir / "skill.json"
        ws_manifest = {}
        if ws_manifest_path.exists():
            ws_manifest = json.loads(ws_manifest_path.read_text())
        ws_manifest.setdefault("skills", {})[skill_name] = {
            "enabled": True,
            "source": "pool",
            "broadcast_at": datetime.now(timezone.utc).isoformat(),
        }
        ws_manifest_path.write_text(json.dumps(ws_manifest, ensure_ascii=False, indent=2))

        logger.bind(event="skill_broadcast", name=skill_name).info("技能已广播到工作区")
        return True

    def remove_skill(self, name: str) -> bool:
        """从技能池中删除技能。"""
        target = self.pool_dir / name
        if not target.is_dir():
            return False

        shutil.rmtree(target)
        manifest = self.get_manifest()
        manifest["skills"].pop(name, None)
        self._save_manifest(manifest)
        return True

    def import_from_url(self, url: str) -> dict:
        """
        从 URL 导入技能到技能池。
        支持 skills.sh、clawhub.ai、github 等来源。
        """
        # 解析 URL 类型
        if "github.com" in url:
            return self._import_from_github(url)
        elif any(d in url for d in ["skills.sh", "clawhub.ai", "skillsmp.com", "lobehub.com"]):
            return self._import_from_marketplace(url)
        else:
            return {"success": False, "error": f"不支持的 URL 来源: {url}"}

    def _import_from_github(self, url: str) -> dict:
        """从 GitHub URL 导入技能。"""
        import subprocess
        import tempfile

        # 从 URL 提取仓库信息
        # 例如: https://github.com/anthropics/skills/tree/main/skills/pdf
        parts = url.replace("https://github.com/", "").split("/")
        if len(parts) < 5 or parts[2] != "tree":
            return {"success": False, "error": "无效的 GitHub URL 格式"}

        owner = parts[0]
        repo = parts[1]
        branch = parts[3]
        subpath = "/".join(parts[4:])

        try:
            with tempfile.TemporaryDirectory() as tmp:
                clone_cmd = [
                    "git", "clone", "--depth=1", f"--branch={branch}",
                    f"https://github.com/{owner}/{repo}.git", tmp,
                ]
                subprocess.run(clone_cmd, capture_output=True, check=True, timeout=60)
                skill_path = Path(tmp) / subpath
                if not skill_path.exists():
                    return {"success": False, "error": f"路径不存在: {subpath}"}

                skill_name = skill_path.name
                target = self.pool_dir / skill_name
                shutil.copytree(skill_path, target, dirs_exist_ok=True)

                manifest = self.get_manifest()
                manifest["skills"][skill_name] = {
                    "description": f"从 GitHub 导入: {owner}/{repo}",
                    "version": "1.0.0",
                    "source": "github",
                    "source_url": url,
                    "installed_at": datetime.now(timezone.utc).isoformat(),
                }
                self._save_manifest(manifest)

                return {"success": True, "name": skill_name, "source": "github"}
        except Exception as e:
            return {"success": False, "error": f"GitHub 导入失败: {str(e)}"}

    def _import_from_marketplace(self, url: str) -> dict:
        """从技能市场 URL 导入技能。"""
        import urllib.request
        import tempfile
        import zipfile

        try:
            with tempfile.TemporaryDirectory() as tmp:
                zip_path = Path(tmp) / "skill.zip"
                urllib.request.urlretrieve(url, str(zip_path))

                with zipfile.ZipFile(zip_path) as zf:
                    # 查找 SKILL.md 确定技能名称
                    skill_name = None
                    for name in zf.namelist():
                        if name.endswith("SKILL.md"):
                            skill_name = Path(name).parent.name or Path(name).stem
                            break
                    if not skill_name:
                        skill_name = Path(url).stem

                    target = self.pool_dir / skill_name
                    zf.extractall(str(target))

                manifest = self.get_manifest()
                manifest["skills"][skill_name] = {
                    "description": f"从市场导入: {url}",
                    "version": "1.0.0",
                    "source": "marketplace",
                    "source_url": url,
                    "installed_at": datetime.now(timezone.utc).isoformat(),
                }
                self._save_manifest(manifest)

                return {"success": True, "name": skill_name, "source": "marketplace"}
        except Exception as e:
            return {"success": False, "error": f"市场导入失败: {str(e)}"}

    def fetch_market_listing(self) -> list[dict]:
        """
        从已配置的技能市场获取可用技能列表。
        返回合并后的技能列表，包含名称/描述/版本/来源/作者等信息。
        """
        import urllib.request
        import json as json_mod

        all_skills: list[dict] = []
        sources = [
            {"name": "clawhub", "url": "https://clawhub.ai/api/skills"},
            {"name": "skills.sh", "url": "https://skills.sh/api/skills"},
        ]

        for src in sources:
            try:
                req = urllib.request.Request(
                    src["url"],
                    headers={"User-Agent": "Open-AwA/1.0", "Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json_mod.loads(resp.read())
                    skills_list = data if isinstance(data, list) else data.get("skills", data.get("data", []))
                    for s in skills_list:
                        all_skills.append({
                            "name": s.get("name", s.get("id", "")),
                            "description": s.get("description", s.get("summary", "")),
                            "version": s.get("version", "1.0.0"),
                            "source": src["name"],
                            "source_url": s.get("url", s.get("source_url", f"https://{src['name']}.ai/skills/{s.get('name', '')}")),
                            "author": s.get("author", s.get("owner", "community")),
                            "downloads": s.get("downloads", s.get("install_count", 0)),
                        })
            except Exception as e:
                logger.bind(event="market_listing_error", source=src["name"]).warning(f"获取市场列表失败: {str(e)}")

        # 合并已安装信息
        manifest = self.get_manifest()
        installed = set(manifest.get("skills", {}).keys())
        for skill in all_skills:
            skill["installed"] = skill["name"] in installed

        return all_skills
