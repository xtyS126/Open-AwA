# OpenClaw Weixin 插件深度技术研究文档

## 概述

open-weixin 是 OpenClaw 框架的微信渠道插件，实现了通过微信扫码完成登录授权，并与 OpenClaw 的 AI 代理系统集成的完整功能。该插件基于 iLink API 协议，支持长轮询获取消息、发送多媒体消息、会话上下文管理等功能。

版本兼容性：
- 插件版本 2.0.x 要求 OpenClaw >= 2026.3.22
- 插件版本 1.0.x 支持 OpenClaw >= 2026.1.0 < 2026.3.22

---

## 第一章：系统架构总览

### 1.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        OpenClaw Gateway                              │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    openclaw-weixin 插件                         │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐   │ │
│  │  │   channel   │  │   monitor   │  │  messaging pipeline  │   │ │
│  │  │  (入口/配置) │  │  (长轮询循环) │  │  (消息处理/回复)     │   │ │
│  │  └─────────────┘  └─────────────┘  └─────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      iLink API Server                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │
│  │ getUpdates  │  │sendMessage  │  │ getUploadUrl│  │sendTyping │ │
│  │  (长轮询)   │  │  (消息发送)  │  │(CDN预签名)  │  │(输入状态) │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └──────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Weixin CDN                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │
│  │   图片上传   │  │   视频上传   │  │   文件上传   │                 │
│  │ (AES加密)   │  │ (AES加密)   │  │ (AES加密)   │                 │
│  └─────────────┘  └─────────────┘  └─────────────┘                 │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 源码目录结构

```
openclaw-weixin/
├── index.ts                    # 插件入口，注册渠道和CLI命令
├── src/
│   ├── channel.ts              # 渠道插件主定义（认证/出站/状态）
│   ├── runtime.ts              # 全局运行时管理
│   ├── compat.ts                # 版本兼容性检查
│   ├── weixin-cli.ts           # CLI命令注册
│   │
│   ├── auth/                    # 认证模块
│   │   ├── login-qr.ts         # 二维码登录核心逻辑
│   │   ├── pairing.ts          # 用户配对与allowFrom管理
│   │   └── accounts.ts         # 账号数据存储与解析
│   │
│   ├── api/                     # API通信模块
│   │   ├── api.ts              # 底层HTTP请求封装
│   │   ├── types.ts            # API类型定义
│   │   ├── config-cache.ts     # 配置缓存
│   │   └── session-guard.ts    # 会话保护机制
│   │
│   ├── messaging/               # 消息处理模块
│   │   ├── send.ts             # 出站消息发送
│   │   ├── send-media.ts       # 媒体消息发送
│   │   ├── inbound.ts          # 入站消息解析
│   │   ├── process-message.ts  # 消息处理主流程
│   │   ├── slash-commands.ts   # 斜杠指令处理
│   │   ├── error-notice.ts     # 错误通知
│   │   └── debug-mode.ts       # 调试模式
│   │
│   ├── cdn/                     # CDN处理模块
│   │   ├── upload.ts           # CDN上传主逻辑
│   │   ├── cdn-upload.ts      # CDN上传实现
│   │   ├── pic-decrypt.ts      # 图片解密下载
│   │   ├── cdn-url.ts         # CDN URL构建
│   │   └── aes-ecb.ts          # AES加密工具
│   │
│   ├── media/                   # 媒体处理模块
│   │   ├── media-download.ts   # 媒体下载
│   │   ├── silk-transcode.ts   # SILK语音转码
│   │   └── mime.ts             # MIME类型判断
│   │
│   ├── storage/                 # 存储模块
│   │   ├── sync-buf.ts         # getUpdates游标持久化
│   │   └── state-dir.ts        # 状态目录管理
│   │
│   ├── monitor/                 # 监控模块
│   │   └── monitor.ts          # 长轮询监控主循环
│   │
│   └── util/                    # 工具模块
│       ├── logger.ts           # 结构化日志
│       ├── redact.ts           # 敏感信息脱敏
│       └── random.ts           # 随机ID生成
│
└── weixin-ilink/               # 独立客户端库（精简版）
    ├── src/
    │   ├── client.ts           # ILinkClient类
    │   ├── auth.ts             # 登录认证
    │   ├── api.ts              # API函数
    │   ├── types.ts            # 类型定义
    │   └── index.ts            # 导出入口
    └── README.md               # 使用文档
```

---

## 第二章：认证与登录系统

### 2.1 扫码登录流程

