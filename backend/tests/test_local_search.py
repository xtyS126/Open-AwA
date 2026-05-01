"""
本地搜索引擎单元测试。
测试索引构建、搜索、删除、持久化等核心功能。
"""
import pytest
import asyncio
import tempfile
import os
from pathlib import Path


@pytest.fixture
async def engine():
    """创建测试用的搜索引擎实例。"""
    from core.builtin_tools.local_search import LocalSearchEngine

    tmpdir = tempfile.mkdtemp()
    eng = LocalSearchEngine({"index_dir": tmpdir})
    await eng.initialize()
    yield eng
    # 清理测试数据
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.asyncio
async def test_initialize_empty_index(engine):
    """测试初始化空索引。"""
    assert engine.is_initialized()
    assert engine._doc_count == 0
    assert len(engine._documents) == 0


@pytest.mark.asyncio
async def test_index_single_document(engine):
    """测试索引单个文档。"""
    result = await engine.execute(
        action="index",
        id="doc1",
        title="测试文档",
        content="这是一段用于测试搜索功能的中文文本内容"
    )
    assert result["success"] is True
    assert engine._doc_count == 1


@pytest.mark.asyncio
async def test_search_basic(engine):
    """测试基本搜索功能。"""
    await engine.execute(
        action="index",
        id="doc1",
        title="Python编程指南",
        content="Python是一门强大的编程语言，广泛应用于AI和数据科学领域"
    )
    await engine.execute(
        action="index",
        id="doc2",
        title="JavaScript教程",
        content="JavaScript是Web开发的核心语言，用于前端和后端开发"
    )

    result = await engine.execute(action="search", query="Python")
    assert result["success"] is True
    assert len(result["results"]) >= 1
    assert any(r["id"] == "doc1" for r in result["results"])


@pytest.mark.asyncio
async def test_search_chinese(engine):
    """测试中文搜索。"""
    await engine.execute(
        action="index",
        id="chinese1",
        title="机器学习入门",
        content="机器学习是人工智能的一个分支，专注于从数据中学习模式"
    )
    await engine.execute(
        action="index",
        id="chinese2",
        title="深度学习框架",
        content="PyTorch和TensorFlow是两个主流的深度学习框架"
    )

    # 搜索中文关键词
    result = await engine.execute(action="search", query="机器学习")
    assert result["success"] is True
    assert len(result["results"]) >= 1
    assert any(r["id"] == "chinese1" for r in result["results"])

    # 搜索另一个关键词
    result = await engine.execute(action="search", query="深度学习")
    assert result["success"] is True
    assert len(result["results"]) >= 1
    assert any(r["id"] == "chinese2" for r in result["results"])


