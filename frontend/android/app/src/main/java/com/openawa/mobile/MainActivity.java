package com.openawa.mobile;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        // 显式注册自定义插件（局域网发现）。
        // 工程内自定义插件虽带 @CapacitorPlugin 注解，但 Capacitor 8 的
        // 注解自动扫描对未列入 capacitor.plugins.json 的插件不保证发现，
        // 显式注册确保 Bridge 在加载页面 WebView 前完成插件注入。
        registerPlugin(LanDiscoveryPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