插件采用 QR Code 扫码授权方式完成微信账号与 OpenClaw 的绑定。整个登录流程涉及三个核心模块：`login-qr.ts`（登录逻辑）、`accounts.ts`（账号存储）、`pairing.ts`（用户配对）。

#### 2.1.1 登录状态机

```typescript
// 登录状态定义
type LoginStatus = "wait" | "scaned" | "confirmed" | "expired" | "scaned_but_redirect";
```

| 状态 | 说明 | 客户端行为 |
|------|------|-----------|
| wait | 等待扫码 | 显示/刷新二维码 |
| scaned | 已扫码待确认 | 提示用户确认 |
| scaned_but_redirect | 扫码后需切换IDC | 切换轮询服务器地址 |
| confirmed | 授权确认完成 | 保存凭证，登录成功 |
| expired | 二维码过期 | 自动刷新二维码 |

#### 2.1.2 二维码获取

```typescript
// 核心流程
async function fetchQRCode(apiBaseUrl: string, botType: string): Promise<QRCodeResponse> {
  // 使用固定URL获取二维码
  const url = `${apiBaseUrl}/ilink/bot/get_bot_qrcode?bot_type=${botType}`;
  const response = await fetch(url);
  return response.json();
}
```

二维码请求的关键参数：
- **固定API地址**: `https://ilinkai.weixin.qq.com`
- **bot_type**: 默认值 `"3"`，标识为机器人类型

响应数据结构：
```typescript
interface QRCodeResponse {
  qrcode: string;           // 二维码标识（轮询用）
  qrcode_img_content: string; // 二维码图片URL（展示用）
}
```

#### 2.1.3 状态轮询机制

```typescript
// 轮询状态检查
async function pollQRStatus(apiBaseUrl: string, qrcode: string): Promise<StatusResponse> {
  const url = `${apiBaseUrl}/ilink/bot/get_qrcode_status?qrcode=${encodeURIComponent(qrcode)}`;
  // 长轮询超时35秒
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 35000);
  // ...
}
```

状态轮询特性：
- **长轮询超时**: 35秒（服务端hold连接）
- **客户端超时**: 客户端也设置35秒超时保护
- **自动重试**: 网络错误返回 `wait` 状态继续轮询
- **二维码刷新**: 最多3次自动刷新机会

#### 2.1.4 IDC重定向处理

当服务器返回 `scaned_but_redirect` 状态时，需要切换轮询的目标地址：

```typescript
case "scaned_but_redirect": {
  const redirectHost = statusResponse.redirect_host;
  if (redirectHost) {
    const newBaseUrl = `https://${redirectHost}`;
    activeLogin.currentApiBaseUrl = newBaseUrl;
    logger.info(`IDC redirect, switching to: ${redirectHost}`);
  }
  break;
}
```

### 2.2 凭证管理与存储

#### 2.2.1 账号数据结构

```typescript
type WeixinAccountData = {
  token?: string;           // Bot认证令牌
  savedAt?: string;         // 保存时间戳
  baseUrl?: string;         // API服务器地址
  userId?: string;          // 微信用户ID
};
```

#### 2.2.2 存储路径设计

```
~/.openclaw/
├── openclaw.json                    # 主配置文件
├── openclaw-weixin/
│   ├── accounts.json                # 账号索引
│   └── accounts/
│       ├── {accountId}.json         # 账号凭证
│       ├── {accountId}.sync.json    # getUpdates游标
│       └── {accountId}.context-tokens.json  # 会话上下文
└── credentials/
    └── openclaw-weixin-{accountId}-allowFrom.json  # 授权用户列表
```

#### 2.2.3 账号ID规范化

插件将微信原始ID（如 `wxid_xxxxx@im.bot`）规范化为文件系统安全格式：

```typescript
// 原始ID: "wxid_xxxxx@im.bot"
// 规范化ID: "wxid_xxxxx-im-bot"
export function normalizeAccountId(raw: string): string {
  return raw.replace(/[@.]/g, "-");
}
```

### 2.3 用户配对与授权

#### 2.3.1 配对机制

首次扫码登录成功后，系统自动将扫码用户的 `ilink_user_id` 注册到 allowFrom 列表：

```typescript
export async function registerUserInFrameworkStore(params: {
  accountId: string;
  userId: string;
}): Promise<{ changed: boolean }> {
  // 写入 credentials/openclaw-weixin-{accountId}-allowFrom.json
  // 使用文件锁保证并发安全
}
```

#### 2.3.2 授权检查流程

消息处理时，系统检查发送者是否在 allowFrom 列表中：

```typescript
const { senderAllowedForCommands, commandAuthorized } =
  await resolveSenderCommandAuthorizationWithRuntime({
    cfg: deps.config,
    rawBody,
    isGroup: false,
    dmPolicy: "pairing",  // 私聊使用配对策略
    configuredAllowFrom: [],
    readAllowFromStore: async () => {
      const fromStore = readFrameworkAllowFromList(deps.accountId);
      if (fromStore.length > 0) return fromStore;
      // 兼容旧版本：回退到账号userId
      const uid = loadWeixinAccount(deps.accountId)?.userId;
      return uid ? [uid] : [];
    },
  });