@pytest.mark.asyncio
async def test_search_empty_query(engine):
    """测试空查询。"""
    result = await engine.execute(action="search", query="")
    assert result["success"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_search_empty_index(engine):
    """测试空索引搜索。"""
    result = await engine.execute(action="search", query="nothing")
    assert result["success"] is True
    assert len(result["results"]) == 0


@pytest.mark.asyncio
async def test_remove_document(engine):
    """测试移除文档。"""
    await engine.execute(
        action="index",
        id="temp1",
        title="临时文档",
        content="待删除的内容"
    )
    assert engine._doc_count == 1

    result = await engine.execute(action="remove", id="temp1")
    assert result["success"] is True
    assert engine._doc_count == 0


@pytest.mark.asyncio
async def test_update_document(engine):
    """测试更新文档（重新索引）。"""
    await engine.execute(
        action="index",
        id="update1",
        title="原始标题",
        content="原始内容"
    )
    assert engine._doc_count == 1

    # 重新索引同一ID
    result = await engine.execute(
        action="index",
        id="update1",
        title="更新后的标题",
        content="更新后的内容"
    )
    assert result["success"] is True
    assert engine._doc_count == 1  # 仍然是1篇


@pytest.mark.asyncio
async def test_search_modes(engine):
    """测试不同搜索模式。"""
    await engine.execute(
        action="index",
        id="mode1",
        title="搜索引擎测试",
        content="测试精确匹配和前缀匹配功能"
    )

    # 精确匹配
    result = await engine.execute(action="search", query="搜索引擎", mode="exact")
    assert result["success"] is True

    # 前缀匹配
    result = await engine.execute(action="search", query="搜索", mode="prefix")
    assert result["success"] is True

    # TF-IDF模式
    result = await engine.execute(action="search", query="搜索", mode="tfidf")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_search_stats(engine):
    """测试统计信息。"""
    await engine.execute(
        action="index",
        id="stat1",
        title="统计测试",
        content="内容A B C D E F G H"
    )

    result = await engine.execute(action="stats")
    assert result["success"] is True
    assert result["doc_count"] == 1
    assert result["unique_terms"] > 0
    assert result["avg_terms_per_doc"] > 0


@pytest.mark.asyncio
async def test_clear_index(engine):
    """测试清空索引。"""
    await engine.execute(
        action="index",
        id="clear1",
        title="待清除",
        content="将被清空的内容"
    )
    assert engine._doc_count == 1

    result = await engine.execute(action="clear")
    assert result["success"] is True
    assert engine._doc_count == 0
    assert len(engine._documents) == 0


@pytest.mark.asyncio
async def test_persistence(engine):
    """测试索引持久化和恢复。"""
    from core.builtin_tools.local_search import LocalSearchEngine

    # 添加文档
    await engine.execute(
        action="index",
        id="persist1",
        title="持久化测试",
        content="测试索引的保存和加载功能"
    )

    # 创建新引擎实例，从同一目录加载
    engine2 = LocalSearchEngine({"index_dir": str(engine.index_dir)})
    await engine2.initialize()

    assert engine2._doc_count == 1
    assert "persist1" in engine2._documents

    # 搜索恢复的索引
    result = await engine2.execute(action="search", query="持久化")
    assert result["success"] is True
    assert len(result["results"]) >= 1


@pytest.mark.asyncio
async def test_html_stripping():
    """测试HTML标签移除。"""
    from core.builtin_tools.local_search import LocalSearchEngine

    html = """
    <html>
    <head><title>Test</title></head>
    <body>
    <script>alert('xss')</script>
    <style>.test{color:red}</style>
    <h1>标题</h1>
    <p>这是正文内容。</p>
    </body>
    </html>
    """
    text = LocalSearchEngine._strip_html(html)
    assert "标题" in text
    assert "正文内容" in text
    assert "alert" not in text
    assert ".test" not in text


@pytest.mark.asyncio
async def test_chinese_tokenization(engine):
    """测试中文分词效果。"""
    tokens = engine._tokenize("你好世界")
    # bigram: 你好, 你, 好世, 好, 世界, 世, 界
    assert "你好" in tokens
    assert "世界" in tokens
    assert "你" in tokens
    assert "好" in tokens

    # 混合中英文
    tokens = engine._tokenize("AI人工智能GPT模型")
    assert "ai" in tokens
    assert "人工" in tokens
    assert "智能" in tokens
    assert "gpt" in tokens


@pytest.mark.asyncio
async def test_ranking_relevance(engine):
    """测试搜索结果的相关性排序。"""
    await engine.execute(
        action="index",
        id="rel1",
        title="Python数据分析",
        content="Python Python Python Python Python 数据分析 数据分析 数据分析"
    )
    await engine.execute(
        action="index",
        id="rel2",
        title="Python简介",
        content="Python Java C++ 编程语言对比"
    )

    result = await engine.execute(action="search", query="Python 数据分析")
    assert result["success"] is True
    if len(result["results"]) >= 2:
        # rel1应该排在rel2前面（相关性更高）
        scores = [r["score"] for r in result["results"]]
        rel1_idx = next(i for i, r in enumerate(result["results"]) if r["id"] == "rel1")
        rel2_idx = next(i for i, r in enumerate(result["results"]) if r["id"] == "rel2")
        assert rel1_idx < rel2_idx, f"Expected rel1 before rel2, got scores {scores}"
