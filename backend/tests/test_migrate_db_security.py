"""
测试数据库迁移脚本的安全性
验证SQL注入防护措施是否有效
"""
import pytest
import sqlite3
import tempfile
import os
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrate_db import (
    MigrationValidator,
    MigrationSecurityError,
    add_column_safely,
    get_existing_columns
)


class TestMigrationValidator:
    """测试MigrationValidator类的安全验证功能"""
    
    def test_validate_table_name_valid(self):
        """测试有效的表名验证"""
        valid_tables = ['skills', 'users', 'plugins', 'experience_memory']
        for table in valid_tables:
            result = MigrationValidator.validate_table_name(table)
            assert result == table
    
    def test_validate_table_name_invalid(self):
        """测试无效的表名应该抛出异常"""
        invalid_tables = [
            'malicious_table',
            'users; DROP TABLE users;--',
            'users UNION SELECT',
            'nonexistent_table'
        ]
        for table in invalid_tables:
            with pytest.raises(MigrationSecurityError) as exc_info:
                MigrationValidator.validate_table_name(table)
            assert "不在允许的白名单中" in str(exc_info.value)
    
    def test_validate_column_name_valid(self):
        """测试有效的列名验证"""
        valid_columns = [
            'category',
            'tags',
            'usage_count',
            'installed_at',
            'author',
            'dependencies',
            'a',
            'column_name_123'
        ]
        for column in valid_columns:
            result = MigrationValidator.validate_column_name(column)
            assert result == column
    
    def test_validate_column_name_invalid(self):
        """测试无效的列名应该抛出异常"""
        invalid_columns = [
            'column; DROP TABLE users;--',
            '1column',
            'column-name',
            'column name',
            'column_name; DELETE',
            '_column',
            'column$name',
            'column\'; DROP',
            ''
        ]
        for column in invalid_columns:
            with pytest.raises(MigrationSecurityError) as exc_info:
                MigrationValidator.validate_column_name(column)
            assert "不符合安全规范" in str(exc_info.value)
    
    def test_validate_column_type_valid(self):
        """测试有效的列类型验证"""
        valid_types = [
            'TEXT',
            'INTEGER',
            'TEXT DEFAULT \'general\'',
            'INTEGER DEFAULT 0',
            'TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
            'VARCHAR(255)',
            'JSON'
        ]
        for col_type in valid_types:
            result = MigrationValidator.validate_column_type(col_type)
            assert result == col_type
    
    def test_validate_column_type_invalid(self):
        """测试包含SQL注入的列类型应该抛出异常"""
        invalid_types = [
            'TEXT; DROP TABLE users;--',
            'INTEGER; DELETE FROM skills',
            'TEXT/**/',
            'TEXT -- comment',
            'EXEC xp_cmdshell',
            'TEXT; INSERT INTO users VALUES',
            'TEXT; UPDATE users SET'
        ]
        for col_type in invalid_types:
            with pytest.raises(MigrationSecurityError) as exc_info:
                MigrationValidator.validate_column_type(col_type)
            assert "不安全" in str(exc_info.value) or "不在允许的白名单中" in str(exc_info.value)
    
    def test_validate_column_type_unknown_base_type(self):
        """测试未知的基础类型应该抛出异常"""
        unknown_types = [
            'CUSTOM_TYPE',
            'BINARY_VARCHAR',
            'UNKNOWN_TYPE DEFAULT 1'
        ]
        for col_type in unknown_types:
            with pytest.raises(MigrationSecurityError) as exc_info:
                MigrationValidator.validate_column_type(col_type)
            assert "不在允许的白名单中" in str(exc_info.value)
    
    def test_validate_migration_success(self):
        """测试完整的迁移验证成功"""
        result = MigrationValidator.validate_migration('category', 'TEXT DEFAULT \'general\'')
        assert result == ('category', 'TEXT DEFAULT \'general\'')
    
    def test_validate_migration_failure_invalid_name(self):
        """测试迁移验证失败 - 无效列名"""
        with pytest.raises(MigrationSecurityError):
            MigrationValidator.validate_migration('1invalid', 'TEXT')
    
    def test_validate_migration_failure_invalid_type(self):
        """测试迁移验证失败 - 无效类型"""
        with pytest.raises(MigrationSecurityError):
            MigrationValidator.validate_migration('valid_name', 'UNKNOWN_TYPE')