```

---

## 第三章：API通信协议

### 3.1 协议概述

插件通过 HTTP JSON API 与 iLink 后端通信。所有请求均为 POST（除二维码相关为GET），请求响应均为 JSON 格式。

#### 3.1.1 通用请求头

| Header | 值 | 说明 |
|--------|-----|------|
| Content-Type | application/json | 请求体格式 |
| AuthorizationType | ilink_bot_token | 认证类型 |
| Authorization | Bearer {token} | Bot令牌 |
| X-WECHAT-UIN | base64(uint32) | 随机标识 |
| iLink-App-Id | bot | 应用标识 |
| iLink-App-ClientVersion | 0x00MMNNPP | 客户端版本 |

#### 3.1.2 BaseInfo机制

每个API请求都包含 `base_info` 字段：

```typescript
export function buildBaseInfo(): BaseInfo {
  return { channel_version: "2.1.1" };
}
```

### 3.2 核心API接口

#### 3.2.1 getUpdates（长轮询获取消息）

**用途**: 长轮询方式获取新消息，是插件的核心入站通道。

**请求**:
```json
POST /ilink/bot/getupdates
{
  "get_updates_buf": "",      // 上次响应的游标
  "base_info": {
    "channel_version": "2.1.1"
  }
}
```

**响应**:
```json
{
  "ret": 0,
  "msgs": [...],
  "get_updates_buf": "<新游标>",
  "longpolling_timeout_ms": 35000
}
```

**关键特性**:
- 服务端会hold请求直到有新消息或超时
- `get_updates_buf` 必须持久化，下次请求回传
- 客户端应遵循服务端返回的 `longpolling_timeout_ms`

#### 3.2.2 sendMessage（发送消息）

**用途**: 发送文本、图片、视频、文件等消息。

**请求**:
```json
POST /ilink/bot/sendmessage
{
  "msg": {
    "to_user_id": "wxid_xxxxx@im.wechat",
    "context_token": "xxx",
    "item_list": [
      {
        "type": 1,
        "text_item": { "text": "Hello" }
      }
    ]
  }
}
```

**消息类型值**:
| type值 | 含义 |
|--------|------|
| 1 | TEXT（文本） |
| 2 | IMAGE（图片） |
| 3 | VOICE（语音） |
| 4 | FILE（文件） |
| 5 | VIDEO（视频） |

#### 3.2.3 getUploadUrl（获取CDN上传预签名）

**用途**: 上传媒体文件前获取CDN上传地址和参数。

**请求**:
```json
{
  "filekey": "随机16字节hex",
  "media_type": 1,            // 1=IMAGE, 2=VIDEO, 3=FILE
  "to_user_id": "xxx",
  "rawsize": 12345,           // 原文件大小
  "rawfilemd5": "md5...",    // 原文件MD5
  "filesize": 12352,         // AES加密后大小
  "thumb_rawsize": 1024,     // 缩略图大小
  "aeskey": "16字节hex"      // AES密钥
}
```

**响应**:
```json
{
  "upload_param": "<加密参数>",
  "thumb_upload_param": "<缩略图加密参数>",
  "upload_full_url": "<完整上传URL>"  // 新版API直接返回
}
```

#### 3.2.4 getConfig（获取配置）

**用途**: 获取用户相关的配置信息，包括 typing_ticket。

**请求**:
```json
{
  "ilink_user_id": "xxx",
  "context_token": "xxx"
}
```

**响应**:
```json
{
  "ret": 0,
  "typing_ticket": "<base64编码的typing票据>"
}
```

#### 3.2.5 sendTyping（发送输入状态）

**用途**: 向用户发送"正在输入"或"取消输入"状态。

**请求**:
```json
{
  "ilink_user_id": "xxx",
  "typing_ticket": "<from getConfig>",
  "status": 1  // 1=正在输入, 2=取消输入
}
```

### 3.3 API超时配置

| 接口类型 | 默认超时 | 说明 |
|----------|----------|------|
| getUpdates | 35秒 | 长轮询等待 |
| sendMessage | 15秒 | 普通API |
| getUploadUrl | 15秒 | 文件上传前 |
| getConfig | 10秒 | 配置获取 |
| sendTyping | 10秒 | 状态通知 |

---

## 第四章：消息处理流程

### 4.1 入站消息处理

#### 4.1.1 消息结构解析

```typescript
interface WeixinMessage {
  seq?: number;              // 消息序列号
  message_id?: number;        // 消息唯一ID
  from_user_id?: string;      // 发送者ID
  to_user_id?: string;        // 接收者ID
  create_time_ms?: number;     // 创建时间戳
  session_id?: string;        // 会话ID
  message_type?: number;      // 1=USER, 2=BOT
  message_state?: number;     // 0=NEW, 1=GENERATING, 2=FINISH
  item_list?: MessageItem[];  // 消息内容
  context_token?: string;     // 会话上下文令牌
}
```

#### 4.1.2 消息体提取

```typescript
function bodyFromItemList(itemList?: MessageItem[]): string {
  for (const item of itemList) {
    // 优先提取文本内容
    if (item.type === MessageItemType.TEXT) {
      return item.text_item.text;
    }
    // 语音消息：提取转文字内容
    if (item.type === MessageItemType.VOICE && item.voice_item?.text) {
      return item.voice_item.text;
    }
  }
  return "";
}
```

### 4.2 斜杠指令系统

插件内置两个斜杠指令：

#### 4.2.1 /echo 指令

直接回复消息内容，不经过AI处理，用于测试通道延迟：

```
用户发送: /echo 你好
插件回复: 你好
插件回复: ⏱ 通道耗时
          ├ 事件时间: 2024-01-01T12:00:00.000Z
          ├ 平台→插件: 500ms
          └ 插件处理: 100ms
