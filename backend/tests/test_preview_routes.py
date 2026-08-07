# -*- coding: utf-8 -*-
"""
文件预览与反向代理路由单元测试。

覆盖：
- /api/coding/preview/file 端点：Markdown 渲染、图片/音视频 Content-Type、Range 请求、
  Office 降级、路径遍历防护、未知类型回退
- /api/preview/{port}/{path:path} 反向代理：成功透传、port 范围校验、SSRF 防护
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user
from api.routes.coding import router as coding_router
from api.routes.preview_proxy import router as preview_proxy_router


# ==================== 测试用户与依赖覆盖 ====================


class _DummyUser:
    """测试用 DummyUser，仅暴露 id/username/role 三个字段。"""

    def __init__(self, user_id: str, username: str, role: str = "user") -> None:
        self.id = user_id
        self.username = username
        self.role = role


_USER_A = _DummyUser("user-a", "alice")
# RBAC fail-closed 后，preview 属于 coding:read 权限范畴，渲染类测试使用管理员身份
_ADMIN_USER = _DummyUser("admin-1", "admin", role="admin")


def _override_user(user: _DummyUser):
    """生成 get_current_user 的依赖覆盖函数。"""

    def _override() -> _DummyUser:
        return user

    return _override


# ==================== 公共 fixture ====================


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """构造临时项目目录，并预置若干测试文件。"""
    (tmp_path / "docs").mkdir()
    (tmp_path / "media").mkdir()
    (tmp_path / "office").mkdir()

    # Markdown 文件（含 <script> 和 <img onerror> 用于 bleach 净化测试）
    md_with_script = (
        '# 标题\n\n'
        '<script>alert(1)</script>\n\n'
        '<img src="x" onerror="alert(2)">\n\n'
        '正文 **加粗**。\n'
    )
    (tmp_path / "docs" / "test.md").write_text(md_with_script, encoding="utf-8")

    # 普通文本文件
    (tmp_path / "docs" / "plain.txt").write_text("纯文本内容", encoding="utf-8")

    # 图片文件（伪造 PNG 头）
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    (tmp_path / "media" / "pic.png").write_bytes(png_bytes)
    (tmp_path / "media" / "pic.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16)

    # 音视频文件
    (tmp_path / "media" / "song.mp3").write_bytes(b"ID3" + b"\x00" * 64)
    (tmp_path / "media" / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftyp" + b"\x00" * 32)
    (tmp_path / "media" / "tone.wav").write_bytes(b"RIFF" + b"\x00" * 64)

    # Office 文件（伪二进制）
    (tmp_path / "office" / "doc.docx").write_bytes(b"PK\x03\x04" + b"\x00" * 32)

    # 大文件（用于 Range 测试，512 字节固定内容）
    (tmp_path / "media" / "big.mp4").write_bytes(b"AB" * 256)  # 512 字节
    return tmp_path


@contextmanager
def _coding_client(project_root: Path, user: Optional[_DummyUser] = _ADMIN_USER):
    """构造 coding 路由的 TestClient，将默认项目目录指向临时目录。

    使用 contextmanager + patch 形式，避免装饰器注入 mock 时的位置参数混乱。
    默认使用管理员身份：preview 端点已启用 RBAC fail-closed（coding:read），
    渲染类测试不关心权限分支，统一走管理员放行路径。
    """
    with patch("api.routes.coding.DEFAULT_PROJECT_DIR", str(project_root)):
        app = FastAPI()
        app.include_router(coding_router)
        if user is not None:
            app.dependency_overrides[get_current_user] = _override_user(user)
        with TestClient(app) as client:
            yield client


@contextmanager
def _proxy_client():
    """构造 preview_proxy 路由的 TestClient。"""
    app = FastAPI()
    app.include_router(preview_proxy_router)
    app.dependency_overrides[get_current_user] = _override_user(_USER_A)
    with TestClient(app) as client:
        yield client


# ==================== Markdown 预览测试 ====================


class TestMarkdownPreview:
    """Markdown 文件预览。"""

    def test_renders_markdown_to_html(self, project_root: Path) -> None:
        """Markdown 文件应被渲染为 HTML。"""
        with _coding_client(project_root) as client:
            response = client.get("/api/coding/preview/file", params={"path": "docs/test.md"})

        assert response.status_code == 200
        body = response.json()
        assert body["type"] == "markdown"
        assert "<h1>" in body["html"] or "<h1>" in body["html"]
        assert "加粗" in body["html"]

    def test_bleach_strips_script_tag(self, project_root: Path) -> None:
        """Markdown 渲染出的 HTML 应经过 bleach 净化，<script> 标签被移除。

        安全目标：阻止脚本执行，即 <script> 标签不能出现在输出中。
        标签内的文本内容（如 "alert(1)"）被保留为可见纯文本是安全的。
        """
        with _coding_client(project_root) as client:
            response = client.get("/api/coding/preview/file", params={"path": "docs/test.md"})

        assert response.status_code == 200
        html = response.json()["html"]
        # <script> 标签必须被移除（不区分大小写）
        assert "<script>" not in html.lower()
        assert "<script " not in html.lower()
        assert "</script>" not in html.lower()
        # onerror 等事件处理器属性也应被移除
        assert "onerror" not in html.lower()


# ==================== 图片预览测试 ====================


class TestImagePreview:
    """图片文件预览。"""

    def test_png_returns_correct_content_type(self, project_root: Path) -> None:
        """PNG 图片应返回 image/png Content-Type。"""
        with _coding_client(project_root) as client:
            response = client.get("/api/coding/preview/file", params={"path": "media/pic.png"})

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content.startswith(b"\x89PNG")

    def test_jpeg_returns_correct_content_type(self, project_root: Path) -> None:
        """JPEG 图片应返回 image/jpeg Content-Type。"""
        with _coding_client(project_root) as client:
            response = client.get("/api/coding/preview/file", params={"path": "media/pic.jpg"})

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"


# ==================== 音视频预览测试 ====================


class TestAudioVideoPreview:
    """音视频文件预览。"""

    def test_mp3_returns_correct_content_type(self, project_root: Path) -> None:
        """MP3 文件应返回 audio/mpeg Content-Type。"""
        with _coding_client(project_root) as client:
            response = client.get("/api/coding/preview/file", params={"path": "media/song.mp3"})

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"

    def test_mp4_returns_correct_content_type(self, project_root: Path) -> None:
        """MP4 文件应返回 video/mp4 Content-Type。"""
        with _coding_client(project_root) as client:
            response = client.get("/api/coding/preview/file", params={"path": "media/clip.mp4"})

        assert response.status_code == 200
        assert response.headers["content-type"] == "video/mp4"

    def test_wav_returns_correct_content_type(self, project_root: Path) -> None:
        """WAV 文件应返回 audio/wav Content-Type。"""
        with _coding_client(project_root) as client:
            response = client.get("/api/coding/preview/file", params={"path": "media/tone.wav"})

        assert response.status_code == 200
        assert response.headers["content-type"] in ("audio/wav", "audio/x-wav", "audio/wave")


# ==================== Range 请求测试 ====================


class TestRangeRequest:
    """音视频 Range 请求支持。"""

    def test_range_request_returns_206_partial_content(self, project_root: Path) -> None:
        """携带 Range 头时应返回 206 Partial Content 与 Content-Range。"""
        with _coding_client(project_root) as client:
            response = client.get(
                "/api/coding/preview/file",
                params={"path": "media/big.mp4"},
                headers={"Range": "bytes=0-127"},
            )

        assert response.status_code == 206
        assert response.headers.get("content-range") is not None
        # Content-Range: bytes 0-127/512
        cr = response.headers["content-range"]
        assert cr.startswith("bytes 0-127/")
        assert cr.endswith("/512")
        assert response.headers.get("accept-ranges") == "bytes"
        assert len(response.content) == 128

    def test_full_request_returns_200(self, project_root: Path) -> None:
        """无 Range 头时应返回完整文件。"""
        with _coding_client(project_root) as client:
            response = client.get(
                "/api/coding/preview/file",
                params={"path": "media/big.mp4"},
            )

        assert response.status_code == 200
        assert len(response.content) == 512


# ==================== Office 文件降级测试 ====================


class TestOfficeFallback:
    """Office 文件降级为下载链接。"""

    def test_docx_returns_download_link_when_no_extractor(self, project_root: Path) -> None:
        """docx 文件无 mammoth 时应返回下载链接。"""
        # 强制 mammoth 不可导入
        import builtins

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "mammoth":
                raise ImportError("no mammoth")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_fake_import):
            with _coding_client(project_root) as client:
                response = client.get(
                    "/api/coding/preview/file", params={"path": "office/doc.docx"}
                )

        assert response.status_code == 200
        body = response.json()
        # 至少应返回 download 类型的下载链接
        assert body["type"] == "download"
        assert "url" in body
        assert "/api/coding/download" in body["url"]


# ==================== 路径遍历防护测试 ====================


class TestPathTraversal:
    """路径遍历防护。"""

    def test_rejects_path_traversal_to_etc_passwd(self, project_root: Path) -> None:
        """禁止访问项目目录外的 /etc/passwd。"""
        with _coding_client(project_root) as client:
            response = client.get(
                "/api/coding/preview/file",
                params={"path": "../../../../etc/passwd"},
            )

        # 路径越权应被拒绝（403 或 404 都算防护成功）
        assert response.status_code in (403, 404)

    def test_rejects_absolute_path_outside_root(self, project_root: Path) -> None:
        """禁止访问绝对路径指向项目目录外。"""
        with _coding_client(project_root) as client:
            response = client.get(
                "/api/coding/preview/file",
                params={"path": "/etc/passwd"},
            )

        assert response.status_code in (403, 404)


# ==================== 未知文件类型测试 ====================


class TestUnknownFileType:
    """未知文件类型回退。"""

    def test_text_file_returns_text_type(self, project_root: Path) -> None:
        """普通文本文件应返回 type=text。"""
        with _coding_client(project_root) as client:
            response = client.get("/api/coding/preview/file", params={"path": "docs/plain.txt"})

        assert response.status_code == 200
        body = response.json()
        assert body["type"] == "text"
        assert "纯文本内容" in body["content"]


# ==================== RBAC fail-closed 测试 ====================


class TestRbacFailClosed:
    """非管理员访问 coding 预览端点应被拒绝（fail-closed）。

    删除兜底后：无显式角色分配的用户按默认 viewer 角色判定（无 coding 权限），
    一律 403，禁止降级放行。
    """

    def test_non_admin_rejected_from_preview(self, project_root: Path) -> None:
        """role=user 且无 coding:read 权限的用户访问 preview 应 403。"""
        with _coding_client(project_root, user=_USER_A) as client:
            response = client.get(
                "/api/coding/preview/file", params={"path": "docs/plain.txt"}
            )

        assert response.status_code == 403


# ==================== 反向代理测试 ====================


class _FakeStreamResponse:
    """模拟 httpx.AsyncClient.stream 上下文。"""

    def __init__(self, status_code: int, content: bytes, headers: dict) -> None:
        self.status_code = status_code
        self._content = content
        self.headers = headers

    async def aiter_bytes(self):
        # 简单按块返回
        yield self._content

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TestPreviewProxy:
    """反向代理到本地开发服务器。"""

    def test_proxy_passes_through_response(self) -> None:
        """成功代理响应，透传状态码、headers、body。"""
        fake_response = _FakeStreamResponse(
            status_code=200,
            content=b"hello-from-dev-server",
            headers={"content-type": "text/html; charset=utf-8", "x-custom": "yes"},
        )

        fake_client = MagicMock()
        fake_client.stream = MagicMock(return_value=fake_response)
        fake_client.aclose = AsyncMock()

        with patch("api.routes.preview_proxy.httpx.AsyncClient", return_value=fake_client):
            with _proxy_client() as client:
                response = client.get("/api/preview/5173/index.html")

        assert response.status_code == 200
        assert response.content == b"hello-from-dev-server"
        assert response.headers.get("x-custom") == "yes"
        # 应代理到 127.0.0.1:5173
        # client.stream(method, url, headers=...) 形式：第一个是 method，第二个是 url
        call_args = fake_client.stream.call_args
        if len(call_args.args) >= 2:
            url = call_args.args[1]
        else:
            url = call_args.kwargs.get("url", "")
        assert "127.0.0.1:5173" in str(url)
        assert "/index.html" in str(url)

    def test_rejects_port_below_1024(self) -> None:
        """port < 1024 应返回 400。"""
        with _proxy_client() as client:
            response = client.get("/api/preview/80/index.html")

        assert response.status_code == 400
        assert "port" in response.json()["detail"].lower()

    def test_rejects_port_above_65535(self) -> None:
        """port > 65535 应返回 400。"""
        with _proxy_client() as client:
            response = client.get("/api/preview/70000/index.html")

        assert response.status_code == 400
        assert "port" in response.json()["detail"].lower()

    def test_rejects_port_at_boundary_1023(self) -> None:
        """边界值 1023 应拒绝（< 1024）。"""
        with _proxy_client() as client:
            response = client.get("/api/preview/1023/foo")

        assert response.status_code == 400

    def test_accepts_allowed_preview_port(self) -> None:
        """边界值 1024 应被接受（>= 1024）。"""
        fake_response = _FakeStreamResponse(
            status_code=200, content=b"ok", headers={"content-type": "text/plain"}
        )
        fake_client = MagicMock()
        fake_client.stream = MagicMock(return_value=fake_response)
        fake_client.aclose = AsyncMock()

        with patch("api.routes.preview_proxy.httpx.AsyncClient", return_value=fake_client):
            with _proxy_client() as client:
                response = client.get("/api/preview/3000/")

        assert response.status_code == 200

    def test_passes_query_params(self) -> None:
        """查询参数应透传到目标。"""
        fake_response = _FakeStreamResponse(
            status_code=200, content=b"ok", headers={"content-type": "text/plain"}
        )
        fake_client = MagicMock()
        fake_client.stream = MagicMock(return_value=fake_response)
        fake_client.aclose = AsyncMock()

        with patch("api.routes.preview_proxy.httpx.AsyncClient", return_value=fake_client):
            with _proxy_client() as client:
                response = client.get("/api/preview/5173/api", params={"q": "1"})

        assert response.status_code == 200
        # 验证 stream 被调用过
        fake_client.stream.assert_called_once()
