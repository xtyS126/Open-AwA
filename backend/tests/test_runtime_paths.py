"""运行时目录契约测试。"""

from pathlib import Path

from config.runtime_paths import (
    DATA_DIR,
    DOWNLOADS_DIR,
    PETS_DATA_DIR,
    PROJECT_ROOT,
    TOOL_OUTPUTS_DIR,
    TRANSCRIPTS_DIR,
    UPLOADS_DIR,
    VAR_DIR,
    WORKSPACE_DIR,
    get_workspace_dir,
)


def test_runtime_paths_are_anchored_to_project_root():
    """运行时数据必须统一落在项目根目录的 var 下。"""
    assert PROJECT_ROOT.name == "Open-AwA"
    assert VAR_DIR == PROJECT_ROOT / "var"
    assert DATA_DIR == VAR_DIR / "data"
    assert UPLOADS_DIR == DATA_DIR / "uploads"
    assert TOOL_OUTPUTS_DIR == UPLOADS_DIR / "tool_outputs"
    assert DOWNLOADS_DIR == DATA_DIR / "downloads"
    assert TRANSCRIPTS_DIR == DATA_DIR / "transcripts"
    assert PETS_DATA_DIR == VAR_DIR / "pets"


def test_workspace_dir_supports_explicit_override(monkeypatch, tmp_path: Path):
    """部署环境可通过环境变量指定独立工作区。"""
    monkeypatch.delenv("WORKSPACE_DIR", raising=False)
    assert get_workspace_dir() == WORKSPACE_DIR

    configured_workspace = tmp_path / "workspace"
    monkeypatch.setenv("WORKSPACE_DIR", str(configured_workspace))
    assert get_workspace_dir() == configured_workspace.resolve()


def test_vector_model_cache_uses_canonical_data_directory():
    """向量模型缓存必须复用统一运行时目录。"""
    from memory.vector_store_manager import _get_models_dir

    assert Path(_get_models_dir()) == DATA_DIR / "models"