```

#### 4.2.2 /toggle-debug 指令

开启/关闭调试模式，开启后每条AI回复追加全链路耗时：

```
用户发送: /toggle-debug
插件回复: Debug 模式已开启
```

调试输出示例：
```
⏱ Debug 全链路
── 收消息 ──
│ seq=123 msgId=456 from=wxid_xxx
│ body="帮我写一段代码" (len=6) itemTypes=[1]
── 鉴权 & 路由 ──
│ auth: cmdAuthorized=true senderAllowed=true
│ route: agent=gpt-4 session=xxx
── 回复 ──
│ textLen=500 media=none
├ deliver耗时: 2000ms
── 耗时 ──
├ 平台→插件: 500ms
├ 入站处理(auth+route+media): 150ms
├ AI生成+回复: 3000ms
├ 总耗时: 3650ms
└ eventTime: 2024-01-01T12:00:00.000Z
```

### 4.3 出站消息发送

#### 4.3.1 文本消息

```typescript
export async function sendMessageWeixin(params: {
  to: string;
  text: string;
  opts: { baseUrl, token, contextToken };
}): Promise<{ messageId: string }> {
  const req = buildTextMessageReq({ to, text, contextToken, clientId });
  await sendMessageApi({ baseUrl, token, body: req });
  return { messageId: clientId };
}
```

#### 4.3.2 Markdown转纯文本

AI回复通常为Markdown格式，发送前需转换：

```typescript
export function markdownToPlainText(text: string): string {
  let result = text;
  // 去除代码块标记，保留代码内容
  result = result.replace(/```[^\n]*\n?([\s\S]*?)```/g, "$1");
  // 去除图片
  result = result.replace(/!\[[^\]]*\]\([^)]*\)/g, "");
  // 链接保留显示文本
  result = result.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");
  // 表格转换
  result = result.replace(/^\|[\s:|-]+\|$/gm, "");
  // 其他Markdown清理
  result = stripMarkdown(result);
  return result;
}
```

---

## 第五章：CDN与媒体处理

### 5.1 CDN上传流程

#### 5.1.1 完整上传流程

```
本地文件 → MD5计算 → AES-128-ECB加密 → 上传CDN → 获取下载参数 → 构造MessageItem → sendMessage
```

#### 5.1.2 AES加密实现

```typescript
import crypto from "node:crypto";

function encryptAesEcb(data: Buffer, key: Buffer): Buffer {
  const cipher = crypto.createCipheriv("aes-128-ecb", key, null);
  cipher.setAutoPadding(true);  // PKCS7填充
  return Buffer.concat([cipher.update(data), cipher.final()]);
}

