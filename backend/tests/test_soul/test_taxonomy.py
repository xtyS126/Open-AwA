"""
分类词表单元测试。
"""

import pytest
from soul.taxonomy import (
    INTEREST_CATEGORIES,
    ROLE_CATEGORIES,
    VALUE_CATEGORIES,
    COGNITIVE_STYLES,
    MBTI_DESCRIPTIONS,
    get_all_categories,
    get_category_keywords,
)


class TestTaxonomyConstants:
    """分类词表常量测试套件。"""

    def test_interest_categories_not_empty(self):
        """测试兴趣分类词表不为空"""
        assert len(INTEREST_CATEGORIES) > 0
        assert "技术" in INTEREST_CATEGORIES
        assert "艺术" in INTEREST_CATEGORIES
        assert "游戏" in INTEREST_CATEGORIES

    def test_interest_categories_contain_keywords(self):
        """测试兴趣分类包含关键词列表"""
        for category, keywords in INTEREST_CATEGORIES.items():
            assert isinstance(keywords, list)
            assert len(keywords) > 0
            for kw in keywords:
                assert isinstance(kw, str)

    def test_role_categories_not_empty(self):
        """测试角色分类词表不为空"""
        assert len(ROLE_CATEGORIES) > 0
        assert "开发者" in ROLE_CATEGORIES
        assert "学生" in ROLE_CATEGORIES

    def test_value_categories_not_empty(self):
        """测试价值分类词表不为空"""
        assert len(VALUE_CATEGORIES) > 0
        assert "效率" in VALUE_CATEGORIES
        assert "成长" in VALUE_CATEGORIES

    def test_cognitive_styles_not_empty(self):
        """测试认知风格词表不为空"""
        assert len(COGNITIVE_STYLES) > 0
        assert "analytical" in COGNITIVE_STYLES
        assert "creative" in COGNITIVE_STYLES
        assert "practical" in COGNITIVE_STYLES

    def test_cognitive_styles_have_descriptions(self):
        """测试认知风格包含描述"""
        for style, description in COGNITIVE_STYLES.items():
            assert isinstance(description, str)
            assert len(description) > 0

    def test_mbti_descriptions_not_empty(self):
        """测试 MBTI 词表不为空"""
        assert len(MBTI_DESCRIPTIONS) > 0
        assert "INTJ" in MBTI_DESCRIPTIONS
        assert "INTP" in MBTI_DESCRIPTIONS
        assert "ENTJ" in MBTI_DESCRIPTIONS

    def test_mbti_descriptions_have_16_types(self):
        """测试 MBTI 有16种类型"""
        assert len(MBTI_DESCRIPTIONS) == 16

    def test_mbti_descriptions_contain_chinese(self):
        """测试 MBTI 描述包含中文"""
        for mbti_type, description in MBTI_DESCRIPTIONS.items():
            assert isinstance(description, str)
            assert len(description) > 0


class TestGetAllCategories:
    """get_all_categories 函数测试套件。"""

    def test_get_all_categories_returns_dict(self):
        """测试返回字典格式"""
        result = get_all_categories()
        assert isinstance(result, dict)
        assert "interests" in result
        assert "roles" in result
        assert "values" in result
        assert "cognitive_styles" in result
        assert "mbti" in result

    def test_get_all_categories_contains_original_data(self):
        """测试包含原始数据"""
        result = get_all_categories()
        assert result["interests"] == INTEREST_CATEGORIES
        assert result["roles"] == ROLE_CATEGORIES
        assert result["values"] == VALUE_CATEGORIES
        assert result["cognitive_styles"] == COGNITIVE_STYLES
        assert result["mbti"] == MBTI_DESCRIPTIONS


class TestGetCategoryKeywords:
    """get_category_keywords 函数测试套件。"""

    def test_get_category_keywords_interests(self):
        """测试获取兴趣分类关键词"""
        keywords = get_category_keywords("interests", "技术")
        assert isinstance(keywords, list)
        assert "编程" in keywords
        assert "人工智能" in keywords

    def test_get_category_keywords_roles(self):
        """测试获取角色分类关键词"""
        keywords = get_category_keywords("roles", "开发者")
        assert isinstance(keywords, list)
        assert "前端开发" in keywords
        assert "后端开发" in keywords

    def test_get_category_keywords_values(self):
        """测试获取价值分类关键词"""
        keywords = get_category_keywords("values", "效率")
        assert isinstance(keywords, list)
        assert len(keywords) > 0

    def test_get_category_keywords_mbti(self):
        """测试获取 MBTI 描述"""
        keywords = get_category_keywords("mbti", "INTJ")
        assert isinstance(keywords, list)
        assert len(keywords) == 1
        assert "建筑师" in keywords[0]

    def test_get_category_keywords_cognitive_styles(self):
        """测试获取认知风格描述"""
        keywords = get_category_keywords("cognitive_styles", "analytical")
        assert isinstance(keywords, list)
        assert len(keywords) == 1
        assert "分析型" in keywords[0]

    def test_get_category_keywords_unknown_category_type(self):
        """测试获取未知分类类型"""
        keywords = get_category_keywords("unknown_type", "something")
        assert isinstance(keywords, list)
        assert len(keywords) == 0

    def test_get_category_keywords_unknown_category_name(self):
        """测试获取未知分类名称"""
        keywords = get_category_keywords("interests", "不存在分类")
        assert isinstance(keywords, list)
        assert len(keywords) == 0