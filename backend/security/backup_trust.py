"""
备份信任控制模块 — 文件完整性验证和可信源管理。
支持 SHA-256 哈希验证、可信源公钥固定和备份清单校验。
"""
import hashlib
import json
from pathlib import Path
from typing import Any, Optional
from datetime import datetime, timezone

from loguru import logger


class BackupTrustController:
    """
    备份信任控制器。
    管理备份文件的完整性验证和可信来源的密钥固定。
    """

    def __init__(self, trust_dir: Optional[Path] = None):
        self._trust_dir = Path(trust_dir) if trust_dir else Path.home() / ".openawa" / "trust"
        self._trust_dir.mkdir(parents=True, exist_ok=True)
        self._trusted_sources_path = self._trust_dir / "trusted_sources.json"

    # ---- 文件完整性验证 ----

    @staticmethod
    def compute_file_hash(file_path: str, algorithm: str = "sha256") -> Optional[str]:
        """
        计算文件的哈希值。
        支持 sha256 和 sha512。
        """
        hasher = hashlib.new(algorithm)
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (OSError, ValueError) as e:
            logger.warning(f"文件哈希计算失败 ({file_path}): {str(e)}")
            return None

    def verify_file_integrity(
        self,
        file_path: str,
        expected_hash: str,
        algorithm: str = "sha256",
    ) -> dict:
        """
        验证文件完整性 — 计算文件哈希并与预期值比较。

        Returns:
            {"valid": bool, "computed_hash": str, "expected_hash": str}
        """
        computed = self.compute_file_hash(file_path, algorithm)
        if computed is None:
            return {
                "valid": False,
                "error": f"无法读取文件: {file_path}",
            }

        return {
            "valid": computed.lower() == expected_hash.lower(),
            "computed_hash": computed,
            "expected_hash": expected_hash,
            "algorithm": algorithm,
            "file": file_path,
        }

    # ---- 可信源管理 ----

    def _load_trusted_sources(self) -> dict:
        """加载可信源配置。"""
        if self._trusted_sources_path.exists():
            try:
                return json.loads(self._trusted_sources_path.read_text())
            except json.JSONDecodeError:
                return {"sources": {}}
        return {"sources": {}}

    def _save_trusted_sources(self, data: dict):
        """保存可信源配置。"""
        self._trusted_sources_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2)
        )

    def pin_trusted_source(self, source_name: str, public_key: str) -> dict:
        """
        固定可信源的公钥。

        Args:
            source_name: 来源名称
            public_key: 公钥（Base64 编码）

        Returns:
            操作结果
        """
        data = self._load_trusted_sources()
        data["sources"][source_name] = {
            "public_key": public_key,
            "pinned_at": datetime.now(timezone.utc).isoformat(),
            "last_verified": None,
        }
        self._save_trusted_sources(data)
        logger.bind(event="trusted_source_pinned", source=source_name).info("可信源已固定")
        return {"success": True, "source": source_name}

    def list_trusted_sources(self) -> list[dict]:
        """列出所有可信源。"""
        data = self._load_trusted_sources()
        return [
            {"name": name, **info}
            for name, info in data.get("sources", {}).items()
        ]

    def remove_trusted_source(self, source_name: str) -> bool:
        """移除可信源。"""
        data = self._load_trusted_sources()
        if source_name in data["sources"]:
            del data["sources"][source_name]
            self._save_trusted_sources(data)
            return True
        return False

    def get_trusted_key(self, source_name: str) -> Optional[str]:
        """获取可信源的公钥。"""
        data = self._load_trusted_sources()
        return data.get("sources", {}).get(source_name, {}).get("public_key")

    # ---- 备份签名验证 ----

    @staticmethod
    def verify_manifest(manifest_path: str) -> dict:
        """
        验证备份清单中所有文件的校验和。
        清单格式: {"files": {"path": "hash", ...}, "algorithm": "sha256"}

        Returns:
            {"valid": bool, "results": {"path": "ok"|"modified"|"missing", ...}}
        """
        manifest_file = Path(manifest_path)
        if not manifest_file.exists():
            return {"valid": False, "error": f"清单文件不存在: {manifest_path}"}

        try:
            manifest = json.loads(manifest_file.read_text())
        except json.JSONDecodeError:
            return {"valid": False, "error": "清单文件格式无效"}

        algorithm = manifest.get("algorithm", "sha256")
        base_dir = manifest_file.parent
        files = manifest.get("files", {})
        results = {}

        for rel_path, expected_hash in files.items():
            file_path = base_dir / rel_path
            if not file_path.exists():
                results[rel_path] = "missing"
                continue

            computed = BackupTrustController.compute_file_hash(str(file_path), algorithm)
            if computed and computed.lower() == expected_hash.lower():
                results[rel_path] = "ok"
            else:
                results[rel_path] = "modified"

        all_valid = all(v == "ok" for v in results.values())
        return {
            "valid": all_valid,
            "results": results,
            "total": len(results),
            "ok": sum(1 for v in results.values() if v == "ok"),
            "modified": sum(1 for v in results.values() if v == "modified"),
            "missing": sum(1 for v in results.values() if v == "missing"),
        }