function aesEcbPaddedSize(size: number): number {
  const blockSize = 16;
  return Math.ceil(size / blockSize) * blockSize;
}
```

#### 5.1.3 CDN上传函数

```typescript
async function uploadMediaToCdn(params: {
  filePath: string;
  toUserId: string;
  opts: WeixinApiOptions;
  cdnBaseUrl: string;
  mediaType: number;  // 1=IMAGE, 2=VIDEO, 3=FILE
}): Promise<UploadedFileInfo> {
  // 1. 读取文件并计算哈希
  const plaintext = await fs.readFile(filePath);
  const rawfilemd5 = crypto.createHash("md5").update(plaintext).digest("hex");
  
  // 2. 生成随机AES密钥和filekey
  const aeskey = crypto.randomBytes(16);
  const filekey = crypto.randomBytes(16).toString("hex");
  
  // 3. 获取上传URL
  const uploadResp = await getUploadUrl({
    ...opts,
    filekey,
    media_type: mediaType,
    rawsize: plaintext.length,
    rawfilemd5,
    filesize: aesEcbPaddedSize(plaintext.length),
    aeskey: aeskey.toString("hex"),
  });
  
  // 4. 加密并上传
  const ciphertext = encryptAesEcb(plaintext, aeskey);
  await uploadBufferToCdn({ buf: ciphertext, ...uploadResp, ... });
  
  // 5. 返回上传结果
  return {
    filekey,
    downloadEncryptedQueryParam,
    aeskey: aeskey.toString("hex"),
    fileSize: plaintext.length,
    fileSizeCiphertext: ciphertext.length,
  };
}
```

### 5.2 媒体下载与解密

#### 5.2.1 加密媒体下载

```typescript
async function downloadAndDecryptBuffer(
  encryptQueryParam: string,
  aesKeyBase64: string,
  cdnBaseUrl: string
): Promise<Buffer> {
  // 1. 构建下载URL
  const downloadUrl = buildCdnDownloadUrl(cdnBaseUrl, encryptQueryParam);
  
  // 2. 下载密文
  const ciphertext = await fetch(downloadUrl).then(r => r.arrayBuffer());
  
  // 3. AES解密
  const key = Buffer.from(aesKeyBase64, "base64");
  const decipher = crypto.createDecipheriv("aes-128-ecb", key, null);
  decipher.setAutoPadding(true);
  return Buffer.concat([decipher.update(Buffer.from(ciphertext)), decipher.final()]);
}
```

#### 5.2.2 语音转码

微信语音使用SILK格式，插件尝试转码为WAV：

```typescript
async function silkToWav(silkBuffer: Buffer): Promise<Buffer | null> {
  try {
    // 使用 silk-wasm 库转码
    const { SilkDecoder } = await import("silk-wasm");
    const decoder = new SilkDecoder();
    return decoder.decode(silkBuffer);
  } catch {
    return null;  // 转码失败返回原始SILK
  }
}
```

### 5.3 媒体类型判断

```typescript
const MIME_MAP: Record<string, string> = {
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".gif": "image/gif",
  ".mp4": "video/mp4",
  ".mp3": "audio/mpeg",
  ".pdf": "application/pdf",
  ".doc": "application/msword",
  // ...
};

function getMimeFromFilename(filename: string): string {
  const ext = path.extname(filename).toLowerCase();
  return MIME_MAP[ext] || "application/octet-stream";
}
```

---

## 第六章：存储与同步机制

### 6.1 getUpdates游标持久化

#### 6.1.1 游标存储

```typescript
type SyncBufData = {
  get_updates_buf: string;  // 服务端返回的同步游标
};

// 存储路径
function getSyncBufFilePath(accountId: string): string {
  return `~/.openclaw/openclaw-weixin/accounts/${accountId}.sync.json`;
}
```

#### 6.1.2 持久化流程

```typescript
// 1. 启动时加载
const previousBuf = loadGetUpdatesBuf(syncFilePath);

// 2. 每次响应后保存
const resp = await getUpdates({ get_updates_buf: previousBuf });
if (resp.get_updates_buf) {
  saveGetUpdatesBuf(syncFilePath, resp.get_updates_buf);
}
```

#### 6.1.3 兼容性处理

插件支持三种历史格式的游标文件：
1. 新格式：`{normalizedId}.sync.json`
2. 旧格式：`{rawId}.sync.json`（如 `wxid@im.bot.sync.json`）
3. 极旧格式：`agents/default/sessions/.openclaw-weixin-sync/default.json`

### 6.2 context_token管理

#### 6.2.1 会话上下文存储

```typescript
// 内存缓存
const contextTokenStore = new Map<string, string>();
// key格式: "accountId:userId"
// value: context_token字符串

