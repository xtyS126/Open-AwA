"""
IP 访问控制模块，管理白名单与黑名单（含 CIDR 网段）。

设计原则：
- IP 白名单优先级最高，命中白名单的请求跳过所有限制
- IP 黑名单次之，命中黑名单的请求直接拒绝
- 默认策略：无任何匹配时放行
"""

import ipaddress
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import IpAccessList


class IpAccessController:
    """
    IP 访问控制器，管理白名单和黑名单。

    白名单优先级高于黑名单：若 IP 同时命中两者，按白名单放行。
    支持单 IP（如 "192.168.1.1"）和 CIDR 网段（如 "10.0.0.0/8"）。
    """

    def __init__(self, db: Session):
        """
        初始化 IP 访问控制器。

        Args:
            db: 数据库会话实例。
        """
        self.db = db

    def add_entry(
        self,
        ip_cidr: str,
        list_type: str,
        reason: str = "",
        created_by: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> IpAccessList:
        """
        添加 IP 到白名单或黑名单。

        Args:
            ip_cidr: IP 地址或 CIDR 网段。
            list_type: "whitelist" 或 "blacklist"。
            reason: 添加原因。
            created_by: 创建者用户 ID。
            expires_at: 过期时间，None 表示永不过期。

        Returns:
            创建的 IpAccessList 实例。

        Raises:
            ValueError: 参数非法或条目已存在。
        """
        ip_cidr = ip_cidr.strip()
        list_type = list_type.strip().lower()

        if list_type not in {"whitelist", "blacklist"}:
            raise ValueError(f"list_type 必须为 whitelist 或 blacklist，实际: {list_type}")

        # 校验 IP/CIDR 格式
        try:
            if "/" in ip_cidr:
                ipaddress.ip_network(ip_cidr, strict=False)
            else:
                ipaddress.ip_address(ip_cidr)
        except ValueError as e:
            raise ValueError(f"IP/CIDR 格式非法: {ip_cidr}") from e

        # 检查是否已存在
        existing = (
            self.db.query(IpAccessList)
            .filter(
                IpAccessList.ip_cidr == ip_cidr,
                IpAccessList.list_type == list_type,
            )
            .first()
        )
        if existing:
            raise ValueError(f"{list_type} 条目已存在: {ip_cidr}")

        entry = IpAccessList(
            ip_cidr=ip_cidr,
            list_type=list_type,
            reason=reason,
            created_by=created_by,
            is_active=True,
            expires_at=expires_at,
        )
        self.db.add(entry)
        try:
            self.db.commit()
        except IntegrityError as e:
            self.db.rollback()
            raise ValueError(f"{list_type} 条目已存在: {ip_cidr}（并发创建冲突）") from e
        self.db.refresh(entry)
        logger.bind(
            event="ip_access_added",
            ip_cidr=ip_cidr,
            list_type=list_type,
        ).info(f"IP 访问条目已添加: {list_type} {ip_cidr}")
        return entry

    def remove_entry(self, entry_id: int) -> bool:
        """
        移除 IP 访问条目。

        Args:
            entry_id: 条目 ID。

        Returns:
            True 表示删除成功。

        Raises:
            ValueError: 条目不存在。
        """
        entry = self.db.query(IpAccessList).filter(IpAccessList.id == entry_id).first()
        if not entry:
            raise ValueError(f"IP 访问条目 {entry_id} 不存在")

        info = f"{entry.list_type} {entry.ip_cidr}"
        self.db.delete(entry)
        self.db.commit()
        logger.bind(event="ip_access_removed", entry_id=entry_id).info(f"IP 访问条目已移除: {info}")
        return True

    def list_entries(
        self,
        list_type: Optional[str] = None,
        active_only: bool = True,
    ) -> list[dict]:
        """
        列出 IP 访问条目。

        Args:
            list_type: 筛选类型（whitelist/blacklist），None 表示全部。
            active_only: 是否仅返回活跃条目。

        Returns:
            条目信息字典列表。
        """
        query = self.db.query(IpAccessList)
        if list_type:
            list_type = list_type.strip().lower()
            query = query.filter(IpAccessList.list_type == list_type)
        if active_only:
            query = query.filter(IpAccessList.is_active.is_(True))

        entries = query.order_by(IpAccessList.created_at.desc()).all()
        return [
            {
                "id": e.id,
                "ip_cidr": e.ip_cidr,
                "list_type": e.list_type,
                "reason": e.reason,
                "created_by": e.created_by,
                "is_active": e.is_active,
                "expires_at": e.expires_at.isoformat() if e.expires_at else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ]

    def check_ip(self, ip_address_str: str) -> dict:
        """
        检查 IP 是否被允许访问。

        白名单优先：命中白名单直接放行，即使同时在黑名单中。
        黑名单次之：命中黑名单拒绝。
        默认策略：无任何匹配时放行。

        Args:
            ip_address_str: 客户端 IP 地址字符串。

        Returns:
            决策字典：
            - allowed: bool 是否允许
            - reason: str 决策原因
            - matched_list: str 命中的列表类型（whitelist/blacklist/none）
        """
        try:
            client_ip = ipaddress.ip_address(ip_address_str)
        except ValueError:
            return {
                "allowed": False,
                "reason": f"IP 地址格式非法: {ip_address_str}",
                "matched_list": "none",
            }

        now = datetime.now(timezone.utc)
        # 获取所有活跃条目
        entries = (
            self.db.query(IpAccessList)
            .filter(IpAccessList.is_active.is_(True))
            .all()
        )

        for entry in entries:
            # 跳过已过期条目
            if entry.expires_at:
                expires_at = entry.expires_at
                # SQLite 存储的 datetime 可能缺少时区信息，统一补齐
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at <= now:
                    continue

            try:
                if "/" in entry.ip_cidr:
                    network = ipaddress.ip_network(entry.ip_cidr, strict=False)
                    if client_ip in network:
                        if entry.list_type == "whitelist":
                            return {
                                "allowed": True,
                                "reason": f"IP 命中白名单: {entry.ip_cidr}",
                                "matched_list": "whitelist",
                            }
                        if entry.list_type == "blacklist":
                            return {
                                "allowed": False,
                                "reason": f"IP 命中黑名单: {entry.ip_cidr}",
                                "matched_list": "blacklist",
                            }
                else:
                    entry_ip = ipaddress.ip_address(entry.ip_cidr)
                    if client_ip == entry_ip:
                        if entry.list_type == "whitelist":
                            return {
                                "allowed": True,
                                "reason": f"IP 命中白名单: {entry.ip_cidr}",
                                "matched_list": "whitelist",
                            }
                        if entry.list_type == "blacklist":
                            return {
                                "allowed": False,
                                "reason": f"IP 命中黑名单: {entry.ip_cidr}",
                                "matched_list": "blacklist",
                            }
            except ValueError:
                # 跳过格式损坏的条目
                continue

        return {
            "allowed": True,
            "reason": "IP 未命中任何列表，默认放行",
            "matched_list": "none",
        }
