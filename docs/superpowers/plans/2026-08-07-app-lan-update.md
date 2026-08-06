# APP 局域网 OTA 更新功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移动 APP（Capacitor Android）连接局域网后端后，启动/手动可检测到新版本 APK，弹窗让用户选择是否下载安装。

**Architecture:** 后端 `var/apk/manifest.json` 作为更新元数据唯一事实源（部署脚本构建后生成），`/api/system/update-check` 按客户端 versionCode 对比返回是否有更新，`/api/system/apk/download` 认证流式托管 APK。APP 端新增原生 Capacitor 插件 `AppUpdatePlugin`（读取本地 versionCode + 下载 APK 到 cacheDir + SHA256 校验 + FileProvider 触发系统安装 + 进度事件），前端 `useAppUpdate` hook + `UpdateDialog` 弹窗承载"检测 → 提示 → 用户选择 → 下载 → 安装"完整链路。

**Tech Stack:** FastAPI（后端）、Capacitor 8 / Java 原生插件（Android）、React 18 + Zustand（前端）、PowerShell 部署脚本、Playwright + adb（E2E）。

---

## 文件结构映射

| 文件 | 职责 |
|---|---|
| `backend/api/routes/system.py` | 新增 `update-check` / `apk/download` 端点 |
| `backend/config/runtime_paths.py` | 新增 `APK_DIR`（var/apk）路径常量 |
| `backend/tests/test_system_update.py` | 后端更新接口测试 |
| `frontend/android/app/src/main/java/com/openawa/mobile/AppUpdatePlugin.java` | 原生插件：versionCode + 下载 + 校验 + 安装 + 进度 |
| `frontend/android/app/src/main/AndroidManifest.xml` | 加 `REQUEST_INSTALL_PACKAGES` 权限 |
| `frontend/android/app/src/main/res/xml/file_paths.xml` | 加 cache 下载目录 path（已有 cache-path，扩展 fileName） |
| `frontend/android/app/src/main/java/com/openawa/mobile/MainActivity.java` | 注册 AppUpdatePlugin |
| `frontend/src/shared/api/updateApi.ts` | 前端更新 API 模块 |
| `frontend/src/shared/hooks/useAppUpdate.ts` | 检查/下载/安装状态机 + 进度订阅 |
| `frontend/src/shared/components/UpdateDialog/UpdateDialog.tsx` + `.module.css` | 更新弹窗 UI |
| `frontend/src/features/settings/` | 设置页"检查更新"入口 |
| `frontend/src/App.tsx` | 启动时自动检查挂载 |
| `frontend/scripts/release-apk.ps1` | 版本同步 + 构建 + manifest 生成 + 部署 |
| `frontend/src/__tests__/shared/hooks/useAppUpdate.test.ts`、`__tests__/shared/components/UpdateDialog.test.tsx` | 前端测试 |

---

### Task 1: 后端 update-check 端点 + manifest 读取

**Files:**
- Modify: `backend/config/runtime_paths.py`
- Modify: `backend/api/routes/system.py`
- Create: `backend/tests/test_system_update.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_system_update.py
"""APP 局域网 OTA 更新接口测试。"""
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def apk_dir(tmp_path, monkeypatch):
    """临时 APK 目录 + manifest。"""
    from config import runtime_paths
    monkeypatch.setattr(runtime_paths, "APK_DIR", tmp_path)
    # 让 system.py 的模块级引用指向新目录
    monkeypatch.setattr("api.routes.system.APK_DIR", tmp_path)
    return tmp_path


def _write_manifest(apk_dir: Path, version_code: int, version: str = "1.0.1") -> None:
    apk = apk_dir / "openawa-1.0.1.apk"
    apk.write_bytes(b"fake-apk-content")
    apk_dir.joinpath("manifest.json").write_text(
        json.dumps({
            "version": version,
            "version_code": version_code,
            "apk": apk.name,
            "apk_size": apk.stat().st_size,
            "apk_sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
            "changelog": "修复已知问题",
            "published_at": "2026-08-07T10:00:00+08:00",
        }),
        encoding="utf-8",
    )


def test_update_check_no_manifest(apk_dir, client):
    resp = client.get("/api/system/update-check?version_code=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_update"] is False


def test_update_check_newer_version_available(apk_dir, client):
    _write_manifest(apk_dir, version_code=2)
    resp = client.get("/api/system/update-check?version_code=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_update"] is True
    assert data["latest_version"] == "1.0.1"
    assert data["latest_version_code"] == 2
    assert data["apk_size"] > 0
    assert len(data["apk_sha256"]) == 64
    assert data["download_url"] == "/api/system/apk/download"


def test_update_check_same_version(apk_dir, client):
    _write_manifest(apk_dir, version_code=1)
    resp = client.get("/api/system/update-check?version_code=1")
    assert resp.json()["has_update"] is False


def test_update_check_client_version_greater(apk_dir, client):
    _write_manifest(apk_dir, version_code=1)
    resp = client.get("/api/system/update-check?version_code=5")
    assert resp.json()["has_update"] is False
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_system_update.py -q --tb=short -p no:cacheprovider`
Expected: FAIL（`api.routes.system.APK_DIR` 不存在 / 端点 404）

- [ ] **Step 3: 实现 runtime_paths + 端点**

```python
# backend/config/runtime_paths.py 追加
APK_DIR = _DATA_DIR.parent / "apk"  # var/apk：APP 更新包部署目录
APK_DIR.mkdir(parents=True, exist_ok=True)
```

