"""
最终验证辅助脚本，用于执行关键场景的集成性校验。
阅读时可结合输出日志理解每个验证步骤对应的目标能力与预期结果。
"""

import sys
from unittest.mock import patch
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from billing.models import Base, ModelConfiguration
from billing.pricing_manager import PricingManager

def test_database_uniqueness():
    """
    验证database、uniqueness相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
    print("=== 测试数据库唯一约束 ===\n")

    # 创建内存数据库
    engine = create_engine('sqlite:///:memory:', echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # 使用PRAGMA检查索引
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA index_list('model_configurations')"))
        indexes = list(result)

        print(f"找到 {len(indexes)} 个索引:")
        has_unique_index = False
        for idx in indexes:
            print(f"  - 索引名: {idx[1]}, 唯一: {idx[2]}, 来源: {idx[3]}")
            if idx[1] == 'sqlite_autoindex_model_configurations_1' and idx[2] == 1:
                has_unique_index = True

        if has_unique_index:
            print("\n✓ 发现数据库唯一约束 (sqlite_autoindex)")
        else:
            print("\n✗ 未发现数据库唯一约束")

    # 测试实际的重复插入
    print("\n测试重复插入:")
    try:
        # 插入第一条
        config1 = ModelConfiguration(
            provider="test",
            model="unique",
            is_active=True,
            is_default=True
        )
        session.add(config1)
        session.commit()
        print("✓ 第一次插入成功")

        # 尝试插入重复
        config2 = ModelConfiguration(
            provider="test",
            model="unique",
            is_active=True,
            is_default=False
        )
        session.add(config2)
        session.commit()

        print("✗ 错误: 应该抛出异常")
        session.rollback()
        return False

    except Exception as e:
        print("✓ 数据库正确拒绝重复插入")
        print(f"  异常类型: {type(e).__name__}")
        print(f"  异常信息: {str(e)[:80]}...")
        session.rollback()
        return True
    finally:
        session.close()


def test_code_validation():
    """
    验证code、validation相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
    print("\n=== 测试代码层面验证 ===\n")

    duplicate_configs = [
        {"provider": "openai", "model": "gpt-4", "display_name": "GPT-4", "description": "Original", "is_active": True, "is_default": True, "sort_order": 0},
        {"provider": "openai", "model": "gpt-4", "display_name": "GPT-4 Duplicate", "description": "Duplicate", "is_active": True, "is_default": False, "sort_order": 99},
    ]

    with patch("config.config_loader.config_loader.load_default_configurations", return_value=duplicate_configs):
        # 创建数据库
        engine = create_engine('sqlite:///:memory:', echo=False)
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()

        manager = PricingManager(session)

        try:
            manager.initialize_default_configurations()
            print("✗ 错误: 应该抛出ValueError")
            session.close()
            return False
        except ValueError as e:
            print("✓ 代码正确检测到重复并抛出异常")
            print(f"  异常信息: {str(e)[:100]}...")
            session.close()
            return True


def test_normal_case():
    """
    验证normal、case相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
    print("\n=== 测试正常情况 ===\n")

    # 验证当前配置唯一
    is_unique, dups = PricingManager.validate_default_configurations()
    print(f"✓ DEFAULT_CONFIGURATIONS 唯一性: {'通过' if is_unique else '失败'}")
    if not is_unique:
        print(f"  重复: {dups}")
        return False

    # 创建数据库并初始化
    engine = create_engine('sqlite:///:memory:', echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    manager = PricingManager(session)
    count = manager.initialize_default_configurations()
    print(f"✓ 初始化了 {count} 个配置")

    # 验证无重复
    configs = session.query(ModelConfiguration).all()
    seen = set()
    duplicate_found = False
    for cfg in configs:
        key = (cfg.provider, cfg.model)
        if key in seen:
            print(f"✗ 发现重复: {key}")
            duplicate_found = True
        seen.add(key)

    if not duplicate_found:
        print(f"✓ 所有 {len(configs)} 个配置都是唯一的")

    session.close()
    return not duplicate_found


if __name__ == "__main__":
    print("=" * 60)
    print("唯一性验证测试")
    print("=" * 60 + "\n")

    results = []

    results.append(("数据库唯一约束", test_database_uniqueness()))
    results.append(("代码验证逻辑", test_code_validation()))
    results.append(("正常初始化", test_normal_case()))

    print("\n" + "=" * 60)
    print("测试结果:")
    print("=" * 60)
    for name, passed in results:
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"  {status} - {name}")

    print("\n" + ("所有测试通过!" if all(r[1] for r in results) else "存在问题!"))

    sys.exit(0 if all(r[1] for r in results) else 1)
