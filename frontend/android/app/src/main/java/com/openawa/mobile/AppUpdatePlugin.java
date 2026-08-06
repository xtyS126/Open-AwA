package com.openawa.mobile;

import android.content.ActivityNotFoundException;
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
import java.security.MessageDigest;
import java.util.Locale;

/**
 * APP 更新插件：读取本地 versionCode、下载 APK 到 cacheDir、SHA256 校验、
 * FileProvider 暴露并触发系统安装界面。
 *
 * 安全设计：
 * - APK 下载走 HTTP(S)（局域网），Authorization Bearer 头传递 API Key，token 不入 URL
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

        // Android 8+ 需要"安装未知应用"权限；无权限时引导到系统设置页
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                && !getContext().getPackageManager().canRequestPackageInstalls()) {
            JSObject err = new JSObject();
            err.put("code", "NEED_INSTALL_PERMISSION");
            err.put("message", "需要授予安装未知应用权限");
            call.resolve(err);
            try {
                Intent intent = new Intent(
                        Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:" + getContext().getPackageName()));
                getActivity().startActivity(intent);
            } catch (ActivityNotFoundException e) {
                Log.w(TAG, "无法打开未知来源设置页", e);
            }
            return;
        }

        new Thread(() -> {
            try {
                File apkFile = download(url, fileName, sha256, authToken);
                install(apkFile, call);
            } catch (Exception e) {
                Log.e(TAG, "download/install failed", e);
                call.reject(e.getMessage());
            }
        }).start();
    }

    private File download(String url, String fileName, String sha256, String authToken) throws Exception {
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

        try (InputStream in = conn.getInputStream();
             FileOutputStream out = new FileOutputStream(apkFile)) {
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
                apkFile);
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
