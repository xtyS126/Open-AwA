"""
数据库迁移辅助脚本，用于补齐历史库结构并执行兼容性修复。
这类脚本通常面向一次性运维或版本升级场景，维护时需要重点关注幂等性与旧数据兼容性。
"""
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import List, Tuple, Set
from loguru import logger

sys.path.insert(0, '.')


def get_database_file_path() -> str:
    """
    获取数据库文件的绝对路径（不含 sqlite:/// 前缀）。
    优先使用环境变量 DATABASE_URL，否则使用默认路径。
    """
    env_db_url = os.getenv("DATABASE_URL")
    if env_db_url:
        if env_db_url.startswith("sqlite:///"):
            return env_db_url[10:]
        return env_db_url
    
    backend_dir = Path(__file__).parent.resolve()
    return str(backend_dir / "openawa.db")


class MigrationSecurityError(Exception):
    """迁移安全错误，当检测到潜在的SQL注入攻击时抛出"""
    pass


class MigrationValidator:
    """
    迁移验证器，用于验证列名、列类型和表名的安全性
    防止SQL注入攻击
    """
    
    ALLOWED_TABLE_NAMES: Set[str] = {
        'skills',
        'experience_memory',
        'experience_extraction_log',
        'plugins',
        'users',
        'conversation_records',
        'behavior_logs',
        'audit_logs',
        'prompt_configs',
        'short_term_memory',
        'long_term_memory',
        'skill_execution_logs',
        'plugin_execution_logs'
    }
    
    ALLOWED_COLUMN_TYPES: Set[str] = {
        'TEXT',
        'INTEGER',
        'REAL',
        'BLOB',
        'NUMERIC',
        'BOOLEAN',
        'DATE',
        'DATETIME',
        'TIMESTAMP',
        'VARCHAR',
        'JSON'
    }
    
    COLUMN_NAME_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]*$')
    
    @classmethod
    def validate_table_name(cls, table_name: str) -> str:
        """
        验证表名是否在白名单中
        
        参数:
            table_name: 要验证的表名
            
        返回:
            验证通过的表名
            
        抛出:
            MigrationSecurityError: 如果表名不在白名单中
        """
        if table_name not in cls.ALLOWED_TABLE_NAMES:
            raise MigrationSecurityError(
                f"表名 '{table_name}' 不在允许的白名单中。"
                f"允许的表名: {sorted(cls.ALLOWED_TABLE_NAMES)}"
            )
        return table_name
    
    @classmethod
    def validate_column_name(cls, column_name: str) -> str:
        """
        验证列名是否符合安全规范
        列名必须以字母开头，只能包含字母、数字和下划线
        
        参数:
            column_name: 要验证的列名
            
        返回:
            验证通过的列名
            
        抛出:
            MigrationSecurityError: 如果列名不符合规范
        """
        if not cls.COLUMN_NAME_PATTERN.match(column_name):
            raise MigrationSecurityError(
                f"列名 '{column_name}' 不符合安全规范。"
                f"列名必须以字母开头，只能包含字母、数字和下划线"
            )
        return column_name
    
    @classmethod
    def validate_column_type(cls, column_type: str) -> str:
        """
        验证列类型是否在白名单中
        会提取类型的基础部分进行验证，忽略DEFAULT等约束
        
        参数:
            column_type: 要验证的列类型定义
            
        返回:
            验证通过的列类型
            
        抛出:
            MigrationSecurityError: 如果列类型不在白名单中
        """
        base_type = column_type.upper().split()[0]
        base_type = base_type.split('(')[0]
        
        if base_type not in cls.ALLOWED_COLUMN_TYPES:
            raise MigrationSecurityError(
                f"列类型 '{base_type}' 不在允许的白名单中。"
                f"允许的类型: {sorted(cls.ALLOWED_COLUMN_TYPES)}"
            )
        
        if not cls._validate_type_constraints(column_type):
            raise MigrationSecurityError(
                f"列类型定义 '{column_type}' 包含不安全的字符或模式"
            )
        
        return column_type
    
    @classmethod
    def _validate_type_constraints(cls, column_type: str) -> bool:
        """
        验证列类型约束是否安全
        检查DEFAULT值和其他约束是否包含潜在的注入代码
        
        参数:
            column_type: 完整的列类型定义
            
        返回:
            True如果安全，False如果不安全
        """
        dangerous_patterns = [
            r';',
            r'--',
            r'/\*',
            r'\*/',
            r'DROP',
            r'DELETE',
            r'INSERT',
            r'UPDATE',
            r'CREATE',
            r'ALTER',
            r'EXEC',
            r'EXECUTE',
            r'xp_',
            r'sp_',
        ]
        
        type_upper = column_type.upper()
        for pattern in dangerous_patterns:
            if re.search(pattern, type_upper, re.IGNORECASE):
                return False
        
        return True
    
    @classmethod
    def validate_migration(cls, column_name: str, column_type: str) -> Tuple[str, str]:
        """
        验证迁移定义的安全性
        
        参数:
            column_name: 列名
            column_type: 列类型
            
        返回:
            验证通过的(列名, 列类型)元组
        """
        safe_name = cls.validate_column_name(column_name)
        safe_type = cls.validate_column_type(column_type)
        return safe_name, safe_type


