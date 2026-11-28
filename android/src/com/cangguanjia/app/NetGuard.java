package com.cangguanjia.app;

import java.util.Locale;

/**
 * 出网白名单：只允许与「同一局域网内的自己人」通信。
 *
 * 为什么需要它：本应用的数据共享走局域网明文 HTTP（电脑端是自签/无证书的简易服务，
 * 上 TLS 需要用户手动信任证书，落地成本高）。明文本身不可怕，可怕的是**明文发到公网**。
 * 因此这里在 WebView 层做硬拦截：只放行私有网段 IPv4、localhost、以及不含公网后缀的
 * 单标签主机名（如 my-pc / nas.local）。任何 example.com、公网 IP 一律拒绝，
 * 避免页面被篡改后把库存数据外传。
 *
 * 依据：《网络安全法》第二十三条（防范网络攻击的技术措施）、第二十四条（产品服务安全维护）、
 *       《个人信息保护法》第五十一条（采取相应的加密、访问控制等技术措施）。
 */
public final class NetGuard {

    private NetGuard() {
    }

    /**
     * v1.45.7 云更新：检查更新需要拉 GitHub 上的版本信息文件（只读 JSON，
     * 不发送库存数据；APK 下载走系统浏览器，不经 WebView）。
     * 白名单精确到这两个只读域名，其余公网域名一律照旧拒绝。
     */
    private static final String[] UPDATE_HOSTS = {
            "raw.githubusercontent.com",
            "api.github.com",
    };

    /** URL 是否允许加载/请求。非 http(s)（如 file:// 本地页面）直接放行。 */
    static boolean allow(String url) {
        if (url == null || url.length() == 0) {
            return true;
        }
        String u = url.toLowerCase(Locale.ROOT);
        String host;
        if (u.startsWith("http://")) {
            host = u.substring(7);
        } else if (u.startsWith("https://")) {
            host = u.substring(8);
        } else {
            return true;                       // file://、data:、blob: 等本地资源
        }
        int cut = host.length();
        int slash = host.indexOf('/');
        if (slash >= 0 && slash < cut) cut = slash;
        int q = host.indexOf('?');
        if (q >= 0 && q < cut) cut = q;
        int hash = host.indexOf('#');
        if (hash >= 0 && hash < cut) cut = hash;
        host = host.substring(0, cut);
        int at = host.lastIndexOf('@');
        if (at >= 0) {
            host = host.substring(at + 1);     // 防 user@host 混淆
        }
        if (host.startsWith("[")) {            // IPv6 字面量
            int end = host.indexOf(']');
            String v6 = end > 0 ? host.substring(1, end) : host;
            return "::1".equals(v6) || v6.startsWith("fe80:") || v6.startsWith("fc")
                    || v6.startsWith("fd");
        }
        int colon = host.indexOf(':');
        if (colon >= 0) {
            host = host.substring(0, colon);   // 去端口
        }
        for (String h : UPDATE_HOSTS) {        // 云更新：只读版本检查
            if (h.equals(host)) {
                return true;
            }
        }
        return isLanHost(host);
    }

    /** 私有网段 IPv4 / localhost / 单标签主机名 / .local 等局域网域名。 */
    static boolean isLanHost(String host) {
        if (host == null || host.length() == 0) {
            return false;
        }
        if ("localhost".equals(host)) {
            return true;
        }
        if (isIpv4(host)) {
            return isPrivateIpv4(host);
        }
        if (host.indexOf('.') < 0) {
            return true;                       // my-pc、desktop 这类内网单标签名
        }
        return host.endsWith(".local") || host.endsWith(".lan")
                || host.endsWith(".home") || host.endsWith(".home.arpa")
                || host.endsWith(".internal");
    }

    private static boolean isIpv4(String s) {
        String[] p = s.split("\\.", -1);
        if (p.length != 4) {
            return false;
        }
        for (String seg : p) {
            if (seg.length() == 0 || seg.length() > 3) {
                return false;
            }
            for (int i = 0; i < seg.length(); i++) {
                if (seg.charAt(i) < '0' || seg.charAt(i) > '9') {
                    return false;
                }
            }
            if (Integer.parseInt(seg) > 255) {
                return false;
            }
        }
        return true;
    }

    private static boolean isPrivateIpv4(String s) {
        String[] p = s.split("\\.");
        int a = Integer.parseInt(p[0]);
        int b = Integer.parseInt(p[1]);
        if (a == 10) return true;                       // 10.0.0.0/8
        if (a == 127) return true;                      // 环回
        if (a == 192 && b == 168) return true;          // 192.168.0.0/16
        if (a == 172 && b >= 16 && b <= 31) return true; // 172.16.0.0/12
        if (a == 169 && b == 254) return true;          // 链路本地
        return false;
    }
}