```python
# backend/api/routes/system.py 追加（文件顶部 import 区）
import hashlib
import json
from pathlib import Path
from fastapi.responses import FileResponse
from config.runtime_paths import APK_DIR

# 模块级缓存 manifest（部署后 60s 内生效，避免每次请求读盘）
_UPDATE_MANIFEST_CACHE: dict = {"mtime": 0.0, "data": None}

def _load_update_manifest() -> dict | None:
    manifest_path = APK_DIR / "manifest.json"
    if not manifest_path.exists():
        _UPDATE_MANIFEST_CACHE.update({"mtime": 0.0, "data": None})
        return None
    mtime = manifest_path.stat().st_mtime
    if _UPDATE_MANIFEST_CACHE["mtime"] == mtime and _UPDATE_MANIFEST_CACHE["data"] is not None:
        return _UPDATE_MANIFEST_CACHE["data"]
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        _UPDATE_MANIFEST_CACHE.update({"mtime": mtime, "data": data})
        return data
    except Exception:
        _UPDATE_MANIFEST_CACHE.update({"mtime": 0.0, "data": None})
        return None


@router.get("/update-check")
async def update_check(version_code: int = Query(0, ge=0, description="客户端 APK versionCode")):
    """
    APP 更新检查：返回局域网后端托管的 APK 版本元数据。
    无 manifest（未部署更新包）或客户端已是最新时 has_update=false。
    """
    manifest = _load_update_manifest()
    if manifest is None:
        return {"has_update": False}
    latest_code = int(manifest.get("version_code", 0))
    if latest_code <= version_code:
        return {"has_update": False}
    return {
        "has_update": True,
        "latest_version": manifest.get("version", ""),
        "latest_version_code": latest_code,
        "apk_size": int(manifest.get("apk_size", 0)),
        "apk_sha256": manifest.get("apk_sha256", ""),
        "changelog": manifest.get("changelog", ""),
        "download_url": f"{settings.API_V1_STR}/system/apk/download",
        "published_at": manifest.get("published_at", ""),
    }


@router.get("/apk/download")
async def apk_download(current_user: User = Depends(get_current_user)):
    """
    下载托管 APK（需认证）。返回流式文件 + X-APK-SHA256 响应头供客户端校验。
    """
    manifest = _load_update_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="未部署更新包")
    apk_path = APK_DIR / manifest.get("apk", "")
    if not apk_path.exists():
        raise HTTPException(status_code=404, detail="APK 文件缺失")
    return FileResponse(
        path=str(apk_path),
        filename=apk_path.name,
        media_type="application/vnd.android.package-archive",
        headers={"X-APK-SHA256": manifest.get("apk_sha256", "")},
    )
```

> 注意：`User` / `get_current_user` / `HTTPException` / `Query` / `Depends` 在 system.py 已有导入则复用；无则按现有 import 风格补充。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_system_update.py -q --tb=short -p no:cacheprovider`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/config/runtime_paths.py backend/api/routes/system.py backend/tests/test_system_update.py
git commit -m "[New] APP 局域网 OTA 更新：后端 update-check + APK 托管下载端点"
```

---

### Task 2: 原生 AppUpdatePlugin（versionCode + 下载 + 校验 + 安装 + 进度）

**Files:**
- Create: `frontend/android/app/src/main/java/com/openawa/mobile/AppUpdatePlugin.java`
- Modify: `frontend/android/app/src/main/AndroidManifest.xml`
- Modify: `frontend/android/app/src/main/res/xml/file_paths.xml`
- Modify: `frontend/android/app/src/main/java/com/openawa/mobile/MainActivity.java`

- [ ] **Step 1: Manifest 权限 + FileProvider 路径**

```xml
<!-- AndroidManifest.xml <manifest> 内追加 -->
<uses-permission android:name="android.permission.REQUEST_INSTALL_PACKAGES" />
<uses-permission android:name="android.permission.INTERNET" /> <!-- 已存在则忽略 -->
```

```xml
<!-- file_paths.xml <paths> 内追加（cacheDir 下的下载目录） -->
<cache-path name="update_apk" path="update/" />
```

- [ ] **Step 2: 实现 AppUpdatePlugin.java**

