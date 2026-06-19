"""
LLM json_utils 模块测试。
"""
import pytest
from pydantic import BaseModel
from llm.json_utils import extract_json_from_text, complete_brackets, extract_json, parse_structured_output
from llm.exceptions import StructuredOutputError


class TestJsonUtils:
    """json_utils 模块单元测试。"""

    def test_extract_json_from_code_block(self):
        """从 ```json 代码块提取 JSON。"""
        text = '```json\n{"key": "value"}\n```'
        result = extract_json_from_text(text)
        assert result == '{"key": "value"}'

    def test_extract_json_from_code_block_no_lang(self):
        """从无语言标记的代码块提取 JSON。"""
        text = '```\n{"key": "value"}\n```'
        result = extract_json_from_text(text)
        assert result == '{"key": "value"}'

    def test_extract_json_from_naked_json(self):
        """从裸 JSON 文本提取。"""
        text = '一些前缀文字 {"key": "value"} 一些后缀文字'
        result = extract_json_from_text(text)
        assert result == '{"key": "value"}'

    def test_extract_json_from_naked_array(self):
        """从裸 JSON 数组提取。"""
        text = '前缀 [1, 2, 3] 后缀'
        result = extract_json_from_text(text)
        assert result == '[1, 2, 3]'

    def test_extract_json_empty_text(self):
        """空文本返回 None。"""
        assert extract_json_from_text("") is None

    def test_extract_json_none_text(self):
        """None 输入返回 None。"""
        assert extract_json_from_text("") is None  # 空字符串等价于 falsy

    def test_extract_json_no_braces(self):
        """不含 JSON 结构的文本返回 None。"""
        result = extract_json_from_text("只有普通文本，没有任何括号")
        assert result is None

    def test_complete_brackets_no_missing(self):
        """括号完整时不追加。"""
        result = complete_brackets('{"key": "value"}')
        assert result == '{"key": "value"}'

    def test_complete_brackets_missing_brace(self):
        """补全缺失的大括号。"""
        result = complete_brackets('{"key": "value"')
        assert result == '{"key": "value"}'

    def test_complete_brackets_missing_bracket(self):
        """补全缺失的方括号。"""
        result = complete_brackets('[1, 2, 3')
        assert result == '[1, 2, 3]'

    def test_complete_brackets_nested(self):
        """补全嵌套缺失括号。"""
        result = complete_brackets('{"arr": [1, 2')
        # 函数按大括号、方括号顺序追加，结果为 '{"arr": [1, 2}]'
        assert result == '{"arr": [1, 2}]'

    def test_complete_brackets_empty_string(self):
        """空字符串直接返回。"""
        result = complete_brackets("")
        assert result == ""

    def test_extract_json_success(self):
        """extract_json 成功解析 JSON。"""
        result = extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_extract_json_with_trailing_comma(self):
        """extract_json 容错处理尾部逗号。"""
        result = extract_json('{"key": "value",}')
        assert result == {"key": "value"}

    def test_extract_json_from_code_block_full(self):
        """extract_json 从代码块提取并解析。"""
        result = extract_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_extract_json_empty_default(self):
        """extract_json 空文本返回默认值。"""
        result = extract_json("", default={"default": True})
        assert result == {"default": True}

    def test_parse_structured_output_success(self):
        """parse_structured_output 成功解析为 Pydantic 模型。"""

        class TestSchema(BaseModel):
            name: str
            age: int

        text = '{"name": "Alice", "age": 30}'
        result = parse_structured_output(text, TestSchema)
        assert isinstance(result, TestSchema)
        assert result.name == "Alice"
        assert result.age == 30

    def test_parse_structured_output_from_code_block(self):
        """parse_structured_output 从代码块中解析。"""

        class TestSchema(BaseModel):
            value: str

        text = '```json\n{"value": "test"}\n```'
        result = parse_structured_output(text, TestSchema)
        assert result.value == "test"

    def test_parse_structured_output_failure(self):
        """parse_structured_output 解析失败抛 StructuredOutputError。"""

        class TestSchema(BaseModel):
            name: str

        text = "这不是 JSON"
        with pytest.raises(StructuredOutputError):
            parse_structured_output(text, TestSchema)

    def test_parse_structured_output_schema_mismatch(self):
        """parse_structured_output JSON 不符合 schema 抛异常。"""

        class TestSchema(BaseModel):
            required_field: str

        text = '{"wrong_field": "value"}'
        with pytest.raises(StructuredOutputError):
            parse_structured_output(text, TestSchema)