// 磁盘持久化
function persistContextTokens(accountId: string): void {
  const tokens: Record<string, string> = {};
  for (const [k, v] of contextTokenStore) {
    if (k.startsWith(`${accountId}:`)) {
      tokens[k.slice(accountId.length + 1)] = v;
    }
  }
  fs.writeFileSync(`${accountId}.context-tokens.json`, JSON.stringify(tokens));
}
```

#### 6.2.2 用途

`context_token` 是微信消息的会话上下文标识，发送回复时必须回传：
```typescript
await sendMessage({
  msg: {
    to_user_id: "xxx",
    context_token: getContextToken(accountId, userId),  // 必须回传
    item_list: [...]
  }
});
```

### 6.3 账号清理机制

#### 6.3.1 清理同名用户旧账号

扫码登录成功后，清理同一用户ID的其他旧账号：

```typescript
export function clearStaleAccountsForUserId(
  currentAccountId: string,
  userId: string
): void {
  const allIds = listIndexedWeixinAccountIds();
  for (const id of allIds) {
    if (id === currentAccountId) continue;
    const data = loadWeixinAccount(id);
    if (data?.userId === userId) {
      // 删除旧账号文件
      clearWeixinAccount(id);
      unregisterWeixinAccountId(id);
    }
  }
}
```

---

## 第七章：监控与错误处理

### 7.1 长轮询监控循环

#### 7.1.1 监控主循环

```typescript
export async function monitorWeixinProvider(opts: MonitorWeixinOpts): Promise<void> {
  // 1. 初始化：加载游标、配置缓存
  const syncFilePath = getSyncBufFilePath(accountId);
  const previousBuf = loadGetUpdatesBuf(syncFilePath);
  const configManager = new WeixinConfigManager({ baseUrl, token });
  
  // 2. 进入主循环
  while (!abortSignal?.aborted) {
    try {
      // 长轮询获取消息
      const resp = await getUpdates({
        baseUrl,
        token,
        get_updates_buf: currentBuf,
        timeoutMs: nextTimeout,
      });
      
      // 处理消息
      for (const msg of resp.msgs ?? []) {
        await processOneMessage(msg, deps);
      }
      
      // 更新游标
      if (resp.get_updates_buf) {
        saveGetUpdatesBuf(syncFilePath, resp.get_updates_buf);
      }
      
    } catch (err) {
      // 错误处理和重试
      await handleError(err);
    }
  }
}
```

#### 7.1.2 错误恢复策略

```typescript
const MAX_CONSECUTIVE_FAILURES = 3;
const BACKOFF_DELAY_MS = 30_000;
const RETRY_DELAY_MS = 2_000;

async function handleError(err: Error): Promise<void> {
  consecutiveFailures++;
  
  if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
    // 3次失败后进入30秒退避
    await sleep(BACKOFF_DELAY_MS);
    consecutiveFailures = 0;
  } else {
    await sleep(RETRY_DELAY_MS);
  }
}
```

### 7.2 会话过期处理

#### 7.2.1 过期检测

```typescript
const SESSION_EXPIRED_ERRCODE = -14;