```java
package com.openawa.mobile;

import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.util.Log;

import androidx.core.content.FileProvider;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;

/**
 * APP 更新插件：读取本地 versionCode、下载 APK 到 cacheDir、SHA256 校验、
 * FileProvider 暴露并触发系统安装界面。
 *
 * 安全设计：
 * - APK 下载走 HTTPS/HTTP（局域网），Authorization Bearer 头传递 API Key，token 不入 URL
 * - SHA256 强制校验，不匹配则删除文件并报错，绝不触发安装
 * - 仅写入 cacheDir（系统可回收），不持久化
 */
@CapacitorPlugin(name = "AppUpdate")
public class AppUpdatePlugin extends Plugin {

    private static final String TAG = "AppUpdatePlugin";

    @PluginMethod
    public void getCurrentVersionCode(PluginCall call) {
        JSObject result = new JSObject();
        result.put("version_code", BuildConfig.VERSION_CODE);
        result.put("version_name", BuildConfig.VERSION_NAME);
        call.resolve(result);
    }

    @PluginMethod
    public void downloadAndInstall(PluginCall call) {
        String url = call.getString("url");
        String fileName = call.getString("fileName");
        String sha256 = call.getString("sha256");
        String authToken = call.getString("authToken");

        if (url == null || fileName == null || sha256 == null || sha256.length() != 64) {
            call.reject("参数缺失或 sha256 非法");
            return;
        }

        // Android 8+ 需要"安装未知应用"权限；无权限时引导到系统设置
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !getContext().getPackageManager().canRequestPackageInstalls()) {
            JSObject err = new JSObject();
            err.put("code", "NEED_INSTALL_PERMISSION");
            err.put("message", "需要授予安装未知应用权限");
            call.resolve(err);
            try {
                Intent intent = new Intent(
                    Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:" + getContext().getPackageName())
                );
                getActivity().startActivity(intent);
            } catch (ActivityNotFoundException e) {
                Log.w(TAG, "无法打开未知来源设置页", e);
            }
            return;
        }

        new Thread(() -> {
            try {
                File apkFile = download(url, fileName, sha256, authToken, call);
                install(apkFile, call);
            } catch (Exception e) {
                Log.e(TAG, "download/install failed", e);
                call.reject(e.getMessage());
            }
        }).start();
    }

    private File download(String url, String fileName, String sha256, String authToken, PluginCall call) throws Exception {
        File dir = new File(getContext().getCacheDir(), "update");
        if (!dir.exists() && !dir.mkdirs()) {
            throw new IllegalStateException("无法创建下载目录");
        }
        File apkFile = new File(dir, fileName);
        if (apkFile.exists()) {
            apkFile.delete();
        }

        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setConnectTimeout(10000);
        conn.setReadTimeout(30000);
        if (authToken != null && !authToken.isEmpty()) {
            conn.setRequestProperty("Authorization", "Bearer " + authToken);
        }
        conn.connect();
        if (conn.getResponseCode() != 200) {
            throw new IllegalStateException("下载失败 HTTP " + conn.getResponseCode());
        }
        long total = conn.getContentLengthLong();
        MessageDigest digest = MessageDigest.getInstance("SHA-256");

        try (InputStream in = conn.getInputStream(); FileOutputStream out = new FileOutputStream(apkFile)) {
            byte[] buffer = new byte[64 * 1024];
            long loaded = 0;
            int read;
            while ((read = in.read(buffer)) != -1) {
                out.write(buffer, 0, read);
                digest.update(buffer, 0, read);
                loaded += read;
                if (total > 0) {
                    int percent = (int) (loaded * 100 / total);
                    notifyListeners("updateProgress", new JSObject()
                        .put("loaded", loaded)
                        .put("total", total)
                        .put("percent", percent));
                }
            }
        } finally {
            conn.disconnect();
        }

        // SHA256 校验：不匹配删除文件并抛错
        String actual = toHex(digest.digest());
        if (!sha256.equalsIgnoreCase(actual)) {
            apkFile.delete();
            throw new IllegalStateException("APK 校验失败：期望 " + sha256 + "，实际 " + actual);
        }
        return apkFile;
    }

    private void install(File apkFile, PluginCall call) {
        Uri apkUri = FileProvider.getUriForFile(
            getContext(),
            getContext().getPackageName() + ".fileprovider",
            apkFile
        );
        Intent intent = new Intent(Intent.ACTION_VIEW);
        intent.setDataAndType(apkUri, "application/vnd.android.package-archive");
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        getContext().startActivity(intent);
        call.resolve(new JSObject().put("installing", true));
    }

    private static String toHex(byte[] bytes) {
        StringBuilder sb = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) {
            sb.append(String.format(Locale.US, "%02x", b));
        }
        return sb.toString();
    }
}
```

- [ ] **Step 3: MainActivity 注册插件**

```java
// MainActivity.onCreate 中 registerPlugin(LanDiscoveryPlugin.class); 之后追加
registerPlugin(AppUpdatePlugin.class);
```

- [ ] **Step 4: 编译验证**

Run: `cd frontend/android && export JAVA_HOME="D:\Program Files\Java\jdk-21" && export ANDROID_HOME="D:\Android\Sdk" && ./gradlew.bat assembleDebug --no-daemon`
Expected: BUILD SUCCESSFUL

- [ ] **Step 5: 提交**

```bash
git add frontend/android/app/src/main/java/com/openawa/mobile/AppUpdatePlugin.java frontend/android/app/src/main/AndroidManifest.xml frontend/android/app/src/main/res/xml/file_paths.xml frontend/android/app/src/main/java/com/openawa/mobile/MainActivity.java
git commit -m "[New] AppUpdatePlugin：versionCode 读取 + APK 下载/校验/安装 + 进度事件"
```

---

### Task 3: 前端 updateApi + useAppUpdate hook

**Files:**
- Create: `frontend/src/shared/api/updateApi.ts`
- Create: `frontend/src/shared/hooks/useAppUpdate.ts`
- Create: `frontend/src/__tests__/shared/hooks/useAppUpdate.test.ts`

- [ ] **Step 1: 写失败测试**

