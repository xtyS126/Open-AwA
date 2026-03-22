"""
数据库迁移脚本 - 为所有表添加缺失的列
"""
import sqlite3
import sys
sys.path.insert(0, '.')

def migrate_database():
    print("[工具] 开始完整数据库迁移...")

    db_path = 'openawa.db'

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 1. 检查skills表结构并添加所有缺失的列
        cursor.execute("PRAGMA table_info(skills)")
        columns = [col[1] for col in cursor.fetchall()]
        print(f"当前skills表列: {columns}")

        migrations = [
            ("category", "TEXT DEFAULT 'general'"),
            ("tags", "TEXT"),
            ("dependencies", "TEXT"),
            ("author", "TEXT"),
            ("installed_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("usage_count", "INTEGER DEFAULT 0")
        ]

        for column_name, column_type in migrations:
            if column_name not in columns:
                print(f"[添加] 添加列: {column_name} {column_type}")
                cursor.execute(f"ALTER TABLE skills ADD COLUMN {column_name} {column_type}")
            else:
                print(f"[信息] 列已存在: {column_name}")

        conn.commit()

        # 2. 验证所有表结构
        print("\n[列表] 验证表结构...")

        tables_to_check = [
            'skills',
            'experience_memory',
            'experience_extraction_log'
        ]

        for table in tables_to_check:
            cursor.execute(f"PRAGMA table_info({table})")
            cols = [col[1] for col in cursor.fetchall()]
            print(f"  {table}: {len(cols)} 列")

        conn.close()

        print("\n[成功] 完整数据库迁移完成!")
        print("\n[提示] 现在可以运行初始化脚本:")
        print("   python init_experience_memory.py")

    except Exception as e:
        print(f"\n[失败] 迁移失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    migrate_database()
