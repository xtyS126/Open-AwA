"""
局域网 APK 分发路由 - 手机浏览器直接下载安装 Open-AwA APP。

用途：手机与后端在同一局域网时，无需数据线 / USB 调试，
访问 http://<后端局域网IP>:8000/apk 即可在浏览器中下载并安装 APK。

设计：
- 无认证：局域网内部工具页，依赖 ALLOW_LAN_ACCESS 的网络边界（与 /api/system/ping 一致）
- 样式外链：后端 CSP 中间件在生产模式 style-src 'self'，页面必须使用同源 CSS 文件而非内联样式
- APK 路径默认锚定仓库相对位置，可用 APK_PATH 环境变量覆盖
"""

import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from config.settings import settings

router = APIRouter(prefix="/apk", tags=["apk"])

# APK 产物路径：优先环境变量 APK_PATH，其次原生 Android 项目产物，最后回退旧 Capacitor 产物
# __file__ = backend/api/routes/apk_dist.py，parents[3] = 项目根
def _resolve_apk_path() -> Path:
    override = os.getenv("APK_PATH", "").strip()
    if override:
        return Path(override)
    root = Path(__file__).resolve().parents[3]
    # 现行方案：原生 Android 项目（android/Open-AwA-Android）
    native_apk = (
        root
        / "android"
        / "Open-AwA-Android"
        / "app"
        / "build"
        / "outputs"
        / "apk"
        / "debug"
        / "app-debug.apk"
    )
    if native_apk.is_file():
        return native_apk
    # 回退：已废弃的 Capacitor 构建产物（仅为兼容存量环境）
    return (
        root
        / "frontend"
        / "android"
        / "app"
        / "build"
        / "outputs"
        / "apk"
        / "debug"
        / "app-debug.apk"
    )


_APK_PATH = _resolve_apk_path()
_CSS_PATH = Path(__file__).resolve().parent / "apk_dist.css"


def _format_size(num: int) -> str:
    """字节数转人类可读大小（MB 精度 1 位小数）"""
    if num >= 1024 * 1024:
        return f"{num / (1024 * 1024):.1f} MB"
    return f"{num / 1024:.0f} KB"


@router.get("", response_class=HTMLResponse)
async def apk_dist_page() -> HTMLResponse:
    """APK 分发页：版本信息 + 下载按钮 + 安装引导"""
    apk_exists = _APK_PATH.is_file()
    apk_size = _APK_PATH.stat().st_size if apk_exists else 0
    apk_mtime = _APK_PATH.stat().st_mtime if apk_exists else 0
    from datetime import datetime

    build_time = datetime.fromtimestamp(apk_mtime).strftime("%Y-%m-%d %H:%M") if apk_exists else ""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Open-AwA 手机版</title>
  <link rel="stylesheet" href="/apk/dist.css" />
</head>
<body>
  <main class="card">
    <header class="brand">
      <h1>Open-AwA</h1>
      <p class="subtitle">手机版安装</p>
    </header>

    <section class="pkg-info" aria-label="安装包信息">
      <div class="pkg-row">
        <span>安装包版本</span>
        <span class="strong">{'v' + settings.VERSION if apk_exists else '未找到'}</span>
      </div>
      <div class="pkg-row">
        <span>文件大小</span>
        <span class="strong">{_format_size(apk_size) if apk_exists else '—'}</span>
      </div>
      <div class="pkg-row">
        <span>构建时间</span>
        <span class="strong">{build_time or '—'}</span>
      </div>
      <div class="pkg-row">
        <span>后端版本</span>
        <span class="strong">v{settings.VERSION}</span>
      </div>
    </section>

    <a class="download-btn" href="/apk/download" role="button">下载并安装</a>

    <section class="steps" aria-label="安装步骤">
      <ol>
        <li>点击上方按钮下载安装包</li>
        <li>下载完成后打开系统通知栏，点击 APK 开始安装</li>
        <li>若提示“禁止安装未知来源”，请到 设置 → 安全 → 允许来自此来源的应用</li>
      </ol>
    </section>

    <p class="footnote">请在手机浏览器中访问本页面，无需连接数据线</p>
  </main>
</body>
</html>"""
    return HTMLResponse(html)


@router.get("/dist.css", response_class=FileResponse)
async def apk_dist_css() -> FileResponse:
    """分发页样式（同源外链，满足 CSP style-src 'self'）"""
    return FileResponse(_CSS_PATH, media_type="text/css")


@router.get("/download")
async def apk_download():
    """APK 下载：以 application/vnd.android.package-archive 响应触发系统安装器"""
    if not _APK_PATH.is_file():
        return HTMLResponse(
            "<h2>安装包不存在</h2><p>请先在 frontend/android 下执行打包（gradlew assembleDebug）。</p>",
            status_code=404,
        )
    return FileResponse(
        _APK_PATH,
        media_type="application/vnd.android.package-archive",
        filename="Open-AwA.apk",
    )
