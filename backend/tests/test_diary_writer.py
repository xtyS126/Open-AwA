"""
日记生成系统单元测试。
测试逻辑日计算、PII 脱敏、日记文件读写等核心逻辑。
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# 确保测试环境能够导入 backend 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestLogicalDay:
    """测试逻辑日计算（凌晨4点日界线）"""

    def test_morning_before_4am(self):
        """测试凌晨3点属于前一天"""
        from api.services.diary_writer import get_logical_day

        now = datetime(2026, 5, 16, 3, 0, 0, tzinfo=timezone.utc)
        date_str, range_start, range_end = get_logical_day(now)

        assert date_str == "2026-05-15", "凌晨3点应属于前一天"
        assert range_start.hour == 4, "range_start 应为凌晨4点"
        assert range_end.hour == 4, "range_end 应为凌晨4点"

    def test_after_4am(self):
        """测试凌晨5点属于当天"""
        from api.services.diary_writer import get_logical_day

        now = datetime(2026, 5, 16, 5, 0, 0, tzinfo=timezone.utc)
        date_str, _, _ = get_logical_day(now)

        assert date_str == "2026-05-16", "凌晨5点应属于当天"

    def test_exactly_4am(self):
        """测试凌晨4点整属于当天"""
        from api.services.diary_writer import get_logical_day

        now = datetime(2026, 5, 16, 4, 0, 0, tzinfo=timezone.utc)
        date_str, _, _ = get_logical_day(now)
        assert date_str == "2026-05-16", "凌晨4点整应属于当天"

    def test_noon(self):
        """测试中午12点属于当天"""
        from api.services.diary_writer import get_logical_day

        now = datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc)
        date_str, _, _ = get_logical_day(now)
        assert date_str == "2026-05-16", "中午12点应属于当天"

    def test_midnight(self):
        """测试午夜0点属于前一天"""
        from api.services.diary_writer import get_logical_day

        now = datetime(2026, 5, 16, 0, 0, 0, tzinfo=timezone.utc)
        date_str, _, _ = get_logical_day(now)
        assert date_str == "2026-05-15", "午夜0点应属于前一天"

    def test_range_boundaries(self):
        """测试时间范围的起止点"""
        from api.services.diary_writer import get_logical_day

        now = datetime(2026, 5, 16, 10, 0, 0, tzinfo=timezone.utc)
        _, range_start, range_end = get_logical_day(now)

        # range_start 应为当天凌晨4点
        assert range_start.hour == 4
        assert range_start.minute == 0
        # range_end 应为 range_start + 1 天
        assert (range_end - range_start).days == 1


class TestPII:
    """测试隐私信息脱敏"""

    def test_phone_number_scrubbed(self):
        """测试手机号脱敏"""
        from api.services.diary_writer import scrub_pii

        text = "我的电话是13812345678，请给我打电话"
        result = scrub_pii(text)
        assert "13812345678" not in result, "手机号应被替换"
        assert "[手机号]" in result, "应包含手机号占位符"

    def test_multiple_phone_numbers(self):
        """测试多个手机号脱敏"""
        from api.services.diary_writer import scrub_pii

        text = "联系人A：13800001111，联系人B：13900002222"
        result = scrub_pii(text)
        assert "13800001111" not in result
        assert "13900002222" not in result
        assert result.count("[手机号]") == 2, "两个手机号都应被替换"

    def test_email_scrubbed(self):
        """测试邮箱脱敏"""
        from api.services.diary_writer import scrub_pii

        text = "联系邮箱 test@example.com，备用 admin@test.org"
        result = scrub_pii(text)
        assert "test@example.com" not in result
        assert "admin@test.org" not in result
        assert "[邮箱]" in result

    def test_id_card_scrubbed(self):
        """测试身份证号脱敏"""
        from api.services.diary_writer import scrub_pii

        text = "身份证：110101199001011234"
        result = scrub_pii(text)
        assert "110101199001011234" not in result
        assert "[身份证号]" in result

    def test_bank_card_scrubbed(self):
        """测试银行卡号脱敏"""
        from api.services.diary_writer import scrub_pii

        text = "卡号：6222021234567890123，请查收"
        result = scrub_pii(text)
        assert "6222021234567890123" not in result
        assert "[银行卡号]" in result

    def test_normal_text_preserved(self):
        """测试正常文本不受影响"""
        from api.services.diary_writer import scrub_pii

        text = "今天天气很好，用户说想去看电影。"
        result = scrub_pii(text)
        assert result == text, "正常文本应保持不变"

    def test_empty_string(self):
        """测试空字符串"""
        from api.services.diary_writer import scrub_pii

        result = scrub_pii("")
        assert result == "", "空字符串应返回空字符串"


class TestDiaryFile:
    """测试日记文件操作"""

    def test_save_and_read_diary(self):
        """测试保存和读取日记的完整流程"""
        from api.services.diary_writer import resolve_diary_dir, save_diary, read_diary

        with tempfile.TemporaryDirectory() as tmpdir:
            diary_dir = resolve_diary_dir(tmpdir)
            content = "# 2026-05-16 充实的一天\n\n今天是个好日子。"

            result = save_diary(diary_dir, "2026-05-16", content)
            assert result["logical_date"] == "2026-05-16"
            assert os.path.exists(result["file_path"])

            read_content = read_diary(tmpdir, "2026-05-16")
            assert read_content == content + "\n", "读取内容应与保存一致"

    def test_save_diary_creates_directory(self):
        """测试保存日记时自动创建目录"""
        from api.services.diary_writer import resolve_diary_dir, save_diary

        with tempfile.TemporaryDirectory() as tmpdir:
            diary_dir = resolve_diary_dir(tmpdir)
            assert diary_dir.exists(), "日记目录应自动创建"

    def test_list_diaries(self):
        """测试列出日记"""
        from api.services.diary_writer import list_diaries, resolve_diary_dir, save_diary

        with tempfile.TemporaryDirectory() as tmpdir:
            diary_dir = resolve_diary_dir(tmpdir)
            save_diary(diary_dir, "2026-05-15", "# 昨天")
            save_diary(diary_dir, "2026-05-16", "# 今天")

            diaries = list_diaries(tmpdir)
            assert len(diaries) == 2, "应列出两篇日记"
            # 按修改时间降序，最新的在前
            assert diaries[0]["name"].startswith("2026-05-16")

    def test_list_diaries_empty(self):
        """测试空目录列出日记"""
        from api.services.diary_writer import list_diaries, resolve_diary_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            resolve_diary_dir(tmpdir)
            diaries = list_diaries(tmpdir)
            assert diaries == [], "空目录应返回空列表"

    def test_read_diary_not_found(self):
        """测试读取不存在的日记"""
        from api.services.diary_writer import read_diary, resolve_diary_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            resolve_diary_dir(tmpdir)
            content = read_diary(tmpdir, "2099-01-01")
            assert content is None, "不存在的日记应返回 None"

    def test_diary_filename_with_title(self):
        """测试日记文件名包含标题后缀"""
        from api.services.diary_writer import resolve_diary_dir, save_diary

        with tempfile.TemporaryDirectory() as tmpdir:
            diary_dir = resolve_diary_dir(tmpdir)
            content = "# 2026-05-16：开心的一天\n\n今天发生的事情..."

            result = save_diary(diary_dir, "2026-05-16", content)
            file_name = Path(result["file_path"]).name
            assert "2026-05-16" in file_name
            assert "开心的一天" in file_name, "文件名应包含标题后缀"

    def test_diary_filename_clean_illegal_chars(self):
        """测试文件名清理非法字符"""
        from api.services.diary_writer import resolve_diary_dir, save_diary

        with tempfile.TemporaryDirectory() as tmpdir:
            diary_dir = resolve_diary_dir(tmpdir)
            content = "# 2026-05-16 包含/非法:字符*的?标题"

            result = save_diary(diary_dir, "2026-05-16", content)
            file_name = Path(result["file_path"]).name
            # 非法字符应被移除
            assert "/" not in file_name
            assert ":" not in file_name
            assert "*" not in file_name
            assert "?" not in file_name
            assert "2026-05-16" in file_name


class TestMaterials:
    """测试对话素材收集（需要数据库）"""

    @pytest.mark.skip(reason="需要数据库连接，CI 中通过集成测试覆盖")
    def test_empty_materials(self):
        """测试空素材（无记录时返回空列表）"""
        from api.services.diary_writer import collect_diary_materials
        from db.models import SessionLocal

        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            materials = collect_diary_materials(
                db=db,
                range_start=now - timedelta(hours=1),
                range_end=now + timedelta(hours=1),
            )
            assert materials == [], "无记录时应返回空列表"
        finally:
            db.close()


class TestResolveDiaryDir:
    """测试日记目录解析"""

    def test_creates_default_diary_dir(self):
        """测试默认创建 desk/diary 目录"""
        from api.services.diary_writer import resolve_diary_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            diary_dir = resolve_diary_dir(tmpdir)
            assert diary_dir.exists()
            assert diary_dir.name == "diary"

    def test_prefer_chinese_dir(self):
        """测试优先使用中文「日记」目录"""
        from api.services.diary_writer import resolve_diary_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建中文日记目录
            zh_dir = Path(tmpdir) / "日记"
            zh_dir.mkdir()

            diary_dir = resolve_diary_dir(tmpdir)
            assert diary_dir.name == "日记", "存在中文目录时应优先使用"


class TestGetLogicalDayDefault:
    """测试 get_logical_day 默认参数（使用当前时间）"""

    def test_returns_tuple_of_three(self):
        """测试返回三元组"""
        from api.services.diary_writer import get_logical_day

        result = get_logical_day()
        assert len(result) == 3, "应返回三元组"
        date_str, range_start, range_end = result
        assert isinstance(date_str, str), "日期应为字符串"
        assert isinstance(range_start, datetime), "range_start 应为 datetime"
        assert isinstance(range_end, datetime), "range_end 应为 datetime"
        assert range_end > range_start, "range_end 应大于 range_start"