```ts
// frontend/src/__tests__/shared/hooks/useAppUpdate.test.ts
import '@testing-library/jest-dom/vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAppUpdate } from '@/shared/hooks/useAppUpdate'

vi.mock('@/shared/api/updateApi', () => ({
  checkForUpdate: vi.fn(),
  buildDownloadUrl: vi.fn(() => 'http://lan/api/system/apk/download'),
}))
vi.mock('@/shared/utils/platform', () => ({ isNativeApp: () => true }))
vi.mock('@capacitor/core', () => ({
  registerPlugin: vi.fn(() => ({
    getCurrentVersionCode: vi.fn(async () => ({ version_code: 1, version_name: '1.0' })),
    downloadAndInstall: vi.fn(),
    addListener: vi.fn(async () => ({ remove: vi.fn() })),
  })),
}))

import { checkForUpdate } from '@/shared/api/updateApi'

describe('useAppUpdate', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('无更新时状态为 idle 且不弹窗', async () => {
    vi.mocked(checkForUpdate).mockResolvedValue({ has_update: false } as never)
    const { result } = renderHook(() => useAppUpdate())
    await act(async () => { await result.current.check() })
    expect(result.current.status).toBe('idle')
    expect(result.current.updateInfo).toBeNull()
  })

  it('检测到更新时状态为 available 并携带元数据', async () => {
    vi.mocked(checkForUpdate).mockResolvedValue({
      has_update: true, latest_version: '1.0.1', latest_version_code: 2,
      apk_size: 1000, apk_sha256: 'a'.repeat(64), changelog: '修复',
      download_url: '/api/system/apk/download', published_at: '',
    } as never)
    const { result } = renderHook(() => useAppUpdate())
    await act(async () => { await result.current.check() })
    expect(result.current.status).toBe('available')
    expect(result.current.updateInfo?.latest_version).toBe('1.0.1')
  })

  it('用户点击稍后关闭后本次会话不再自动弹出', async () => {
    vi.mocked(checkForUpdate).mockResolvedValue({ has_update: true, latest_version: '1.0.1', latest_version_code: 2, apk_size: 1, apk_sha256: 'a'.repeat(64), changelog: '', download_url: '/x', published_at: '' } as never)
    const { result } = renderHook(() => useAppUpdate())
    await act(async () => { await result.current.check() })
    act(() => { result.current.dismiss() })
    expect(result.current.status).toBe('idle')
    // 再次 check 不应触发弹窗
    await act(async () => { await result.current.check() })
    expect(result.current.status).toBe('idle')
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run src/__tests__/shared/hooks/useAppUpdate.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 updateApi + hook**

```ts
// frontend/src/shared/api/updateApi.ts
import api from '@/shared/api/api'
import { API_BASE_URL } from '@/shared/api/client'

export interface UpdateInfo {
  has_update: boolean
  latest_version: string
  latest_version_code: number
  apk_size: number
  apk_sha256: string
  changelog: string
  download_url: string
  published_at: string
}

/** 调用后端更新检查接口（携带客户端 versionCode） */
export async function checkForUpdate(versionCode: number): Promise<UpdateInfo> {
  const { data } = await api.get('/system/update-check', { params: { version_code: versionCode } })
  return data
}

/** 构造 APK 下载绝对地址（APP 模式 API_BASE_URL 为局域网地址） */
export function buildDownloadUrl(downloadUrl: string): string {
  if (API_BASE_URL.startsWith('http')) {
    return `${API_BASE_URL.replace(/\/$/, '')}${downloadUrl}`
  }
  return downloadUrl
}
```

```ts
// frontend/src/shared/hooks/useAppUpdate.ts
import { useCallback, useEffect, useRef, useState } from 'react'
import { Capacitor } from '@capacitor/core'
import { appLogger } from '@/shared/utils/logger'
import { isNativeApp } from '@/shared/utils/platform'
import { checkForUpdate, buildDownloadUrl, type UpdateInfo } from '@/shared/api/updateApi'

export type UpdateStatus = 'idle' | 'checking' | 'available' | 'downloading' | 'installing' | 'error'

export interface UpdateProgress { loaded: number; total: number; percent: number }

interface AppUpdateState {
  status: UpdateStatus
  updateInfo: UpdateInfo | null
  progress: UpdateProgress | null
  error: string
  /** 用户已选择稍后（本次会话不再自动弹窗） */
  dismissed: boolean
  check: () => Promise<void>
  dismiss: () => void
  startDownload: () => Promise<void>
  reset: () => void
}

let _plugin: { getCurrentVersionCode: () => Promise<{ version_code: number; version_name: string }>; downloadAndInstall: (opts: Record<string, unknown>) => Promise<{ code?: string; installing?: boolean }>; addListener: (event: string, fn: (p: UpdateProgress) => void) => Promise<{ remove: () => void }> } | null = null

function getPlugin() {
  if (!isNativeApp()) return null
  if (!_plugin) {
    _plugin = Capacitor.isNativePlatform()
      ? (Capacitor as unknown as { Plugins: Record<string, never> }).Plugins['AppUpdate'] as never
      : null
    if (!_plugin) {
      // registerPlugin 类型化包装
      const { registerPlugin } = require('@capacitor/core') as typeof import('@capacitor/core')
      _plugin = registerPlugin('AppUpdate') as never
    }
  }
  return _plugin
}