def get_existing_columns(cursor: sqlite3.Cursor, table_name: str) -> List[str]:
    """
    获取表中已存在的列名列表
    
    参数:
        cursor: 数据库游标
        table_name: 表名（必须已通过验证）
        
    返回:
        列名列表
    """
    safe_table = MigrationValidator.validate_table_name(table_name)
    cursor.execute(f"PRAGMA table_info({safe_table})")
    return [col[1] for col in cursor.fetchall()]


def add_column_safely(cursor: sqlite3.Cursor, table_name: str, 
                      column_name: str, column_type: str) -> bool:
    """
    安全地添加列到表中
    
    参数:
        cursor: 数据库游标
        table_name: 表名
        column_name: 列名
        column_type: 列类型
        
    返回:
        True如果列被添加，False如果列已存在
    """
    safe_table = MigrationValidator.validate_table_name(table_name)
    safe_name, safe_type = MigrationValidator.validate_migration(column_name, column_type)
    
    existing_columns = get_existing_columns(cursor, safe_table)
    
    if safe_name not in existing_columns:
        logger.info(f"[添加] 添加列: {safe_name} {safe_type}")
        sql = f"ALTER TABLE {safe_table} ADD COLUMN {safe_name} {safe_type}"
        cursor.execute(sql)
        return True
    else:
        logger.info(f"[信息] 列已存在: {safe_name}")
        return False


def migrate_database():
    """
    处理migrate、database相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    logger.info("[工具] 开始完整数据库迁移...")

    db_path = get_database_file_path()
    logger.info(f"[信息] 数据库路径: {db_path}")

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        logger.info("当前skills表列: {}", get_existing_columns(cursor, 'skills'))

        migrations = [
            ("category", "TEXT DEFAULT 'general'"),
            ("tags", "TEXT"),
            ("dependencies", "TEXT"),
            ("author", "TEXT"),
            ("installed_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("usage_count", "INTEGER DEFAULT 0")
        ]

        for column_name, column_type in migrations:
            try:
                add_column_safely(cursor, 'skills', column_name, column_type)
            except MigrationSecurityError as e:
                logger.error(f"[安全错误] 迁移失败: {e}")
                raise

        conn.commit()

        logger.info("")
        logger.info("[列表] 验证表结构...")

        tables_to_check = [
            'skills',
            'experience_memory',
            'experience_extraction_log'
        ]

        for table in tables_to_check:
            try:
                cols = get_existing_columns(cursor, table)
                logger.info(f"  {table}: {len(cols)} 列")
            except MigrationSecurityError as e:
                logger.error(f"[安全错误] 表验证失败: {e}")
                raise

        conn.close()

        logger.info("")
        logger.info("[成功] 完整数据库迁移完成!")
        logger.info("")
        logger.info("[提示] 现在可以运行初始化脚本:")
        logger.info("   python init_experience_memory.py")

    except MigrationSecurityError as e:
        logger.error(f"\n[安全失败] 迁移被阻止: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n[失败] 迁移失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    migrate_database()