const isSessionExpired = resp.errcode === SESSION_EXPIRED_ERRCODE;
if (isSessionExpired) {
  pauseSession(accountId);  // 暂停该账号的请求
  // 等待1分钟后重试
  await sleep(getRemainingPauseMs(accountId));
}
```

#### 7.2.2 会话保护

```typescript
export function assertSessionActive(accountId: string): void {
  if (isSessionPaused(accountId)) {
    const remaining = getRemainingPauseMs(accountId);
    throw new Error(
      `weixin session paused for ${Math.ceil(remaining / 60000)} minutes`
    );
  }
}
```

### 7.3 错误通知机制

#### 7.3.1 自动发送错误提示

```typescript
async function sendWeixinErrorNotice(params: {
  to: string;
  contextToken?: string;
  message: string;
  baseUrl: string;
  token?: string;
}): Promise<void> {
  // 根据错误类型生成友好提示
  let notice: string;
  if (errMsg.includes("remote media download failed")) {
    notice = "⚠️ 媒体文件下载失败，请检查链接是否可访问。";
  } else if (errMsg.includes("CDN upload")) {
    notice = "⚠️ 媒体文件上传失败，请稍后重试。";
  } else {
    notice = `⚠️ 消息发送失败：${errMsg}`;
  }
  await sendMessageWeixin({ to: params.to, text: notice, opts });
}
```

---

## 第八章：OpenClaw框架集成

### 8.1 插件注册

```typescript
// index.ts
export default {
  id: "openclaw-weixin",
  name: "Weixin",
  configSchema: buildChannelConfigSchema(WeixinConfigSchema),
  
  register(api: OpenClawPluginApi) {
    // 版本兼容性检查
    assertHostCompatibility(api.runtime?.version);
    
    // 设置全局运行时
    if (api.runtime) {
      setWeixinRuntime(api.runtime);
    }
    
    // 注册渠道
    api.registerChannel({ plugin: weixinPlugin });
    
    // 注册CLI命令
    api.registerCli(({ program, config }) => registerWeixinCli({ program, config }));
  },
};
```

### 8.2 渠道能力定义

```typescript
export const weixinPlugin: ChannelPlugin<ResolvedWeixinAccount> = {
  // 渠道元信息
  meta: {
    id: "openclaw-weixin",
    blurb: "getUpdates long-poll upstream, sendMessage downstream",
  },
  
  // 能力声明
  capabilities: {
    chatTypes: ["direct"],    // 仅支持私聊
    media: true,               // 支持媒体
    blockStreaming: true,      // 支持阻断式流式输出
  },
  
  // 消息处理提示（注入AI提示词）
  agentPrompt: {
    messageToolHints: () => [
      "发送图片时使用message tool，media设为本地路径或远程URL",
      "生成/保存文件时使用绝对路径",
      "创建定时任务时必须指定delivery.to和delivery.accountId",
    ],
  },
  
  // 出站消息
  outbound: {
    deliveryMode: "direct",
    textChunkLimit: 4000,  // 文本分块限制
    sendText: async (ctx) => { /* ... */ },
    sendMedia: async (ctx) => { /* ... */ },
  },
  
  // 状态监控
  status: {
    buildChannelSummary: ({ snapshot }) => ({
      configured: snapshot.configured,
      lastError: snapshot.lastError,
      lastInboundAt: snapshot.lastInboundAt,
    }),
  },
  
  // 认证入口
  auth: {
    login: async ({ cfg, accountId, verbose, runtime }) => {
      // 触发二维码登录流程
    },
  },
  
  // 网关入口
  gateway: {
    startAccount: async (ctx) => {
      // 启动长轮询监控
      return monitorWeixinProvider({ ...ctx });
    },
    loginWithQrStart: async ({ accountId, timeoutMs }) => {
      // 返回二维码数据供前端展示
    },
    loginWithQrWait: async (params) => {
      // 轮询登录状态
    },
  },
};
```

### 8.3 消息路由

#### 8.3.1 目标解析

```typescript
targetResolver: {
  // 微信用户ID格式: xxx@im.wechat
  looksLikeId: (raw) => raw.endsWith("@im.wechat"),
},
```

#### 8.3.2 账号推断

出站消息发送时，根据收件人推断发送账号：

```typescript
function resolveOutboundAccountId(cfg, to): string {
  const allIds = listWeixinAccountIds(cfg);
  
  if (allIds.length === 1) {
    return allIds[0];  // 只有一个账号直接使用
  }
  
  // 多个账号：根据contextToken匹配
  const matched = findAccountIdsByContextToken(allIds, to);
  if (matched.length === 1) {
    return matched[0];
  }
  
  // 匹配失败或多个匹配：抛出错误
  throw new Error(`Ambiguous account for to=${to}`);
}
```

---

## 第九章：weixin-ilink 客户端库

### 9.1 库概述

weixin-ilink 是插件的独立客户端库版本，可单独导入使用，适合需要更低集成度的场景。

### 9.2 核心API

```typescript
import { ILinkClient, loginWithQR } from "weixin-ilink";

// 方式一：使用Client类
const client = new ILinkClient({
  baseUrl: "https://ilinkai.weixin.qq.com",
  token: "bot_token",
});

// 轮询消息
const resp = await client.getUpdates({ get_updates_buf: "" });

// 发送消息
await client.sendMessage({
  msg: {
    to_user_id: "wxid_xxx@im.wechat",
    item_list: [{ type: 1, text_item: { text: "Hello" } }],
  },
});

// 方式二：使用独立函数
const { getUpdates, sendMessage, getUploadUrl } = await import("weixin-ilink");
await sendMessage({ /* ... */ });
```

### 9.3 登录函数

```typescript
import { loginWithQR } from "weixin-ilink";

const creds = await loginWithQR({
  onQRCode: (url) => {
    // 渲染二维码
    qrterm.generate(url, { small: true });
  },
  onStatusChange: (status) => {
    console.log(`Status: ${status}`);
    // status: "waiting" | "scanned" | "refreshing" | "confirmed"
  },
});