export function useAppUpdate(): AppUpdateState {
  const [status, setStatus] = useState<UpdateStatus>('idle')
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null)
  const [progress, setProgress] = useState<UpdateProgress | null>(null)
  const [error, setError] = useState('')
  const [dismissed, setDismissed] = useState(false)
  const listenerRef = useRef<{ remove: () => void } | null>(null)
  const checkingRef = useRef(false)

  const check = useCallback(async () => {
    if (!isNativeApp() || checkingRef.current) return
    const plugin = getPlugin()
    if (!plugin) return
    checkingRef.current = true
    setStatus('checking')
    try {
      const { version_code } = await plugin.getCurrentVersionCode()
      const info = await checkForUpdate(version_code)
      if (info.has_update && !dismissed) {
        setUpdateInfo(info)
        setStatus('available')
      } else {
        setStatus('idle')
      }
    } catch (e) {
      appLogger.warning({ event: 'app_update_check_failed', module: 'app-update', message: String(e) })
      setStatus('idle')
    } finally {
      checkingRef.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dismissed])

  const startDownload = useCallback(async () => {
    const plugin = getPlugin()
    if (!plugin || !updateInfo) return
    setStatus('downloading')
    setProgress({ loaded: 0, total: updateInfo.apk_size, percent: 0 })
    try {
      const result = await plugin.downloadAndInstall({
        url: buildDownloadUrl(updateInfo.download_url),
        fileName: `openawa-${updateInfo.latest_version}.apk`,
        sha256: updateInfo.apk_sha256,
      })
      if (result.code === 'NEED_INSTALL_PERMISSION') {
        // 用户去系统设置授权后需要再次点击更新
        setStatus('available')
        setError('请在系统设置中允许安装未知来源应用后再次点击更新')
        return
      }
      setStatus('installing')
    } catch (e) {
      setStatus('error')
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [updateInfo])

  // 下载进度订阅
  useEffect(() => {
    const plugin = getPlugin()
    if (!plugin) return
    let active = true
    plugin.addListener('updateProgress', (p) => {
      if (active) setProgress(p)
    }).then((h) => { listenerRef.current = h })
    return () => {
      active = false
      listenerRef.current?.remove()
    }
  }, [])

  const dismiss = useCallback(() => {
    setDismissed(true)
    setStatus('idle')
  }, [])

  const reset = useCallback(() => {
    setDismissed(false)
    setStatus('idle')
    setUpdateInfo(null)
    setProgress(null)
    setError('')
  }, [])

  return { status, updateInfo, progress, error, dismissed, check, dismiss, startDownload, reset }
}
```

> 注意：上述 `getPlugin()` 中的 registerPlugin 调用方式需与项目现有插件调用风格（`lanDiscovery.ts` 的 `registerPlugin<...>('LanDiscovery')`）保持一致，类型化声明参照 `frontend/src/shared/api/lanDiscovery.ts` 的 `LanDiscoveryNativePlugin` interface 模式。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npx vitest run src/__tests__/shared/hooks/useAppUpdate.test.ts`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/shared/api/updateApi.ts frontend/src/shared/hooks/useAppUpdate.ts frontend/src/__tests__/shared/hooks/useAppUpdate.test.ts
git commit -m "[New] 前端更新检查 hook：useAppUpdate（检查/下载/安装状态机）"
```

---

### Task 4: UpdateDialog 弹窗组件

**Files:**
- Create: `frontend/src/shared/components/UpdateDialog/UpdateDialog.tsx`
- Create: `frontend/src/shared/components/UpdateDialog/UpdateDialog.module.css`
- Create: `frontend/src/__tests__/shared/components/UpdateDialog.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
// frontend/src/__tests__/shared/components/UpdateDialog.test.tsx
import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { UpdateDialog } from '@/shared/components/UpdateDialog/UpdateDialog'
import type { UpdateInfo } from '@/shared/api/updateApi'

const info: UpdateInfo = {
  has_update: true, latest_version: '1.0.1', latest_version_code: 2,
  apk_size: 1024 * 1024, apk_sha256: 'a'.repeat(64),
  changelog: '修复已知问题\n新增功能', download_url: '/api/system/apk/download', published_at: '',
}

describe('UpdateDialog', () => {
  it('展示版本号、changelog 与文件大小', () => {
    render(<UpdateDialog info={info} status="available" progress={null} onUpdate={vi.fn()} onLater={vi.fn()} />)
    expect(screen.getByText(/1\.0\.1/)).toBeInTheDocument()
    expect(screen.getByText(/修复已知问题/)).toBeInTheDocument()
    expect(screen.getByText(/1\.00 MB/)).toBeInTheDocument()
  })

  it('点击立即更新触发 onUpdate，点击稍后触发 onLater', () => {
    const onUpdate = vi.fn()
    const onLater = vi.fn()
    render(<UpdateDialog info={info} status="available" progress={null} onUpdate={onUpdate} onLater={onLater} />)
    fireEvent.click(screen.getByRole('button', { name: /立即更新/ }))
    expect(onUpdate).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: /稍后/ }))
    expect(onLater).toHaveBeenCalledTimes(1)
  })

  it('下载中显示进度百分比', () => {
    render(<UpdateDialog info={info} status="downloading" progress={{ loaded: 512 * 1024, total: 1024 * 1024, percent: 50 }} onUpdate={vi.fn()} onLater={vi.fn()} />)
    expect(screen.getByText(/50%/)).toBeInTheDocument()
  })

  it('错误状态显示错误信息', () => {
    render(<UpdateDialog info={info} status="error" progress={null} error="下载失败" onUpdate={vi.fn()} onLater={vi.fn()} />)
    expect(screen.getByText(/下载失败/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run src/__tests__/shared/components/UpdateDialog.test.tsx`
Expected: FAIL（组件不存在）

- [ ] **Step 3: 实现组件**

```tsx
// frontend/src/shared/components/UpdateDialog/UpdateDialog.tsx
import { useI18nStore } from '@/i18n'
import type { UpdateInfo } from '@/shared/api/updateApi'
import type { UpdateProgress, UpdateStatus } from '@/shared/hooks/useAppUpdate'
import styles from './UpdateDialog.module.css'

interface UpdateDialogProps {
  info: UpdateInfo
  status: UpdateStatus
  progress: UpdateProgress | null
  error?: string
  onUpdate: () => void
  onLater: () => void
}

function formatSize(bytes: number): string {
  if (bytes <= 0) return ''
  const mb = bytes / (1024 * 1024)
  return `${mb.toFixed(2)} MB`
}

/** APP 更新弹窗：版本信息 + changelog + 下载进度 + 立即更新/稍后 */
export function UpdateDialog({ info, status, progress, error, onUpdate, onLater }: UpdateDialogProps) {
  const { t } = useI18nStore()
  const downloading = status === 'downloading'
  const installing = status === 'installing'
  const failed = status === 'error'
  const percent = progress?.percent ?? 0

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-label={t('update.title')}>
      <div className={styles.dialog}>
        <div className={styles.icon}>⬆</div>
        <h2 className={styles.title}>{t('update.title')}</h2>
        <p className={styles.subtitle}>
          {t('update.currentToLatest', { latest: info.latest_version })}
        </p>
        {info.changelog && (
          <div className={styles.changelog}>
            <h3>{t('update.changelog')}</h3>
            <pre className={styles.changelogText}>{info.changelog}</pre>
          </div>
        )}
        <p className={styles.meta}>
          {t('update.packageSize')}: {formatSize(info.apk_size)}
        </p>

        {downloading && (
          <div className={styles.progressWrap}>
            <div className={styles.progressBar}>
              <div className={styles.progressFill} style={{ width: `${percent}%` }} />
            </div>
            <span className={styles.progressText}>{percent}%</span>
          </div>
        )}
        {installing && <p className={styles.installing}>{t('update.installing')}</p>}
        {failed && <p className={styles.error} role="alert">{error || t('update.downloadFailed')}</p>}

        <div className={styles.actions}>
          {!downloading && !installing && (
            <button type="button" className={styles.laterBtn} onClick={onLater} data-testid="update-later">
              {t('update.later')}
            </button>
          )}
          {!downloading && !installing && (
            <button type="button" className={styles.updateBtn} onClick={onUpdate} data-testid="update-now">
              {t('update.now')}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default UpdateDialog
```

```css
/* UpdateDialog.module.css —— 信号中枢主题延续 */
.overlay { position: fixed; inset: 0; z-index: var(--z-modal); background: var(--color-overlay); display: flex; align-items: center; justify-content: center; padding: var(--space-4); }
.dialog { width: 100%; max-width: 380px; background: var(--color-bg); border: 1px solid var(--color-border); border-radius: var(--radius-xl); padding: var(--space-6); box-shadow: var(--shadow-lg); }
.icon { width: 48px; height: 48px; border-radius: var(--radius-full); background: var(--color-primary-soft-bg); color: var(--color-primary); display: flex; align-items: center; justify-content: center; font-size: 1.5rem; margin-bottom: var(--space-4); }
.title { margin: 0 0 var(--space-1); font-size: var(--text-lg); }
.subtitle { margin: 0 0 var(--space-4); color: var(--color-text-secondary); font-size: var(--text-sm); }
.changelog { background: var(--color-bg-secondary); border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: var(--space-3); margin-bottom: var(--space-4); max-height: 160px; overflow-y: auto; }
.changelog h3 { margin: 0 0 var(--space-2); font-size: var(--text-xs); color: var(--color-text-tertiary); text-transform: uppercase; letter-spacing: 0.05em; }
.changelogText { margin: 0; font-size: var(--text-sm); line-height: var(--leading-relaxed); white-space: pre-wrap; font-family: inherit; }
.meta { margin: 0 0 var(--space-4); font-size: var(--text-xs); color: var(--color-text-tertiary); }
.progressWrap { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); }
.progressBar { flex: 1; height: 8px; border-radius: var(--radius-full); background: var(--color-bg-tertiary); overflow: hidden; }
.progressFill { height: 100%; background: var(--color-primary-gradient); border-radius: var(--radius-full); transition: width var(--transition-fast); }
.progressText { font-size: var(--text-sm); font-variant-numeric: tabular-nums; min-width: 40px; text-align: right; }
.installing { color: var(--color-success-strong); font-size: var(--text-sm); margin-bottom: var(--space-4); }
.error { color: var(--color-danger); font-size: var(--text-sm); margin-bottom: var(--space-4); }
.actions { display: flex; gap: var(--space-3); justify-content: flex-end; }
.laterBtn { padding: var(--space-2) var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: transparent; color: var(--color-text-secondary); font-size: var(--text-sm); }
.updateBtn { padding: var(--space-2) var(--space-5); border: none; border-radius: var(--radius-md); background: var(--color-primary); color: #fff; font-size: var(--text-sm); font-weight: 600; }
/* 移动端（≤768px，对应 --breakpoint-md）：弹窗贴边 */
@media (max-width: 768px) {
  .overlay { padding: var(--space-3); }
  .dialog { max-width: none; border-radius: var(--radius-lg); }
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npx vitest run src/__tests__/shared/components/UpdateDialog.test.tsx`
Expected: PASS（4 passed）
> 若 i18n 缺少 `update.*` 键导致断言失败，同步在 `frontend/src/i18n/locales/*.ts` 添加：title=发现新版本 / changelog=更新内容 / now=立即更新 / later=稍后 / currentToLatest=可更新至 {latest} / packageSize=安装包大小 / installing=正在安装… / downloadFailed=下载失败（4 语言各一份）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/shared/components/UpdateDialog/ frontend/src/__tests__/shared/components/UpdateDialog.test.tsx frontend/src/i18n/locales/
git commit -m "[New] UpdateDialog 更新弹窗：版本/changelog/进度/立即更新/稍后"
```

---

### Task 5: 接入（启动自动检查 + 设置页入口 + App 挂载）

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/features/settings/SettingsPage.tsx`（或对应 Tab Container）

- [ ] **Step 1: App.tsx 挂载自动检查**

```tsx
// frontend/src/App.tsx 内（已认证后触发；参照 useAppInitialization 的调用时机）
import { useAppUpdate } from '@/shared/hooks/useAppUpdate'
import { UpdateDialog } from '@/shared/components/UpdateDialog/UpdateDialog'

// 在 App 组件内：
const { status, updateInfo, progress, error, check, dismiss, startDownload } = useAppUpdate()

// 认证完成后自动检查一次：
useEffect(() => {
  if (isAuthenticated) {
    void check()
  }
}, [isAuthenticated, check])

// 渲染（认证后且 available/downloading/installing/error 时弹窗）：
{isAuthenticated && updateInfo && (status === 'available' || status === 'downloading' || status === 'installing' || status === 'error') && (
  <UpdateDialog
    info={updateInfo}
    status={status}
    progress={progress}
    error={error}
    onUpdate={() => void startDownload()}
    onLater={dismiss}
  />
)}
```

> 注意：`isAuthenticated` 从 `useAuthStore` 读取（App.tsx 已有订阅）；`useAppUpdate` 内部已用 `isNativeApp()` 守卫（Web 端不检查不弹窗）。

- [ ] **Step 2: 设置页"检查更新"入口**

在设置页（`SettingsPage.tsx` 的顶部操作区或"通用设置"容器）添加按钮：

```tsx
<button
  type="button"
  onClick={() => void check()}
  disabled={status === 'checking'}
  className={styles['check-update-btn']}
>
  {status === 'checking' ? '检查中…' : '检查更新'}
</button>
```

> 按钮与 `check/status` 通过 `useAppUpdate()` 在设置页组件内获取；APP 模式下显示，Web 端隐藏（`isNativeApp()` 守卫）。设置页的样式遵循 `SettingsPage.module.css` 既有按钮模式。

- [ ] **Step 3: 前端全量测试**

Run: `cd frontend && npx vitest run`
Expected: PASS（原有 677 + 新增用例全过）

- [ ] **Step 4: 提交**

```bash
git add frontend/src/App.tsx frontend/src/features/settings/
git commit -m "[New] APP 更新接入：启动自动检查 + 设置页手动检查入口"
```

---

### Task 6: 部署脚本 release-apk.ps1

**Files:**
- Create: `frontend/scripts/release-apk.ps1`

- [ ] **Step 1: 实现脚本**

```powershell
# frontend/scripts/release-apk.ps1
# 用途：构建 APP 更新包并部署到后端 var/apk/（生成 manifest.json）
# 用法：powershell -ExecutionPolicy Bypass -File scripts/release-apk.ps1 [-Changelog "修复说明"] [-VersionCode 2]
param(
    [string]$Changelog = "",
    [int]$VersionCode = 0
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot   # frontend/
$backendApkDir = Join-Path $root "..\backend\var\apk"
$apkOut = Join-Path $root "android\app\build\outputs\apk\debug\app-debug.apk"
$manifestPath = Join-Path $backendApkDir "manifest.json"

# 1. 读取 package.json 版本
$pkg = Get-Content (Join-Path $root "package.json") -Raw | ConvertFrom-Json
$version = $pkg.version
Write-Host "构建版本: $version"

# 2. versionCode：显式参数优先，否则从上个 manifest 递增
if ($VersionCode -eq 0) {
    if (Test-Path $manifestPath) {
        $old = Get-Content $manifestPath -Raw | ConvertFrom-Json
        $VersionCode = [int]$old.version_code + 1
    } else {
        $VersionCode = 1
    }
}
Write-Host "versionCode: $VersionCode"

# 3. 同步 build.gradle
$gradle = Join-Path $root "android\app\build.gradle"
$content = Get-Content $gradle -Raw
$content = $content -replace 'versionCode \d+', "versionCode $VersionCode"
$content = $content -replace 'versionName "[^"]+"', "versionName `"$version`""
Set-Content -Path $gradle -Value $content -Encoding UTF8

# 4. 构建 APK
Push-Location (Join-Path $root "android")
try {
    $env:JAVA_HOME = "D:\Program Files\Java\jdk-21"
    $env:ANDROID_HOME = "D:\Android\Sdk"
    & ".\gradlew.bat" assembleDebug --no-daemon
    if ($LASTEXITCODE -ne 0) { throw "gradle 构建失败" }
} finally {
    Pop-Location
}

# 5. 计算 sha256 / size
$sha = (Get-FileHash $apkOut -Algorithm SHA256).Hash.ToLower()
$size = (Get-Item $apkOut).Length
$apkName = "openawa-$version.apk"

# 6. 部署到后端 var/apk/
New-Item -ItemType Directory -Force -Path $backendApkDir | Out-Null
Copy-Item $apkOut (Join-Path $backendApkDir $apkName) -Force
Remove-Item (Join-Path $backendApkDir "openawa-*.apk") -Force -ErrorAction SilentlyContinue -Exclude $apkName

# 7. 生成 manifest.json
$manifest = @{
    version = $version
    version_code = $VersionCode
    apk = $apkName
    apk_size = $size
    apk_sha256 = $sha
    changelog = $Changelog
    published_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz")
} | ConvertTo-Json
Set-Content -Path $manifestPath -Value $manifest -Encoding UTF8

Write-Host "部署完成: $manifestPath"
Write-Host "APK: $apkName ($size bytes, sha256=$sha)"
```

- [ ] **Step 2: 运行验证**

Run: `cd frontend && powershell -ExecutionPolicy Bypass -File scripts/release-apk.ps1 -Changelog "测试更新"`
Expected: 输出构建成功 + `backend/var/apk/manifest.json` 生成（version_code=1）

- [ ] **Step 3: 后端接口联调**

Run: `curl -s "http://localhost:8000/api/system/update-check?version_code=0" -H "Authorization: Bearer $API_KEY"`
Expected: `{"has_update": true, "latest_version_code": 1, ...}`

- [ ] **Step 4: 提交**

```bash
git add frontend/scripts/release-apk.ps1
git commit -m "[New] release-apk 部署脚本：版本同步 + 构建 + manifest 生成 + 部署"
```

---

### Task 7: E2E 完整更新闭环验证

**Files:** 无（验证步骤）

- [ ] **Step 1: 部署 v1（当前版本作为旧版基线）**

当前模拟器 APP 为 versionCode=1。确保 `backend/var/apk/manifest.json` 存在（Task 6 已生成 version_code=1）。

- [ ] **Step 2: 构建并部署 v2（version_code=2）**

Run: `cd frontend && powershell -ExecutionPolicy Bypass -File scripts/release-apk.ps1 -Changelog "修复终端配额问题" -VersionCode 2`
Expected: manifest version_code=2

- [ ] **Step 3: 后端重启加载新 manifest 缓存**

Run: 重启后端（kill 8000 进程 → `.venv/Scripts/python.exe main.py`），或等待缓存 60s 过期后直接请求
Expected: `curl ".../api/system/update-check?version_code=1"` → `has_update: true`

- [ ] **Step 4: APP 检测更新**

模拟器 APP（versionCode=1）重启 → 自动检查 → 弹窗出现：
Run: `adb shell uiautomator dump` 或 CDP `document.body.innerText` 含"发现新版本"/"立即更新"

- [ ] **Step 5: 点击立即更新 → 下载 → 安装**

CDP 点击"立即更新" → 等待下载完成（进度 100%）→ 系统安装界面弹出（adb 验证前台 activity 为 PackageInstaller）→ 点击"安装" → APP 升级完成

Run: `adb shell dumpsys window | grep mCurrentFocus`（应显示 PackageInstaller 或安装确认）
Run: 安装完成后 `adb shell dumpsys package com.openawa.mobile | grep versionName` → `versionName=1.0.1`

- [ ] **Step 6: 回归确认**

- 更新后 APP 正常启动、登录态保留（API Key localStorage）
- `update-check?version_code=2` → `has_update: false`（新版本不再提示）
- 前端 677+ 测试全过、后端 system 测试全过

- [ ] **Step 7: 提交验证脚本与文档**

```bash
git add docs/superpowers/plans/2026-08-07-app-lan-update.md
git commit -m "[Documentation] APP 局域网 OTA 更新实施计划"
```

---

## Self-Review

**Spec coverage:**
- ✅ 后端提供版本元数据 → Task 1（update-check）
- ✅ APK 托管 → Task 1（apk/download）+ Task 6（部署脚本）
- ✅ APP 检测更新 → Task 3（useAppUpdate 启动检查）+ Task 5（App.tsx 挂载）
- ✅ 用户选择是否更新 → Task 4（UpdateDialog 立即更新/稍后）+ Task 3（dismissed 会话内不重复弹）
- ✅ 下载/校验/安装 → Task 2（AppUpdatePlugin：下载+SHA256+FileProvider+ACTION_VIEW）
- ✅ 版本对比 → Task 1（version_code 对比）+ Task 3（插件读 BuildConfig.VERSION_CODE）
- ✅ 进度反馈 → Task 2（updateProgress 事件）+ Task 3（progress 状态）+ Task 4（进度条）
- ✅ E2E 验证 → Task 7

**风险与注意：**
- Capacitor 插件事件：`notifyListeners` 需要前端先 `addListener`；Android 原生线程中调用需通过 `bridge` 主线程 —— 实现时若进度事件不触发，改在 `Plugin` 的 `notifyListeners`（内部已处理线程安全）
- `registerPlugin` 的 TS 类型：参照 `lanDiscovery.ts` 定义 `AppUpdatePlugin` interface
- i18n：UpdateDialog 用 `t('update.*')`，需同步 4 语言文件
- 安装权限：Android 8+ 首次点击更新会先跳系统"安装未知应用"设置，用户返回后需再次点击"立即更新"（Task 3 已处理 NEED_INSTALL_PERMISSION 分支）
- 旧版 APP 兼容：ping 的 `capabilities` 可加 `app_update: true` 标识新后端能力（可选）
