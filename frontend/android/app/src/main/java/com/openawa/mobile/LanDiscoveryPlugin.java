package com.openawa.mobile;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.SocketException;
import java.util.Collections;
import java.util.List;

/**
 * 局域网发现辅助插件：返回本机 IPv4 地址与网段前缀长度。
 * 前端据此枚举同一 /24 网段的候选主机，并发探测 Open-AwA 后端。
 *
 * 网段推导采用保守策略：仅按地址类别推断（10/8、172.16-31/12、192.168/16），
 * 扫描时前端只枚举与自身同网段的相邻 /24（家庭/办公典型布局），
 * 避免对超大网段（10.x、172.x）发起不可控的全量扫描。
 */
@CapacitorPlugin(name = "LanDiscovery")
public class LanDiscoveryPlugin extends Plugin {

    @PluginMethod
    public void getNetworkInfo(PluginCall call) {
        JSObject result = new JSObject();
        result.put("info", findBestIpv4());
        call.resolve(result);
    }

    private JSObject findBestIpv4() {
        try {
            List<NetworkInterface> interfaces = Collections.list(NetworkInterface.getNetworkInterfaces());
            // 优先物理接口（wlan0/eth0 等），跳过回环、点对点（VPN）与未启动接口
            for (NetworkInterface nif : interfaces) {
                if (!nif.isUp() || nif.isLoopback() || nif.isPointToPoint()) {
                    continue;
                }
                for (InetAddress addr : Collections.list(nif.getInetAddresses())) {
                    if (!(addr instanceof Inet4Address)) {
                        continue;
                    }
                    Inet4Address ipv4 = (Inet4Address) addr;
                    if (ipv4.isLoopbackAddress() || ipv4.isLinkLocalAddress()) {
                        continue;
                    }
                    byte[] bytes = ipv4.getAddress();
                    int first = bytes[0] & 0xff;
                    int second = bytes[1] & 0xff;
                    int prefix;
                    if (first == 10) {
                        prefix = 8;
                    } else if (first == 172 && second >= 16 && second <= 31) {
                        prefix = 12;
                    } else if (first == 192 && second == 168) {
                        prefix = 16;
                    } else {
                        prefix = 24;
                    }
                    JSObject obj = new JSObject();
                    obj.put("ip", ipv4.getHostAddress());
                    obj.put("prefixLength", prefix);
                    obj.put("interfaceName", nif.getName());
                    return obj;
                }
            }
        } catch (SocketException e) {
            // 网卡枚举失败时返回 null，由前端降级为手动输入模式
        }
        return null;
    }
}