console.log("Bot Token:", creds.botToken);
console.log("Account ID:", creds.accountId);
```

### 9.4 与完整插件的差异

| 特性 | 完整插件 | weixin-ilink |
|------|---------|--------------|
| OpenClaw集成 | 是 | 否 |
| CLI命令 | 是 | 否 |
| 斜杠指令 | 是 | 否 |
| 调试模式 | 是 | 否 |
| 媒体处理 | 是 | 需自行实现 |
| 状态持久化 | 是 | 需自行实现 |

---

## 第十章：二次开发指南

### 10.1 对接自有后端

如果需要将插件或客户端对接自己的 iLink 兼容后端，需要实现以下接口：

| 接口 | 方法 | 路径 | 说明 |
|------|------|------|------|
| getUpdates | POST | /ilink/bot/getupdates | 长轮询 |
| sendMessage | POST | /ilink/bot/sendmessage | 发送消息 |
| getUploadUrl | POST | /ilink/bot/getuploadurl | CDN预签名 |
| getConfig | POST | /ilink/bot/getconfig | 配置获取 |
| sendTyping | POST | /ilink/bot/sendtyping | 输入状态 |
| getQRCode | GET | /ilink/bot/get_bot_qrcode | 获取二维码 |
| getQRStatus | GET | /ilink/bot/get_qrcode_status | 轮询扫码状态 |

### 10.2 消息类型扩展

添加新的消息类型支持：

```typescript
// 1. 在types.ts添加类型定义
interface CustomItem {
  type: number;  // 新类型值
  custom_item?: CustomData;
}

// 2. 在send.ts添加发送函数
export async function sendCustomMessage(params: {
  to: string;
  customData: CustomData;
  opts: WeixinApiOptions;
}): Promise<void> {
  const item: MessageItem = {
    type: CUSTOM_TYPE,
    custom_item: params.customData,
  };
  await sendMessageApi({ ... });
}
```

### 10.3 自定义斜杠指令

扩展 slash-commands.ts：

```typescript
const COMMANDS: Record<string, CommandHandler> = {
  "/echo": handleEcho,
  "/toggle-debug": handleDebug,
  "/mycommand": handleMyCommand,  // 新增
};

async function handleMyCommand(
  ctx: SlashCommandContext,
  args: string
): Promise<void> {
  // 实现自定义逻辑
  await sendReply(ctx, `自定义指令: ${args}`);
}
```

### 10.4 会话上下文管理

如果需要自定义 context_token 存储策略：

```typescript
// 替换默认实现
import { setContextToken, getContextToken } from "./messaging/inbound.ts";

// 使用Redis存储
import { createClient } from "redis";

const redis = createClient();

export function setContextToken(accountId: string, userId: string, token: string): void {
  redis.set(`weixin:${accountId}:${userId}`, token);
}

export function getContextToken(accountId: string, userId: string): string | undefined {
  return redis.get(`weixin:${accountId}:${userId}`);
}
```

---

## 附录A：配置参考

### A.1 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| OPENCLAW_STATE_DIR | 状态目录 | ~/.openclaw |
| OPENCLAW_CONFIG | 配置文件路径 | ~/.openclaw/openclaw.json |
| OPENCLAW_OAUTH_DIR | 凭证目录 | $OPENCLAW_STATE_DIR/credentials |

### A.2 插件配置

```json
{
  "channels": {
    "openclaw-weixin": {
      "accounts": {
        "accountId": {
          "name": "我的微信",
          "enabled": true,
          "cdnBaseUrl": "https://novac2c.cdn.weixin.qq.com/c2c",
          "routeTag": "optional"
        }
      }
    }
  },
  "agents": {
    "mode": "per-channel-per-peer"
  }
}
```

### A.3 代理配置

```json
{
  "plugins": {
    "entries": {
      "openclaw-weixin": {
        "enabled": true
      }
    }
  }
}
```

---

## 附录B：错误码参考

| 错误码 | 含义 | 处理建议 |
|--------|------|----------|
| -14 | 会话过期 | 自动暂停1分钟后重试 |
| 0 | 成功 | 正常处理 |
| 其他负数 | API错误 | 记录日志，检查网络 |

---

## 附录C：安全考虑

### C.1 凭证保护

- Token 文件权限设置为 0o600（仅所有者可读写）
- 日志中自动脱敏敏感信息
- 定期轮换 token

### C.2 输入验证

- 所有 API 响应字段均使用 TypeScript 类型定义
- 使用 Zod schema 验证配置
- 异常输入优雅降级

### C.3 速率限制

- CDN 上传失败最多重试3次
- API 连续失败3次进入退避状态
- 长轮询超时后自动重连

---

## 文档版本

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0 | 2026-04-06 | 初始版本，基于源码v2.1.1 |
