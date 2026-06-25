"""
数据迁移脚本：为现有长期记忆添加 memory_layer 字段。
将现有记忆标记为 semantic（语义记忆）层级，并初始化默认衰减配置。
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from db.models import LongTermMemory, MemoryDecayConfig, SessionLocal, engine, Base


def migrate_memory_layers():
    """
    为现有长期记忆添加 memory_layer 字段。
    默认值：semantic（语义记忆层）
    """
    logger.info("[迁移] 开始为现有记忆添加 memory_layer 字段...")

    with SessionLocal() as session:
        # 统计需要迁移的记录数
        total = session.query(LongTermMemory).count()
        # 统计已有 memory_layer 设置的记录数
        migrated = session.query(LongTermMemory).filter(
            LongTermMemory.memory_layer == "semantic"
        ).count()

        if migrated >= total:
            logger.info(f"[迁移] 无需迁移，所有 {total} 条记忆已有 memory_layer 字段")
            return

        # 更新所有未设置 memory_layer 的记录（SQLAlchemy 中默认值为 semantic）
        # 由于 SQLite 不支持 ALTER TABLE ADD COLUMN，使用重建表的方式
        # 但这里我们使用 ORM 方式，直接更新记录
        records = session.query(LongTermMemory).all()
        updated = 0
        for record in records:
            if not record.memory_layer or record.memory_layer == "":
                record.memory_layer = "semantic"
                updated += 1

        session.commit()
        logger.info(f"[迁移] 完成，已更新 {updated} 条记忆的 memory_layer 字段为 'semantic'")


def init_decay_config():
    """
    初始化默认的记忆衰减配置。
    各层默认配置：
    - core: 不衰减
    - episodic: 指数衰减，半衰期30天
    - semantic: 线性衰减，最大90天
    - working: 指数衰减，半衰期1天（会话级）
    """
    logger.info("[迁移] 初始化记忆衰减配置...")

    default_configs = [
        {
            "layer": "core",
            "decay_function": "none",
            "half_life_days": 0,
            "threshold": 0.0,
            "enabled": False,
        },
        {
            "layer": "episodic",
            "decay_function": "exponential",
            "half_life_days": 30,
            "threshold": 0.1,
            "enabled": True,
        },
        {
            "layer": "semantic",
            "decay_function": "linear",
            "half_life_days": 90,
            "threshold": 0.1,
            "enabled": True,
        },
        {
            "layer": "working",
            "decay_function": "exponential",
            "half_life_days": 1,
            "threshold": 0.0,
            "enabled": True,
        },
    ]

    with SessionLocal() as session:
        for config in default_configs:
            existing = session.query(MemoryDecayConfig).filter(
                MemoryDecayConfig.layer == config["layer"]
            ).first()

            if existing:
                logger.info(f"[迁移] 跳过已存在的配置: {config['layer']}")
                continue

            new_config = MemoryDecayConfig(**config)
            session.add(new_config)
            logger.info(f"[迁移] 已添加配置: {config['layer']}")

        session.commit()
        logger.info("[迁移] 衰减配置初始化完成")


def verify_migration():
    """验证迁移结果"""
    logger.info("\n[验证] 检查迁移结果...")

    with SessionLocal() as session:
        total = session.query(LongTermMemory).count()
        with_layer = session.query(LongTermMemory).filter(
            LongTermMemory.memory_layer.isnot(None)
        ).count()

        logger.info(f"[验证] 总记忆数: {total}")
        logger.info(f"[验证] 已有 memory_layer 字段: {with_layer}")

        # 按层级统计
        from sqlalchemy import func
        layer_stats = session.query(
            LongTermMemory.memory_layer,
            func.count(LongTermMemory.id)
        ).group_by(LongTermMemory.memory_layer).all()

        for layer, count in layer_stats:
            logger.info(f"[验证]   {layer}: {count} 条")

        # 检查衰减配置
        config_count = session.query(MemoryDecayConfig).count()
        logger.info(f"[验证] 衰减配置数: {config_count}")


if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Open-AwA 数据迁移: 多层记忆架构")
    logger.info("=" * 50)

    # 确保表存在
    Base.metadata.create_all(bind=engine)

    # 执行迁移
    migrate_memory_layers()
    init_decay_config()

    # 验证
    verify_migration()

    logger.info("\n[完成] 迁移脚本执行完毕")