class TestSQLInjectionPrevention:
    """测试SQL注入防护"""
    
    @pytest.fixture
    def temp_db(self):
        """创建临时数据库用于测试"""
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE skills (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            )
        ''')
        conn.commit()
        conn.close()
        
        yield path
        
        os.unlink(path)
    
    def test_sql_injection_in_column_name_blocked(self, temp_db):
        """测试列名中的SQL注入被阻止"""
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        
        malicious_column_names = [
            'name; DROP TABLE skills;--',
            'name\'); DROP TABLE skills;--',
            'name UNION SELECT * FROM users'
        ]
        
        for malicious_name in malicious_column_names:
            with pytest.raises(MigrationSecurityError):
                add_column_safely(cursor, 'skills', malicious_name, 'TEXT')
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='skills'")
        result = cursor.fetchone()
        assert result is not None, "skills表应该仍然存在"
        
        conn.close()
    
    def test_sql_injection_in_column_type_blocked(self, temp_db):
        """测试列类型中的SQL注入被阻止"""
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        
        malicious_types = [
            'TEXT; DROP TABLE skills;--',
            'INTEGER; DELETE FROM skills',
            'TEXT\'); DROP TABLE skills;--'
        ]
        
        for malicious_type in malicious_types:
            with pytest.raises(MigrationSecurityError):
                add_column_safely(cursor, 'skills', 'new_column', malicious_type)
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='skills'")
        result = cursor.fetchone()
        assert result is not None, "skills表应该仍然存在"
        
        conn.close()
    
    def test_sql_injection_in_table_name_blocked(self, temp_db):
        """测试表名中的SQL注入被阻止"""
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        
        malicious_table_names = [
            'skills; DROP TABLE skills;--',
            'nonexistent_table',
            'skills UNION SELECT'
        ]
        
        for malicious_table in malicious_table_names:
            with pytest.raises(MigrationSecurityError):
                add_column_safely(cursor, malicious_table, 'new_column', 'TEXT')
        
        conn.close()
    
    def test_valid_migration_succeeds(self, temp_db):
        """测试有效的迁移操作成功"""
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        
        result = add_column_safely(cursor, 'skills', 'category', 'TEXT DEFAULT \'general\'')
        assert result is True
        
        columns = get_existing_columns(cursor, 'skills')
        assert 'category' in columns
        
        result = add_column_safely(cursor, 'skills', 'category', 'TEXT DEFAULT \'general\'')
        assert result is False
        
        conn.close()


class TestEdgeCases:
    """测试边界情况"""
    
    def test_empty_column_name(self):
        """测试空列名"""
        with pytest.raises(MigrationSecurityError):
            MigrationValidator.validate_column_name('')
    
    def test_whitespace_column_name(self):
        """测试空白字符列名"""
        with pytest.raises(MigrationSecurityError):
            MigrationValidator.validate_column_name('   ')
    
    def test_column_name_with_special_chars(self):
        """测试包含特殊字符的列名"""
        special_chars = ['!', '@', '#', '$', '%', '^', '&', '*', '(', ')', '-', '+', '=', '[', ']', '{', '}', '|', '\\', ':', ';', '"', "'", '<', '>', ',', '.', '?', '/', '~', '`']
        for char in special_chars:
            with pytest.raises(MigrationSecurityError):
                MigrationValidator.validate_column_name(f'column{char}name')
    
    def test_column_name_max_length(self):
        """测试超长列名"""
        long_name = 'a' * 1000
        result = MigrationValidator.validate_column_name(long_name)
        assert result == long_name
    
    def test_column_type_case_insensitive(self):
        """测试列类型大小写不敏感"""
        assert MigrationValidator.validate_column_type('text') == 'text'
        assert MigrationValidator.validate_column_type('Text') == 'Text'
        assert MigrationValidator.validate_column_type('TEXT') == 'TEXT'
    
    def test_table_name_case_sensitive(self):
        """测试表名大小写敏感"""
        with pytest.raises(MigrationSecurityError):
            MigrationValidator.validate_table_name('SKILLS')
        with pytest.raises(MigrationSecurityError):
            MigrationValidator.validate_table_name('Skills')


class TestIntegration:
    """集成测试"""
    
    @pytest.fixture
    def temp_db(self):
        """创建临时数据库用于集成测试"""
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE skills (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version TEXT,
                description TEXT,
                config TEXT,
                enabled INTEGER DEFAULT 1
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE experience_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                content TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
        
        yield path
        
        os.unlink(path)
    
    def test_full_migration_workflow(self, temp_db):
        """测试完整的迁移工作流"""
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        
        migrations = [
            ("category", "TEXT DEFAULT 'general'"),
            ("tags", "TEXT"),
            ("dependencies", "TEXT"),
            ("author", "TEXT"),
            ("installed_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("usage_count", "INTEGER DEFAULT 0")
        ]
        
        for column_name, column_type in migrations:
            result = add_column_safely(cursor, 'skills', column_name, column_type)
            assert result is True
        
        columns = get_existing_columns(cursor, 'skills')
        for column_name, _ in migrations:
            assert column_name in columns
        
        conn.commit()
        conn.close()
    
    def test_idempotent_migration(self, temp_db):
        """测试迁移的幂等性"""
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        
        add_column_safely(cursor, 'skills', 'category', 'TEXT DEFAULT \'general\'')
        conn.commit()
        
        result = add_column_safely(cursor, 'skills', 'category', 'TEXT DEFAULT \'general\'')
        assert result is False
        
        columns = get_existing_columns(cursor, 'skills')
        assert columns.count('category') == 1
        
        conn.close()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
