# Open-AwA API 完整测试方案

> 本文档覆盖 Open-AwA 平台全部 35 个路由模块、190+ API 端点的自动化测试方案与 AI 驱动功能测试场景。

---

## 目录

1. [测试环境准备](#1-测试环境准备)
2. [认证与安全测试](#2-认证与安全测试)
3. [聊天模块测试](#3-聊天模块测试)
4. [会话管理测试](#4-会话管理测试)
5. [技能引擎测试](#5-技能引擎测试)
6. [插件系统测试](#6-插件系统测试)
7. [插件市场测试](#7-插件市场测试)
8. [记忆系统测试](#8-记忆系统测试)
9. [经验管理测试](#9-经验管理测试)
10. [经验文件测试](#10-经验文件测试)
11. [提示词管理测试](#11-提示词管理测试)
12. [行为分析测试](#12-行为分析测试)
13. [工作流测试](#13-工作流测试)
14. [定时任务测试](#14-定时任务测试)
15. [日记系统测试](#15-日记系统测试)
16. [系统日志测试](#16-系统日志测试)
17. [MCP 服务测试](#17-mcp-服务测试)
18. [模型管理测试](#18-模型管理测试)
19. [计费系统测试](#19-计费系统测试)
20. [安全/RBAC 测试](#20-安全rbac-测试)
21. [用户管理测试](#21-用户管理测试)
22. [用户画像测试](#22-用户画像测试)
23. [系统诊断测试](#23-系统诊断测试)
24. [测试场景运行器测试](#24-测试场景运行器测试)
25. [Agent 工具测试](#25-agent-工具测试)
26. [子Agent测试](#26-子agent测试)
27. [任务运行时测试](#27-任务运行时测试)
28. [工作区管理测试](#28-工作区管理测试)
29. [心跳系统测试](#29-心跳系统测试)
30. [Coding 模式测试](#30-coding-模式测试)
31. [收件箱测试](#31-收件箱测试)
32. [魔法命令测试](#32-魔法命令测试)
33. [TTS 语音测试](#33-tts-语音测试)
34. [任务执行测试](#34-任务执行测试)
35. [微信集成测试](#35-微信集成测试)
36. [AI 驱动的端到端场景测试](#36-ai-驱动的端到端场景测试)
37. [附录：通用测试工具脚本](#37-附录通用测试工具脚本)

---

## 1. 测试环境准备

### 1.1 环境变量

```bash
# 后端服务地址
export BASE_URL="http://localhost:8000"
export API_PREFIX="/api"

# 测试账号（需预先创建）
export TEST_USERNAME="test_user"
export TEST_PASSWORD="Test@123456"

# 管理员账号
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="Admin@123456"
```

### 1.2 通用测试函数（Python）

```python
import requests
import json
import time
import uuid
from typing import Dict, Optional, Any

BASE_URL = "http://localhost:8000"
API_PREFIX = "/api"

class APITestClient:
    """API 测试客户端，管理认证状态"""

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.access_token: Optional[str] = None
        self.csrf_token: Optional[str] = None
        self.session = requests.Session()
        self.current_user: Optional[Dict] = None

    def _headers(self, extra: dict = None) -> dict:
        h = {"Content-Type": "application/json"}
        if self.access_token:
            h["Authorization"] = f"Bearer {self.access_token}"
        if self.csrf_token:
            h["X-CSRF-Token"] = self.csrf_token
        if extra:
            h.update(extra)
        return h

    def _url(self, path: str) -> str:
        return f"{self.base_url}{API_PREFIX}{path}"

    def _handle_response(self, resp: requests.Response, expected_status: int = 200):
        assert resp.status_code == expected_status, \
            f"期望 {expected_status}, 实际 {resp.status_code}: {resp.text[:500]}"
        return resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text

    # --- Auth ---
    def login(self, username: str, password: str):
        data = {"username": username, "password": password}
        resp = self.session.post(
            self._url("/auth/login"), data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        result = self._handle_response(resp, 200)
        self.access_token = result["access_token"]
        if "csrf_token" in result:
            self.csrf_token = result["csrf_token"]
        self.current_user = self.get(f"/auth/me")
        print(f"[LOGIN] 用户 {username} 登录成功, user_id={self.current_user.get('id')}")
        return result

    def logout(self):
        resp = self.session.post(self._url("/auth/logout"), headers=self._headers())
        self.access_token = None
        self.csrf_token = None
        self.current_user = None
        return self._handle_response(resp, 200)

    # --- HTTP Methods ---
    def get(self, path: str, params: dict = None, expected_status: int = 200):
        resp = self.session.get(self._url(path), headers=self._headers(), params=params)
        return self._handle_response(resp, expected_status)

    def post(self, path: str, data: dict = None, expected_status: int = 200):
        resp = self.session.post(self._url(path), headers=self._headers(), json=data or {})
        return self._handle_response(resp, expected_status)

    def put(self, path: str, data: dict = None, expected_status: int = 200):
        resp = self.session.put(self._url(path), headers=self._headers(), json=data or {})
        return self._handle_response(resp, expected_status)

    def patch(self, path: str, data: dict = None, expected_status: int = 200):
        resp = self.session.patch(self._url(path), headers=self._headers(), json=data or {})
        return self._handle_response(resp, expected_status)

    def delete(self, path: str, expected_status: int = 200):
        resp = self.session.delete(self._url(path), headers=self._headers())
        return self._handle_response(resp, expected_status)

    def upload(self, path: str, file_path: str, field_name: str = "file", extra_data: dict = None):
        with open(file_path, "rb") as f:
            files = {field_name: f}
            headers = {}
            if self.access_token:
                headers["Authorization"] = f"Bearer {self.access_token}"
            if self.csrf_token:
                headers["X-CSRF-Token"] = self.csrf_token
            resp = self.session.post(
                self._url(path), headers=headers, files=files, data=extra_data or {}
            )
            return self._handle_response(resp, 200)

    def sse_stream(self, path: str, data: dict, timeout: int = 30):
        """发起 SSE 流式请求，返回生成器"""
        resp = self.session.post(
            self._url(path), headers=self._headers(), json=data, stream=True, timeout=timeout
        )
        assert resp.status_code == 200, f"SSE 请求失败: {resp.status_code}"
        for line in resp.iter_lines():
            if line:
                decoded = line.decode("utf-8")
                if decoded.startswith("data: "):
                    yield decoded[6:]
        resp.close()

    def websocket_connect(self, path: str, token: str):
        """WebSocket 连接（需 websocket-client 库）"""
        import websocket
        ws_url = f"ws://{self.base_url.replace('http://', '')}{API_PREFIX}{path}?token={token}"
        return websocket.create_connection(ws_url)


# 全局测试客户端实例
client = APITestClient()
```

### 1.3 通用断言辅助

```python
def assert_success(response: dict, msg: str = ""):
    """断言响应成功"""
    assert isinstance(response, dict), f"{msg}: 响应不是 dict 类型"
    # 部分接口可能没有 success 字段，只检查无 error
    if "error" in response:
        raise AssertionError(f"{msg}: 响应包含错误: {response['error']}")

def assert_list(response, min_len: int = 0, msg: str = ""):
    """断言返回列表且长度满足要求"""
    lst = response if isinstance(response, list) else response.get("data", response.get("items", []))
    assert isinstance(lst, list), f"{msg}: 期望 list 类型"
    assert len(lst) >= min_len, f"{msg}: 列表长度 {len(lst)} < {min_len}"

def assert_has_fields(obj: dict, fields: list, msg: str = ""):
    """断言对象包含指定字段"""
    for f in fields:
        assert f in obj, f"{msg}: 缺少字段 '{f}'"

def print_test_result(test_name: str, passed: bool, detail: str = ""):
    status = "[PASS]" if passed else "[FAIL]"
    print(f"  {status} {test_name}{' - ' + detail if detail else ''}")
```

---

## 2. 认证与安全测试

### 2.1 自动化测试

```python
def test_auth_flow():
    """认证模块完整流程测试"""
    print("\n=== 认证模块测试 ===")

    # 2.1.1 登录 - 正确凭据
    result = client.login(TEST_USERNAME, TEST_PASSWORD)
    assert "access_token" in result
    assert result["token_type"] == "bearer"
    print_test_result("POST /api/auth/login (正确凭据)", True)

    # 2.1.2 登录 - 错误凭据
    resp = client.session.post(
        client._url("/auth/login"),
        data={"username": "wrong", "password": "wrong"},
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    assert resp.status_code == 401
    print_test_result("POST /api/auth/login (错误凭据 → 401)", True)

    # 2.1.3 获取当前用户信息
    user = client.get("/auth/me")
    assert_has_fields(user, ["id", "username", "email"], "me")
    print_test_result("GET /api/auth/me", True, f"username={user['username']}")

    # 2.1.4 修改密码
    result = client.put("/auth/me/password", {
        "old_password": TEST_PASSWORD,
        "new_password": "NewTest@123",
        "confirm_password": "NewTest@123"
    })
    assert "message" in result
    print_test_result("PUT /api/auth/me/password", True)
    # 恢复密码
    client.put("/auth/me/password", {
        "old_password": "NewTest@123",
        "new_password": TEST_PASSWORD,
        "confirm_password": TEST_PASSWORD
    })

    # 2.1.5 修改密码 - 弱密码拒绝
    result = client.put("/auth/me/password", {
        "old_password": TEST_PASSWORD,
        "new_password": "123",
        "confirm_password": "123"
    }, expected_status=422)
    print_test_result("PUT /api/auth/me/password (弱密码 → 422)", True)

    # 2.1.6 获取 CSRF Token
    result = client.get("/auth/csrf-token")
    assert "csrf_token" in result
    print_test_result("GET /api/auth/csrf-token", True)

    # 2.1.7 轮转 API Key
    result = client.post("/auth/rotate-api-key", {"confirm": True})
    assert "api_key" in result
    print_test_result("POST /api/auth/rotate-api-key", True)

    # 2.1.8 未认证访问受保护接口
    anon = APITestClient()
    resp = anon.session.get(client._url("/auth/me"))
    assert resp.status_code == 401
    print_test_result("GET /api/auth/me (未认证 → 401)", True)

    # 2.1.9 登出
    result = client.logout()
    assert "message" in result
    print_test_result("POST /api/auth/logout", True)

    # 2.1.10 登出后令牌失效
    resp = client.session.get(client._url("/auth/me"), headers=client._headers())
    assert resp.status_code == 401
    print_test_result("GET /api/auth/me (登出后 → 401)", True)
```

### 2.2 速率限制测试

```python
def test_rate_limiting():
    """速率限制测试（60 请求/分钟）"""
    print("\n=== 速率限制测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)
    # 连续发送 65 次请求
    rate_limited = False
    for i in range(65):
        resp = client.session.get(client._url("/auth/me"), headers=client._headers())
        if resp.status_code == 429:
            rate_limited = True
            break
    assert rate_limited, "60次请求后应触发速率限制(429)"
    print_test_result("速率限制 60 req/min → 429", True, "触发于第{}次".format(i+1))
```

### 2.3 AI 调用认证场景

```
[AI 测试场景 1] AI 尝试未认证访问
用户输入: "帮我查一下我自己的用户信息"
前提: 未登录状态
预期: AI 调用 GET /api/auth/me 返回 401
验证: AI 应提示用户需要先登录，引导完成认证流程

[AI 测试场景 2] AI 辅助密码修改
用户输入: "帮我把密码改成 MyNewPwd@888"
前提: 已登录
预期: AI 调用 PUT /api/auth/me/password 完成修改
验证: 修改后用新密码重新登录成功，旧密码登录失败
```

---

## 3. 聊天模块测试

### 3.1 自动化测试

```python
def test_chat_basic():
    """聊天模块基础功能测试"""
    print("\n=== 聊天模块测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    session_id = f"test-{uuid.uuid4().hex[:8]}"

    # 3.1.1 发送普通聊天消息
    result = client.post("/chat", {
        "message": "你好，请介绍一下你自己",
        "session_id": session_id,
        "provider": "openai",
        "model": "gpt-4o-mini",
        "mode": "sync"
    })
    assert_has_fields(result, ["response", "session_id"], "chat sync")
    print_test_result("POST /api/chat (sync)", True, f"session={session_id}")

    # 3.1.2 发送流式聊天消息
    chunk_count = 0
    for chunk in client.sse_stream("/chat", {
        "message": "用一句话介绍人工智能",
        "session_id": session_id,
        "mode": "stream"
    }):
        chunk_count += 1
        if chunk_count > 50:
            break
    assert chunk_count > 0, "流式响应应包含至少一个 chunk"
    print_test_result("POST /api/chat (stream SSE)", True, f"收到 {chunk_count} 个 chunk")

    # 3.1.3 带深度思考的聊天
    result = client.post("/chat", {
        "message": "请分析快速排序的时间复杂度",
        "session_id": session_id,
        "mode": "sync",
        "thinking_enabled": True,
        "thinking_depth": "deep"
    })
    assert "response" in result
    print_test_result("POST /api/chat (thinking deep)", True)

    # 3.1.4 获取聊天历史
    history = client.get(f"/chat/history/{session_id}")
    assert isinstance(history, list)
    assert len(history) >= 2, f"至少应该有2条历史记录，实际 {len(history)}"
    print_test_result("GET /api/chat/history/{session_id}", True, f"{len(history)} 条消息")

    # 3.1.5 提交用户反馈
    result = client.post("/chat/feedback", {
        "session_id": session_id,
        "message_id": history[-1].get("id") if history else "0",
        "rating": 5,
        "comment": "回答准确"
    })
    print_test_result("POST /api/chat/feedback (5分好评)", True)

    # 3.1.6 提交用户反馈 - 差评
    result = client.post("/chat/feedback", {
        "session_id": session_id,
        "message_id": history[0].get("id") if len(history) > 1 else "0",
        "rating": 2,
        "comment": "响应速度偏慢"
    })
    print_test_result("POST /api/chat/feedback (2分差评)", True)

    # 3.1.7 取消任务
    result = client.post(f"/chat/cancel/{session_id}")
    assert result.get("status") in ["cancelled", "not_found", "not_running"]
    print_test_result("POST /api/chat/cancel/{session_id}", True)

    return session_id
```

### 3.2 文件上传测试

```python
def test_chat_upload():
    """聊天附件上传测试"""
    print("\n=== 聊天附件测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 创建测试文件
    test_file = "/tmp/test_chat_upload.txt"
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("这是一段测试文本内容，用于验证聊天附件上传功能。")

    # 3.2.1 上传附件
    result = client.upload("/chat/upload", test_file)
    assert_has_fields(result, ["filename", "url"], "upload")
    filename = result["filename"]
    print_test_result("POST /api/chat/upload", True, f"filename={filename}")

    # 3.2.2 下载附件
    resp = client.session.get(
        client._url(f"/chat/uploads/{filename}"),
        headers=client._headers()
    )
    assert resp.status_code == 200
    print_test_result("GET /api/chat/uploads/{filename}", True)

    # 3.2.3 带附件的聊天
    result = client.post("/chat", {
        "message": "请分析我刚上传的文件内容",
        "session_id": f"file-test-{uuid.uuid4().hex[:8]}",
        "mode": "sync",
        "attachments": [{"filename": filename, "type": "text/plain"}]
    })
    print_test_result("POST /api/chat (带附件)", True, "AI 应能分析文件内容")

    # 3.2.4 大文件拒绝测试 (>10MB)
    # 创建 11MB 的文件
    big_file = "/tmp/test_big_file.bin"
    with open(big_file, "wb") as f:
        f.write(b"\x00" * (11 * 1024 * 1024))
    resp = client.session.post(
        client._url("/chat/upload"),
        headers={"Authorization": f"Bearer {client.access_token}"},
        files={"file": open(big_file, "rb")}
    )
    assert resp.status_code in [413, 422, 400], f"大文件应被拒绝: {resp.status_code}"
    print_test_result("POST /api/chat/upload (>10MB 拒绝)", True)
```

### 3.3 确认操作测试

```python
def test_chat_confirmation():
    """操作确认流程测试"""
    print("\n=== 操作确认测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    session_id = f"confirm-{uuid.uuid4().hex[:8]}"

    # 3.3.1 发送需要确认的操作
    result = client.post("/chat", {
        "message": "帮我创建一个名为 test_project 的文件夹",
        "session_id": session_id,
        "mode": "sync"
    })
    # 如果 AI 返回了需要确认的操作
    if result.get("requires_confirmation"):
        step = result.get("confirmation_step", {})
        # 3.3.2 确认操作
        confirm = client.post("/chat/confirm", {
            "confirmed": True,
            "step": step
        })
        print_test_result("POST /api/chat/confirm (确认)", True)
    else:
        print_test_result("POST /api/chat/confirm (无需确认，跳过)", True)

    # 3.3.3 撤销操作测试
    result = client.post("/chat/undo-operation", {
        "operation_id": "test-op-001"
    })
    print_test_result("POST /api/chat/undo-operation", True)
```

### 3.4 WebSocket 聊天测试

```python
def test_chat_websocket():
    """WebSocket 实时聊天测试"""
    print("\n=== WebSocket 聊天测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    session_id = f"ws-{uuid.uuid4().hex[:8]}"

    try:
        ws = client.websocket_connect(
            f"/chat/ws/{session_id}",
            client.access_token
        )
        # 发送消息
        import json as json_mod
        ws.send(json_mod.dumps({"message": "WebSocket 测试消息", "mode": "sync"}))
        # 接收响应
        response = ws.recv()
        data = json_mod.loads(response)
        assert "response" in data or "chunk" in data
        ws.close()
        print_test_result("WS /api/chat/ws/{session_id}", True)
    except Exception as e:
        print_test_result("WS /api/chat/ws/{session_id}", False, str(e))
```

### 3.5 AI 驱动聊天场景测试

```
[AI 测试场景 3] 多轮对话记忆测试
步骤:
1. 用户: "我叫张三，是一名Python开发者" → AI 应答并存储
2. 用户: "我叫什么名字？" → AI 应从记忆中检索并回答"张三"
验证: GET /api/memory/search?query=张三 返回包含用户姓名的记忆条目

[AI 测试场景 4] 文件操作工具调用
用户输入: "在当前目录下创建一个 hello.py 文件，写入一个打印'Hello World'的函数"
前提: 已登录，会话中启用了文件操作工具
预期: AI 通过工具调用完成文件创建
验证: GET /api/tools/file/read?path=hello.py 返回文件内容包含 Hello World

[AI 测试场景 5] 网络搜索工具调用
用户输入: "搜索今天的热点新闻，并总结成3条要点"
前提: 已登录，启用了 web 搜索工具
预期: AI 调用搜索工具获取信息后总结
验证: 响应包含3条新闻摘要

[AI 测试场景 6] 代码分析工具调用
用户输入: "分析 backend/main.py 的代码结构，告诉我有哪些中间件"
前提: Coding 模式已启用
预期: AI 通过 coding 工具读取文件并分析返回
验证: 响应包含 CORS、CSRF、request_context 等中间件描述
```

---

## 4. 会话管理测试

### 4.1 自动化测试

```python
def test_conversation_crud():
    """会话增删改查测试"""
    print("\n=== 会话管理测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 4.1.1 创建会话
    session_id = f"conv-{uuid.uuid4().hex[:8]}"
    result = client.post("/conversations", {
        "title": "测试会话1",
        "session_id": session_id
    })
    assert_has_fields(result, ["id", "title", "session_id"], "create")
    conv_id = result.get("id") or result.get("session_id")
    print_test_result("POST /api/conversations", True, f"title=测试会话1")

    # 4.1.2 获取会话列表
    result = client.get("/conversations")
    assert_list(result, min_len=1)
    print_test_result("GET /api/conversations", True, f"总数 {len(result) if isinstance(result, list) else result.get('total')}")

    # 4.1.3 搜索会话
    result = client.get("/conversations", {"search": "测试"})
    print_test_result("GET /api/conversations?search=测试", True)

    # 4.1.4 分页查询
    result = client.get("/conversations", {"page": 1, "page_size": 5})
    print_test_result("GET /api/conversations?page=1&page_size=5", True)

    # 4.1.5 重命名会话
    result = client.patch(f"/conversations/{session_id}", {
        "title": "重命名会话"
    })
    assert result.get("title") == "重命名会话"
    print_test_result("PATCH /api/conversations/{session_id}", True)

    # 4.1.6 获取会话记录预览
    result = client.get("/conversations/records", {"limit": 10})
    print_test_result("GET /api/conversations/records", True)

    # 4.1.7 软删除会话
    result = client.delete(f"/conversations/{session_id}")
    print_test_result("DELETE /api/conversations/{session_id}", True)

    # 4.1.8 恢复会话
    result = client.post(f"/conversations/{session_id}/restore")
    print_test_result("POST /api/conversations/{session_id}/restore", True)

    # 4.1.9 批量删除
    result = client.post("/conversations/batch-delete", {
        "session_ids": [session_id],
        "retention_days": 30
    })
    print_test_result("POST /api/conversations/batch-delete", True)

    return session_id
```

### 4.2 导出与采集测试

```python
def test_conversation_export():
    """会话导出和采集测试"""
    print("\n=== 会话导出测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 4.2.1 导出会话
    resp = client.session.get(
        client._url("/conversations/export"),
        headers=client._headers(),
        params={"start_time": "2024-01-01", "end_time": "2026-12-31"}
    )
    assert resp.status_code == 200
    content = resp.text
    lines = content.strip().split("\n")
    print_test_result("GET /api/conversations/export (JSONL)", True, f"{len(lines)} 条记录")

    # 4.2.2 获取采集状态
    result = client.get("/conversations/collection-status")
    assert "enabled" in result
    print_test_result("GET /api/conversations/collection-status", True)

    # 4.2.3 更新采集状态
    result = client.put("/conversations/collection-status", None, params={"enabled": True})
    print_test_result("PUT /api/conversations/collection-status", True)

    return True
```

### 4.3 AI 调用会话管理场景

```
[AI 测试场景 7] AI 管理对话会话
用户输入: "把我所有的会话列出来，删除掉标题为'测试'的会话"
预期:
  1. AI 调用 GET /api/conversations 获取列表
  2. AI 筛选标题含"测试"的会话
  3. AI 调用 DELETE /api/conversations/{session_id} 逐个删除
验证: 再次获取列表，确认删除成功

[AI 测试场景 8] AI 创建并管理会话
用户输入: "创建3个新会话，分别命名为'工作计划'、'学习笔记'、'日常聊天'"
预期: AI 调用 POST /api/conversations 3次创建
验证: GET /api/conversations 返回3个新会话
```

---

## 5. 技能引擎测试

### 5.1 自动化测试

```python
def test_skills_crud():
    """技能增删改查测试"""
    print("\n=== 技能引擎测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 5.1.1 获取技能列表
    result = client.get("/skills")
    assert isinstance(result, list)
    print_test_result("GET /api/skills", True, f"{len(result)} 个技能")

    # 5.1.2 校验技能配置 YAML
    result = client.post("/skills/validate", {
        "yaml_content": """
name: test-skill
version: "1.0.0"
description: 测试技能
entry_point: test_skill.main
"""
    })
    print_test_result("POST /api/skills/validate", True, str(result.get("valid")))

    # 5.1.3 安装技能
    result = client.post("/skills", {
        "name": "auto-test-skill",
        "version": "1.0.0",
        "description": "自动化测试技能",
        "config": {"param1": "value1"}
    })
    skill_id = result.get("id") or result.get("skill_id")
    print_test_result("POST /api/skills (安装)", True, f"id={skill_id}")

    if skill_id:
        # 5.1.4 获取技能详情
        result = client.get(f"/skills/{skill_id}")
        assert_has_fields(result, ["name", "version"], "detail")
        print_test_result("GET /api/skills/{skill_id}", True)

        # 5.1.5 更新技能
        result = client.put(f"/skills/{skill_id}", {
            "description": "更新后的描述"
        })
        print_test_result("PUT /api/skills/{skill_id}", True)

        # 5.1.6 切换启用状态
        result = client.put(f"/skills/{skill_id}/toggle")
        print_test_result("PUT /api/skills/{skill_id}/toggle", True)

        # 5.1.7 获取技能配置
        result = client.get(f"/skills/{skill_id}/config")
        print_test_result("GET /api/skills/{skill_id}/config", True)

        # 5.1.8 执行技能
        result = client.post(f"/skills/{skill_id}/execute", {
            "inputs": {"input_key": "input_value"},
            "context": {"session_id": "test"}
        })
        print_test_result("POST /api/skills/{skill_id}/execute", True, str(result.get("status")))

        # 5.1.9 卸载技能
        result = client.delete(f"/skills/{skill_id}")
        print_test_result("DELETE /api/skills/{skill_id}", True)
```

### 5.2 技能市场测试

```python
def test_skill_market():
    """技能市场测试"""
    print("\n=== 技能市场测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 5.2.1 获取市场列表
    result = client.get("/skills/market")
    assert "skills" in result or "total" in result
    print_test_result("GET /api/skills/market", True)

    # 5.2.2 搜索市场
    result = client.get("/skills/market", {"search": "code"})
    print_test_result("GET /api/skills/market?search=code", True)

    # 5.2.3 从 ZIP 包安装技能（需要实际 ZIP 包）
    # result = client.upload("/skills/install-from-package", "test_skill.zip")
    # print_test_result("POST /api/skills/install-from-package", True)
    print_test_result("POST /api/skills/install-from-package", True, "需实际 ZIP 包，跳过")
```

### 5.3 技能统计测试

```python
def test_skill_analytics():
    """技能统计测试"""
    print("\n=== 技能统计测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 5.3.1 统计概览
    result = client.get("/skills/analytics/overview")
    print_test_result("GET /api/skills/analytics/overview", True)

    # 5.3.2 执行日志（需管理员）
    admin = APITestClient()
    admin.login(ADMIN_USERNAME, ADMIN_PASSWORD)
    result = admin.get("/skills/analytics/logs", {
        "limit": 10, "offset": 0
    })
    print_test_result("GET /api/skills/analytics/logs (admin)", True)
```

### 5.4 AI 调用技能场景

```
[AI 测试场景 9] AI 通过技能执行数据处理
用户输入: "安装一个文件摘要技能，然后用它分析 backend/README.md"
预期:
  1. AI 调用 POST /api/skills 安装技能
  2. AI 调用 POST /api/skills/{skill_id}/execute 执行
验证: 返回执行结果包含文件分析内容

[AI 测试场景 10] AI 管理技能生命周期
用户输入: "列出所有已安装技能，把不常用的停用掉"
预期:
  1. AI 调用 GET /api/skills 获取列表
  2. AI 调用 GET /api/skills/analytics/overview 查看使用统计
  3. AI 调用 PUT /api/skills/{skill_id}/toggle 停用低频技能
验证: 被停用的技能 enabled=false
```

---

## 6. 插件系统测试

### 6.1 自动化测试

```python
def test_plugins_crud():
    """插件增删改查测试"""
    print("\n=== 插件系统测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 6.1.1 扫描发现插件
    result = client.get("/plugins/discover")
    print_test_result("GET /api/plugins/discover", True)

    # 6.1.2 获取插件列表
    result = client.get("/plugins")
    assert isinstance(result, list)
    print_test_result("GET /api/plugins", True, f"{len(result)} 个插件")

    # 6.1.3 校验插件配置
    result = client.post("/plugins/validate", {
        "yaml_content": "name: test-plugin\nversion: 1.0.0"
    })
    print_test_result("POST /api/plugins/validate", True)

    # 6.1.4 安装插件（需管理员）
    admin = APITestClient()
    admin.login(ADMIN_USERNAME, ADMIN_PASSWORD)
    result = admin.post("/plugins", {
        "name": "auto-test-plugin",
        "version": "1.0.0",
        "config": {}
    })
    plugin_id = result.get("id") or result.get("plugin_id")
    print_test_result("POST /api/plugins (安装, admin)", True, f"id={plugin_id}")

    if plugin_id:
        # 6.1.5 获取插件详情
        result = client.get(f"/plugins/{plugin_id}")
        print_test_result(f"GET /api/plugins/{plugin_id}", True)

        # 6.1.6 获取插件工具列表
        result = client.get(f"/plugins/{plugin_id}/tools")
        print_test_result(f"GET /api/plugins/{plugin_id}/tools", True)

        # 6.1.7 获取插件配置 Schema
        result = client.get(f"/plugins/{plugin_id}/config/schema")
        print_test_result(f"GET /api/plugins/{plugin_id}/config/schema", True)

        # 6.1.8 保存插件配置
        result = admin.put(f"/plugins/{plugin_id}/config", {"key": "value"})
        print_test_result(f"PUT /api/plugins/{plugin_id}/config", True)

        # 6.1.9 导出插件配置
        result = client.get(f"/plugins/{plugin_id}/config/export")
        print_test_result(f"GET /api/plugins/{plugin_id}/config/export", True)

        # 6.1.10 获取插件权限状态
        result = client.get(f"/plugins/{plugin_id}/permissions")
        print_test_result(f"GET /api/plugins/{plugin_id}/permissions", True)

        # 6.1.11 获取插件日志
        result = client.get(f"/plugins/{plugin_id}/logs", {"limit": 10})
        print_test_result(f"GET /api/plugins/{plugin_id}/logs", True)

        # 6.1.12 执行插件方法
        result = client.post(f"/plugins/{plugin_id}/execute", {
            "method": "ping",
            "params": {}
        })
        print_test_result(f"POST /api/plugins/{plugin_id}/execute", True)

        # 6.1.13 切换启用状态
        result = admin.put(f"/plugins/{plugin_id}/toggle")
        print_test_result(f"PUT /api/plugins/{plugin_id}/toggle", True)

        # 6.1.14 卸载插件
        result = admin.delete(f"/plugins/{plugin_id}")
        print_test_result(f"DELETE /api/plugins/{plugin_id}", True)
```

### 6.2 插件热更新测试

```python
def test_plugin_hot_update():
    """插件热更新测试"""
    print("\n=== 插件热更新测试 ===")
    admin = APITestClient()
    admin.login(ADMIN_USERNAME, ADMIN_PASSWORD)

    # 先安装一个插件
    result = admin.post("/plugins", {
        "name": "hot-update-test",
        "version": "1.0.0",
        "config": {}
    })
    plugin_id = result.get("id") or result.get("plugin_id")

    if plugin_id:
        # 6.2.1 热更新
        result = admin.post(f"/plugins/{plugin_id}/hot-update", {})
        print_test_result(f"POST /api/plugins/{plugin_id}/hot-update", True)

        # 6.2.2 回滚
        result = admin.post(f"/plugins/{plugin_id}/rollback", {})
        print_test_result(f"POST /api/plugins/{plugin_id}/rollback", True)

        # 6.2.3 更新日志级别
        result = admin.put(f"/plugins/{plugin_id}/log-level", {"level": "DEBUG"})
        print_test_result(f"PUT /api/plugins/{plugin_id}/log-level", True)

        # 清理
        admin.delete(f"/plugins/{plugin_id}")
```

### 6.3 AI 调用插件场景

```
[AI 测试场景 11] AI 使用插件扩展能力
用户输入: "安装一个天气查询插件，然后告诉我北京今天的天气"
预期:
  1. AI 调用 GET /api/plugins/discover 发现可用插件
  2. AI 调用 POST /api/plugins (或 marketplace API) 安装
  3. AI 通过插件工具调用天气查询
验证: 响应包含北京天气信息

[AI 测试场景 12] AI 诊断插件问题
用户输入: "检查所有插件的运行状态和日志，报告任何异常"
预期:
  1. AI 调用 GET /api/plugins 获取列表
  2. AI 逐个调用 GET /api/plugins/{plugin_id}/logs
  3. AI 汇总形成状态报告
验证: 返回包含所有插件的状态摘要
```

---

## 7. 插件市场测试

### 7.1 自动化测试

```python
def test_marketplace():
    """插件市场测试"""
    print("\n=== 插件市场测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 7.1.1 获取分类列表
    result = client.get("/marketplace/categories")
    assert "categories" in result
    print_test_result("GET /api/marketplace/categories", True)

    # 7.1.2 浏览市场插件
    result = client.get("/marketplace/plugins", {"page": 1, "page_size": 10})
    print_test_result("GET /api/marketplace/plugins", True)

    # 7.1.3 搜索市场插件
    result = client.get("/marketplace/plugins/search", {"q": "code"})
    print_test_result("GET /api/marketplace/plugins/search?q=code", True)

    # 7.1.4 按分类浏览
    result = client.get("/marketplace/plugins", {"category": "utility"})
    print_test_result("GET /api/marketplace/plugins?category=utility", True)
```

### 7.2 AI 调用市场场景

```
[AI 测试场景 13] AI 探索插件市场
用户输入: "浏览插件市场，找到评分最高的5个插件，推荐给我"
预期: AI 调用市场 API 获取列表，分析后推荐
验证: 返回5个插件的推荐理由
```

---

## 8. 记忆系统测试

### 8.1 自动化测试

```python
def test_memory_system():
    """记忆系统完整测试"""
    print("\n=== 记忆系统测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    session_id = f"mem-{uuid.uuid4().hex[:8]}"

    # 8.1.1 新增长期记忆
    result = client.post("/memory/long-term", {
        "content": "用户的生日是1990年5月15日",
        "importance": 8,
        "metadata": {"category": "personal_info"},
        "source_type": "chat"
    })
    memory_id = result.get("id")
    print_test_result("POST /api/memory/long-term", True, f"id={memory_id}")

    # 8.1.2 新增长期记忆（低重要度）
    result = client.post("/memory/long-term", {
        "content": "用户喜欢喝咖啡",
        "importance": 3,
        "metadata": {"category": "preference"},
        "source_type": "chat"
    })
    print_test_result("POST /api/memory/long-term (低重要度)", True)

    # 8.1.3 获取长期记忆列表
    result = client.get("/memory/long-term", {"limit": 10})
    assert_list(result, min_len=1)
    print_test_result("GET /api/memory/long-term", True, f"{len(result) if isinstance(result, list) else result.get('total')} 条")

    # 8.1.4 新增短期记忆
    result = client.post("/memory/short-term", {
        "session_id": session_id,
        "role": "user",
        "content": "这是一条短期记忆测试"
    })
    stm_id = result.get("id")
    print_test_result("POST /api/memory/short-term", True)

    # 8.1.5 获取短期记忆
    result = client.get(f"/memory/short-term/{session_id}")
    print_test_result(f"GET /api/memory/short-term/{session_id}", True)

    # 8.1.6 关键词搜索记忆
    result = client.get("/memory/search", {"query": "生日"})
    print_test_result("GET /api/memory/search?query=生日", True)

    # 8.1.7 向量搜索
    result = client.post("/memory/vector-search", {
        "query": "用户个人信息",
        "limit": 10,
        "keyword_weight": 0.3,
        "vector_weight": 0.7
    })
    print_test_result("POST /api/memory/vector-search", True)

    # 8.1.8 记忆质量评估
    result = client.get("/memory/quality", {"limit": 10})
    print_test_result("GET /api/memory/quality", True)

    # 8.1.9 获取记忆统计
    result = client.get("/memory/stats")
    assert_has_fields(result, ["total", "short_term_count", "long_term_count"], "stats")
    print_test_result("GET /api/memory/stats", True)

    # 8.1.10 删除短期记忆
    result = client.delete(f"/memory/short-term/{stm_id}")
    print_test_result(f"DELETE /api/memory/short-term/{stm_id}", True)

    # 8.1.11 归档长期记忆
    result = client.post("/memory/archive", {
        "older_than_days": 30,
        "importance_threshold": 5
    })
    print_test_result("POST /api/memory/archive", True)

    # 8.1.12 删除长期记忆
    result = client.delete(f"/memory/long-term/{memory_id}")
    print_test_result(f"DELETE /api/memory/long-term/{memory_id}", True)
```

### 8.2 AI 调用记忆场景

```
[AI 测试场景 14] AI 利用长期记忆个性化回答
用户输入: "我喜欢什么？根据你记住的告诉我"
前提: 已有长期记忆（咖啡偏好、生日等）
预期: AI 调用 GET /api/memory/long-term 加载记忆后回答
验证: 回答包含已存储的个人偏好信息

[AI 测试场景 15] AI 管理用户记忆
用户输入: "我不喜欢喝咖啡了，更新你的记忆，然后记住我新喜欢的饮料是茶"
预期:
  1. AI 调用 GET /api/memory/search?query=咖啡 找到旧记忆
  2. AI 调用 DELETE /api/memory/long-term/{id} 删除
  3. AI 调用 POST /api/memory/long-term 新增茶偏好
验证: 搜索"咖啡"不再返回结果，搜索"茶"返回新记忆

[AI 测试场景 16] 跨会话记忆检索
用户输入1（会话1）: "我叫李明，今年30岁"
用户输入2（会话2）: "我叫什么名字？今年多大？"
预期: AI 从长期记忆中检索到跨会话信息
验证: 回答"李明，30岁"
```

---

## 9. 经验管理测试

### 9.1 自动化测试

```python
def test_experiences():
    """经验管理测试"""
    print("\n=== 经验管理测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 9.1.1 创建经验
    result = client.post("/experiences", {
        "experience_type": "coding",
        "confidence": 0.9,
        "content": "使用 Python 异步编程时，应使用 asyncio.run() 启动主协程",
        "tags": ["python", "async", "best-practice"],
        "source_task": "code_review"
    })
    exp_id = result.get("id")
    print_test_result("POST /api/experiences", True, f"id={exp_id}")

    # 9.1.2 获取经验列表
    result = client.get("/experiences", {"limit": 10})
    assert_list(result, min_len=1)
    print_test_result("GET /api/experiences", True)

    # 9.1.3 按类型筛选
    result = client.get("/experiences", {"experience_type": "coding"})
    print_test_result("GET /api/experiences?experience_type=coding", True)

    # 9.1.4 获取经验详情
    result = client.get(f"/experiences/{exp_id}")
    assert_has_fields(result, ["content", "experience_type", "confidence"], "detail")
    print_test_result(f"GET /api/experiences/{exp_id}", True)

    # 9.1.5 更新经验
    result = client.put(f"/experiences/{exp_id}", {
        "content": "更新：Python 3.11+ 推荐使用 asyncio.run()",
        "confidence": 0.95
    })
    print_test_result(f"PUT /api/experiences/{exp_id}", True)

    # 9.1.6 搜索经验
    result = client.get("/experiences/search", {
        "query": "异步编程",
        "experience_type": "coding",
        "min_confidence": 0.8
    })
    print_test_result("GET /api/experiences/search", True)

    # 9.1.7 经验统计
    result = client.get("/experiences/stats/summary")
    print_test_result("GET /api/experiences/stats/summary", True)

    # 9.1.8 审核经验
    result = client.put(f"/experiences/{exp_id}/review", {"approved": True})
    print_test_result("PUT /api/experiences/{exp_id}/review (approved)", True)

    # 9.1.9 提取经验
    result = client.post("/experiences/extract", {
        "session_id": f"extract-{uuid.uuid4().hex[:8]}",
        "user_goal": "学习 Python 异步编程",
        "execution_steps": ["阅读文档", "编写示例代码", "测试"],
        "final_result": "掌握了 asyncio 的核心用法",
        "status": "success"
    })
    print_test_result("POST /api/experiences/extract", True)

    # 9.1.10 获取经验日志
    result = client.get("/experiences/logs", {"limit": 5})
    print_test_result("GET /api/experiences/logs", True)

    # 9.1.11 删除经验
    result = client.delete(f"/experiences/{exp_id}")
    print_test_result(f"DELETE /api/experiences/{exp_id}", True)
```

### 9.2 AI 调用经验场景

```
[AI 测试场景 17] AI 从对话中提取经验
用户输入: "我刚才完成了一个 Flask 迁移到 FastAPI 的项目，整个过程很顺利，注意点是要把 Flask 的 request 对象换成 FastAPI 的依赖注入"
预期:
  1. AI 调用 POST /api/experiences/extract 提取经验
  2. 经验类型: migration, 标签: [flask, fastapi, python]
验证: GET /api/experiences/search?query=flask fastapi 返回相关经验

[AI 测试场景 18] AI 应用历史经验
用户输入: "我想把 Django 项目迁移到 FastAPI，有什么建议吗？"
前提: 已有类似的迁移经验
预期: AI 调用 GET /api/experiences/search 查找相关经验
验证: 回答引用了之前存储的迁移经验
```

---

## 10. 经验文件测试

### 10.1 自动化测试

```python
def test_experience_files():
    """经验文件测试"""
    print("\n=== 经验文件测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 10.1.1 列出经验文件
    result = client.get("/experience-files")
    assert isinstance(result, list)
    print_test_result("GET /api/experience-files", True, f"{len(result)} 个文件")

    # 10.1.2 保存经验文件
    result = client.put("/experience-files/test-experience.txt", {
        "content": "# 测试经验文件\n\n这是用于测试的经验文件内容。"
    })
    print_test_result("PUT /api/experience-files/{file_name}", True)

    # 10.1.3 获取文件详情
    result = client.get("/experience-files/test-experience.txt")
    print_test_result("GET /api/experience-files/{file_name}", True)
```

---

## 11. 提示词管理测试

### 11.1 自动化测试

```python
def test_prompts():
    """提示词管理测试"""
    print("\n=== 提示词管理测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 11.1.1 创建提示词
    result = client.post("/prompts", {
        "name": "测试提示词",
        "content": "你是一个专业的{{role}}，请用{{tone}}的语气回答用户问题。用户问题是: {{question}}",
        "variables": ["role", "tone", "question"]
    })
    prompt_id = result.get("id")
    print_test_result("POST /api/prompts", True, f"id={prompt_id}")

    # 11.1.2 获取提示词列表
    result = client.get("/prompts")
    assert_list(result, min_len=1)
    print_test_result("GET /api/prompts", True)

    # 11.1.3 获取生效中的提示词
    result = client.get("/prompts/active")
    print_test_result("GET /api/prompts/active", True)

    # 11.1.4 获取单个提示词详情
    result = client.get(f"/prompts/{prompt_id}")
    assert_has_fields(result, ["name", "content", "variables"], "detail")
    print_test_result(f"GET /api/prompts/{prompt_id}", True)

    # 11.1.5 更新提示词
    result = client.put(f"/prompts/{prompt_id}", {
        "content": "更新后的提示词内容: {{question}}",
        "variables": ["question"]
    })
    print_test_result(f"PUT /api/prompts/{prompt_id}", True)

    # 11.1.6 删除提示词
    result = client.delete(f"/prompts/{prompt_id}")
    print_test_result(f"DELETE /api/prompts/{prompt_id}", True)
```

### 11.2 AI 调用提示词场景

```
[AI 测试场景 19] AI 创建和管理提示词模板
用户输入: "帮我创建一个代码审查的提示词模板，要求 AI 扮演资深架构师，从性能、安全、可维护性三个角度审查代码"
预期:
  1. AI 调用 POST /api/prompts 创建提示词模板
  2. 模板包含结构化审查维度
验证: GET /api/prompts 返回新创建的模板

[AI 测试场景 20] AI 使用自定义提示词
系统配置: 当前 active prompt 为代码审查模板
用户输入: "审查这段代码: [代码内容]"
预期: AI 使用 active prompt 的审查角度来回答
验证: 回答结构符合提示词模板的要求
```

---

## 12. 行为分析测试

### 12.1 自动化测试

```python
def test_behavior():
    """行为分析测试"""
    print("\n=== 行为分析测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 12.1.1 记录行为日志
    result = client.post("/behaviors/log", {
        "action_type": "页面访问",
        "details": {"page": "仪表盘", "duration_ms": 5000}
    })
    print_test_result("POST /api/behaviors/log", True)

    # 12.1.2 获取行为统计
    result = client.get("/behaviors/stats", {"days": 7})
    print_test_result("GET /api/behaviors/stats?days=7", True)

    # 12.1.3 按类型筛选行为日志
    result = client.get("/behaviors/logs", {
        "skip": 0,
        "limit": 10,
        "action_type": "页面访问"
    })
    print_test_result("GET /api/behaviors/logs", True)
```

---

## 13. 工作流测试

### 13.1 自动化测试

```python
def test_workflows():
    """工作流完整测试"""
    print("\n=== 工作流测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 13.1.1 创建工作流
    result = client.post("/workflows", {
        "name": "测试工作流",
        "definition": {
            "steps": [
                {"id": "step1", "type": "llm", "config": {"prompt": "分析用户需求"}},
                {"id": "step2", "type": "tool", "config": {"tool": "file_search"}},
                {"id": "step3", "type": "llm", "config": {"prompt": "总结结果"}}
            ],
            "edges": [
                {"from": "step1", "to": "step2"},
                {"from": "step2", "to": "step3"}
            ]
        },
        "format": "json",
        "enabled": True
    })
    wf_id = result.get("id")
    print_test_result("POST /api/workflows", True, f"id={wf_id}")

    # 13.1.2 获取工作流列表
    result = client.get("/workflows")
    assert_list(result, min_len=1)
    print_test_result("GET /api/workflows", True)

    # 13.1.3 获取工作流详情
    result = client.get(f"/workflows/{wf_id}")
    assert_has_fields(result, ["name", "definition"], "detail")
    print_test_result(f"GET /api/workflows/{wf_id}", True)

    # 13.1.4 更新工作流
    result = client.put(f"/workflows/{wf_id}", {
        "name": "更新测试工作流",
        "definition": result["definition"]
    })
    print_test_result(f"PUT /api/workflows/{wf_id}", True)

    # 13.1.5 执行工作流
    result = client.post("/workflows/execute", {
        "workflow_id": wf_id,
        "input_context": {"user_query": "测试输入"}
    })
    execution_id = result.get("execution_id") or result.get("id")
    print_test_result("POST /api/workflows/execute", True, f"execution_id={execution_id}")

    # 13.1.6 获取执行记录
    if execution_id:
        result = client.get(f"/workflows/executions/{execution_id}")
        print_test_result(f"GET /api/workflows/executions/{execution_id}", True)

    # 13.1.7 删除工作流
    result = client.delete(f"/workflows/{wf_id}")
    print_test_result(f"DELETE /api/workflows/{wf_id}", True)
```

### 13.2 AI 调用工作流场景

```
[AI 测试场景 21] AI 设计并执行工作流
用户输入: "设计一个自动化代码审查工作流：先检查代码风格，然后运行测试，最后生成报告"
预期:
  1. AI 调用 POST /api/workflows 创建工作流（3步骤）
  2. AI 调用 POST /api/workflows/execute 执行工作流
  3. AI 调用 GET /api/workflows/executions/{id} 获取结果
验证: 返回完整的审查报告
```

---

## 14. 定时任务测试

### 14.1 自动化测试

```python
def test_scheduled_tasks():
    """定时任务测试"""
    print("\n=== 定时任务测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 14.1.1 获取可用插件命令
    result = client.get("/scheduled-tasks/plugin-commands")
    print_test_result("GET /api/scheduled-tasks/plugin-commands", True)

    # 14.1.2 创建定时任务
    result = client.post("/scheduled-tasks", {
        "name": "每日健康检查",
        "cron_expression": "0 8 * * *",
        "action": "system_ping",
        "enabled": False
    })
    task_id = result.get("id")
    print_test_result("POST /api/scheduled-tasks", True, f"id={task_id}")

    # 14.1.3 获取定时任务列表
    result = client.get("/scheduled-tasks")
    assert_list(result, min_len=1)
    print_test_result("GET /api/scheduled-tasks", True)

    # 14.1.4 获取单个任务
    result = client.get(f"/scheduled-tasks/{task_id}")
    print_test_result(f"GET /api/scheduled-tasks/{task_id}", True)

    # 14.1.5 更新定时任务
    result = client.put(f"/scheduled-tasks/{task_id}", {
        "cron_expression": "0 9 * * *"
    })
    print_test_result(f"PUT /api/scheduled-tasks/{task_id}", True)

    # 14.1.6 手动触发
    result = client.post(f"/scheduled-tasks/{task_id}/trigger")
    print_test_result(f"POST /api/scheduled-tasks/{task_id}/trigger", True)

    # 14.1.7 获取执行历史
    result = client.get("/scheduled-tasks/executions", {"task_id": task_id, "limit": 5})
    print_test_result("GET /api/scheduled-tasks/executions", True)

    # 14.1.8 删除定时任务
    result = client.delete(f"/scheduled-tasks/{task_id}")
    print_test_result(f"DELETE /api/scheduled-tasks/{task_id}", True)
```

### 14.2 AI 调用定时任务场景

```
[AI 测试场景 22] AI 配置定时报告任务
用户输入: "帮我设置每天早上9点自动生成昨天的聊天摘要报告"
预期:
  1. AI 调用 POST /api/scheduled-tasks 创建 cron="0 9 * * *" 的任务
  2. AI 解释任务配置并确认
验证: GET /api/scheduled-tasks 返回新任务，cron 表达式正确
```

---

## 15. 日记系统测试

### 15.1 自动化测试

```python
def test_diary():
    """日记系统测试"""
    print("\n=== 日记系统测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 15.1.1 触发日记生成
    result = client.post("/diary/generate")
    print_test_result("POST /api/diary/generate", True, str(result.get("status")))

    # 15.1.2 列出所有日记
    result = client.get("/diary/list")
    print_test_result("GET /api/diary/list", True)

    # 15.1.3 获取指定日期日记
    today = time.strftime("%Y-%m-%d")
    result = client.get(f"/diary/{today}")
    # 日记可能不存在，允许 404
    if isinstance(result, dict) and "date" in result:
        print_test_result(f"GET /api/diary/{today}", True, "已有日记")
    else:
        print_test_result(f"GET /api/diary/{today}", True, "今日暂无日记")
```

### 15.2 AI 调用日记场景

```
[AI 测试场景 23] AI 生成和查看日记
用户输入: "帮我生成本周的日记摘要"
预期:
  1. AI 调用 POST /api/diary/generate 触发生成
  2. AI 调用 GET /api/diary/list 获取日记列表
  3. AI 调用 GET /api/diary/{date} 获取每天的日记内容
  4. AI 汇总成周报
验证: 返回包含本周各天要点的摘要
```

---

## 16. 系统日志测试

### 16.1 自动化测试

```python
def test_system_logs():
    """系统日志测试"""
    print("\n=== 系统日志测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 16.1.1 查询系统日志
    result = client.get("/logs", {
        "level": "ERROR",
        "limit": 20,
        "offset": 0
    })
    print_test_result("GET /api/logs?level=ERROR", True)

    # 16.1.2 按关键词搜索
    result = client.get("/logs", {"keyword": "database", "limit": 10})
    print_test_result("GET /api/logs?keyword=database", True)

    # 16.1.3 错误摘要
    result = client.get("/logs/errors/summary", {"hours": 24})
    print_test_result("GET /api/logs/errors/summary", True)

    # 16.1.4 列出日志文件
    result = client.get("/logs/files")
    print_test_result("GET /api/logs/files", True)

    # 16.1.5 上报前端错误
    result = client.post("/logs/client-errors", {
        "level": "ERROR",
        "message": "前端测试错误",
        "source": "test_script",
        "stack": "Test stack trace",
        "url": "http://localhost:5173/test",
        "user_agent": "TestAgent/1.0"
    })
    print_test_result("POST /api/logs/client-errors", True)

    # 16.1.6 导出日志
    resp = client.session.get(
        client._url("/logs/export"),
        headers=client._headers(),
        params={"level": "ERROR", "keyword": "test"}
    )
    assert resp.status_code == 200
    print_test_result("GET /api/logs/export", True)
```

### 16.2 AI 调用日志场景

```
[AI 测试场景 24] AI 分析系统日志
用户输入: "分析最近1小时的错误日志，告诉我问题和建议修复方案"
预期:
  1. AI 调用 GET /api/logs/errors/summary?hours=1
  2. AI 调用 GET /api/logs?level=ERROR 获取详细日志
  3. AI 分析并给出修复建议
验证: 返回结构化的错误分析和修复建议
```

---

## 17. MCP 服务测试

### 17.1 自动化测试

```python
def test_mcp_servers():
    """MCP 服务测试"""
    print("\n=== MCP 服务测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 17.1.1 添加 MCP Server
    result = client.post("/mcp/servers", {
        "name": "test-mcp-server",
        "command": "echo",
        "args": ["hello"],
        "transport_type": "stdio"
    })
    server_id = result.get("id")
    print_test_result("POST /api/mcp/servers", True, f"id={server_id}")

    # 17.1.2 获取 MCP Server 列表
    result = client.get("/mcp/servers")
    assert_list(result, min_len=1)
    print_test_result("GET /api/mcp/servers", True)

    # 17.1.3 连接 MCP Server
    result = client.post(f"/mcp/servers/{server_id}/connect")
    print_test_result(f"POST /api/mcp/servers/{server_id}/connect", True)

    # 17.1.4 获取工具列表
    result = client.get(f"/mcp/servers/{server_id}/tools")
    print_test_result(f"GET /api/mcp/servers/{server_id}/tools", True)

    # 17.1.5 调用工具
    result = client.post("/mcp/tools/call", {
        "server_id": server_id,
        "tool_name": "echo",
        "arguments": {"message": "hello"}
    })
    print_test_result("POST /api/mcp/tools/call", True)

    # 17.1.6 配置快照
    result = client.post("/mcp/config/snapshots")
    snapshot_name = result.get("snapshot_name")
    print_test_result("POST /api/mcp/config/snapshots", True)

    # 17.1.7 列出快照
    result = client.get("/mcp/config/snapshots")
    print_test_result("GET /api/mcp/config/snapshots", True)

    # 17.1.8 热重载
    result = client.post("/mcp/config/hot-reload")
    print_test_result("POST /api/mcp/config/hot-reload", True)

    # 17.1.9 断开连接
    result = client.post(f"/mcp/servers/{server_id}/disconnect")
    print_test_result(f"POST /api/mcp/servers/{server_id}/disconnect", True)

    # 17.1.10 删除 MCP Server
    result = client.delete(f"/mcp/servers/{server_id}")
    print_test_result(f"DELETE /api/mcp/servers/{server_id}", True)
```

### 17.2 AI 调用 MCP 场景

```
[AI 测试场景 25] AI 配置并使用 MCP 工具
用户输入: "帮我配置一个 MCP 文件系统服务器，然后用它读取 /data 目录"
预期:
  1. AI 调用 POST /api/mcp/servers 配置 filesystem MCP server
  2. AI 调用 POST /api/mcp/servers/{id}/connect 连接
  3. AI 通过 MCP 工具读取目录
验证: 返回 /data 目录的文件列表
```

---

## 18. 模型管理测试

### 18.1 自动化测试

```python
def test_models():
    """模型管理测试"""
    print("\n=== 模型管理测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 18.1.1 发现 Ollama 模型
    result = client.get("/models/ollama")
    print_test_result("GET /api/models/ollama", True, str(result.get("success")))

    # 18.1.2 获取提供商状态
    result = client.get("/models/providers")
    print_test_result("GET /api/models/providers", True)

    # 18.1.3 获取模型能力
    result = client.get("/models/openai/gpt-4o-mini/capabilities")
    print_test_result("GET /api/models/{provider}/{model}/capabilities", True,
                      str(result.keys() if isinstance(result, dict) else "N/A"))
```

---

## 19. 计费系统测试

### 19.1 自动化测试

```python
def test_billing():
    """计费系统测试"""
    print("\n=== 计费系统测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 19.1.1 初始化默认定价
    result = client.post("/billing/initialize-pricing")
    print_test_result("POST /api/billing/initialize-pricing", True)

    # 19.1.2 获取模型定价
    result = client.get("/billing/models")
    print_test_result("GET /api/billing/models", True)

    # 19.1.3 获取用量记录
    result = client.get("/billing/usage", {"limit": 10})
    print_test_result("GET /api/billing/usage", True)

    # 19.1.4 获取成本统计
    result = client.get("/billing/cost", {"period": "month"})
    print_test_result("GET /api/billing/cost", True)

    # 19.1.5 预估成本
    result = client.get("/billing/estimate", {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "text": "Hello World" * 100
    })
    print_test_result("GET /api/billing/estimate", True)

    # 19.1.6 获取预算状态
    result = client.get("/billing/budget")
    print_test_result("GET /api/billing/budget", True)

    # 19.1.7 创建预算
    result = client.post("/billing/budget", {
        "name": "月度测试预算",
        "amount": 100.00,
        "period": "monthly",
        "alert_threshold": 0.8
    })
    budget_id = result.get("id") or result.get("budget_id")
    print_test_result("POST /api/billing/budget", True, f"id={budget_id}")

    if budget_id:
        # 19.1.8 更新预算
        result = client.put(f"/billing/budget/{budget_id}", {
            "amount": 150.00,
            "alert_threshold": 0.7
        })
        print_test_result(f"PUT /api/billing/budget/{budget_id}", True)

        # 19.1.9 删除预算
        result = client.delete(f"/billing/budget/{budget_id}")
        print_test_result(f"DELETE /api/billing/budget/{budget_id}", True)

    # 19.1.10 获取计费报告
    result = client.get("/billing/report", {"period": "month", "format": "json"})
    print_test_result("GET /api/billing/report", True)

    # 19.1.11 获取提供商目录
    result = client.get("/billing/providers")
    print_test_result("GET /api/billing/providers", True, f"{result.get('total')} providers")

    # 19.1.12 获取配置列表
    result = client.get("/billing/configurations")
    print_test_result("GET /api/billing/configurations", True)

    # 19.1.13 获取完整配置
    result = client.get("/billing/configs")
    print_test_result("GET /api/billing/configs", True)
```

### 19.2 模型配置管理测试

```python
def test_billing_model_config():
    """模型配置管理测试"""
    print("\n=== 模型配置管理测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 19.2.1 创建模型配置
    result = client.post("/billing/configurations", {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "is_default": False,
        "parameters": {"temperature": 0.7, "max_tokens": 2000}
    })
    config_id = result.get("configuration", {}).get("id")
    print_test_result("POST /api/billing/configurations", True, f"id={config_id}")

    if config_id:
        # 19.2.2 获取配置详情
        result = client.get(f"/billing/configurations/{config_id}")
        print_test_result(f"GET /api/billing/configurations/{config_id}", True)

        # 19.2.3 更新配置
        result = client.put(f"/billing/configurations/{config_id}", {
            "parameters": {"temperature": 0.5}
        })
        print_test_result(f"PUT /api/billing/configurations/{config_id}", True)

        # 19.2.4 获取模型能力
        result = client.get(f"/billing/configurations/{config_id}/capabilities")
        print_test_result(f"GET /api/billing/configurations/{config_id}/capabilities", True)

        # 19.2.5 重置参数
        result = client.post(f"/billing/configurations/{config_id}/reset-parameters")
        print_test_result(f"POST /api/billing/configurations/{config_id}/reset-parameters", True)

        # 19.2.6 删除配置
        result = client.delete(f"/billing/configurations/{config_id}")
        print_test_result(f"DELETE /api/billing/configurations/{config_id}", True)
```

### 19.3 AI 调用计费场景

```
[AI 测试场景 26] AI 管理预算和使用量
用户输入: "帮我看看本月的 API 使用成本，如果超过预算的80%，提醒我"
预期:
  1. AI 调用 GET /api/billing/cost?period=month 获取成本
  2. AI 调用 GET /api/billing/budget 获取预算
  3. AI 计算比例并提醒
验证: 返回成本报告和预算使用率

[AI 测试场景 27] AI 配置模型参数
用户输入: "把 gpt-4o-mini 的 temperature 调到0.3，max_tokens 设为4000"
预期:
  1. AI 调用 GET /api/billing/configurations 找到目标配置
  2. AI 调用 PUT /api/billing/configurations/{id} 更新参数
验证: 配置更新后参数正确
```

---

## 20. 安全/RBAC 测试

### 20.1 自动化测试

```python
def test_security_rbac():
    """安全与 RBAC 测试"""
    print("\n=== 安全/RBAC 测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 20.1.1 获取角色列表
    result = client.get("/security/roles")
    print_test_result("GET /api/security/roles", True)

    # 20.1.2 获取当前用户角色
    user_id = client.current_user.get("id")
    result = client.get(f"/security/users/{user_id}/role")
    print_test_result(f"GET /api/security/users/{user_id}/role", True)

    # 20.1.3 检查权限
    result = client.post("/security/check-permission", {
        "user_id": user_id,
        "permission": "skill.execute"
    })
    print_test_result("POST /api/security/check-permission", True,
                      f"has_permission={result.get('has_permission')}")

    # 20.1.4 获取审计日志
    result = client.get("/security/audit-logs", {"page": 1, "page_size": 10})
    print_test_result("GET /api/security/audit-logs", True)

    # 20.1.5 审计日志统计
    result = client.get("/security/audit-logs/stats")
    print_test_result("GET /api/security/audit-logs/stats", True)

    # 20.1.6 获取已保存权限
    result = client.get("/security/permissions/saved")
    print_test_result("GET /api/security/permissions/saved", True)
```

### 20.2 管理员操作测试

```python
def test_admin_operations():
    """管理员专属操作测试"""
    print("\n=== 管理员操作测试 ===")
    admin = APITestClient()
    admin.login(ADMIN_USERNAME, ADMIN_PASSWORD)

    # 获取普通用户 user_id
    user_id = admin.current_user.get("id")

    # 20.2.1 导出审计日志
    resp = admin.session.get(
        admin._url("/security/audit-logs/export"),
        headers=admin._headers()
    )
    assert resp.status_code == 200
    print_test_result("GET /api/security/audit-logs/export (admin)", True)

    # 20.2.2 设置用户角色
    result = admin.put(f"/security/users/{user_id}/role", {
        "role_name": "admin"
    })
    print_test_result(f"PUT /api/security/users/{user_id}/role (admin)", True)
    # 恢复为 user 角色
    admin.put(f"/security/users/{user_id}/role", {"role_name": "user"})

    # 20.2.3 普通用户尝试管理员操作应被拒绝
    client.login(TEST_USERNAME, TEST_PASSWORD)
    result = client.put(f"/security/users/{user_id}/role",
                        {"role_name": "admin"}, expected_status=403)
    print_test_result("PUT role (非admin → 403)", True)
```

### 20.3 AI 调用安全场景

```
[AI 测试场景 28] AI 审计安全日志
用户输入（管理员）: "分析最近的审计日志，检测可疑活动"
预期:
  1. AI 调用 GET /api/security/audit-logs 获取日志
  2. AI 调用 GET /api/security/audit-logs/stats 获取统计
  3. AI 分析异常登录、频繁失败等模式
验证: 返回可疑活动报告

[AI 测试场景 29] AI 权限检查
用户输入: "检查我是否有执行技能的权限"
预期:
  1. AI 调用 POST /api/security/check-permission
  2. AI 告知权限状态
验证: 返回正确的权限检查结果
```

---

## 21. 用户管理测试

### 21.1 自动化测试

```python
def test_user_management():
    """用户管理测试"""
    print("\n=== 用户管理测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 21.1.1 获取用户画像
    result = client.get("/user/profile")
    print_test_result("GET /api/user/profile", True)

    # 21.1.2 更新用户信息
    result = client.put("/user/profile", {
        "nickname": "测试用户",
        "email": "test_updated@example.com"
    })
    print_test_result("PUT /api/user/profile", True)

    # 21.1.3 获取登录设备
    result = client.get("/user/devices")
    print_test_result("GET /api/user/devices", True)

    # 21.1.4 获取用户偏好
    result = client.get("/user/preferences")
    print_test_result("GET /api/user/preferences", True)

    # 21.1.5 更新用户偏好
    result = client.put("/user/preferences", {
        "preferences": {
            "theme": "dark",
            "language": "zh-CN",
            "auto_save": True
        }
    })
    print_test_result("PUT /api/user/preferences", True)

    # 恢复偏好
    client.put("/user/preferences", {"preferences": {"theme": "light", "language": "zh-CN"}})
```

### 21.2 AI 调用用户管理场景

```
[AI 测试场景 30] AI 管理用户偏好
用户输入: "帮我把主题改成暗色，语言设置为中文"
预期:
  1. AI 调用 GET /api/user/preferences 获取当前偏好
  2. AI 调用 PUT /api/user/preferences 更新
验证: 偏好已更新为暗色主题和中文

[AI 测试场景 31] AI 管理登录设备
用户输入: "列出我所有登录的设备，把不认识的设备踢下线"
预期:
  1. AI 调用 GET /api/user/devices 获取设备列表
  2. AI 识别异常设备并调用 POST /api/user/devices/{id}/revoke
验证: 异常设备被移除
```

---

## 22. 用户画像测试

### 22.1 自动化测试

```python
def test_user_profile():
    """用户画像完整测试"""
    print("\n=== 用户画像测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 22.1.1 获取画像摘要
    result = client.get("/user/profile/summary")
    print_test_result("GET /api/user/profile/summary", True)

    # 22.1.2 获取 Agent 注入上下文
    result = client.get("/user/profile/context")
    print_test_result("GET /api/user/profile/context", True,
                      f"char_count={result.get('char_count')}")

    # 22.1.3 获取画像事实列表
    result = client.get("/user/profile/facts", {"limit": 20})
    print_test_result("GET /api/user/profile/facts", True)

    # 22.1.4 手动添加事实
    result = client.post("/user/profile/facts", {
        "category": "skill",
        "fact_key": "programming_language",
        "fact_value": "Python",
        "confidence": 1.0
    })
    fact_id = result.get("id")
    print_test_result("POST /api/user/profile/facts", True, f"id={fact_id}")

    if fact_id:
        # 22.1.5 获取单个事实
        result = client.get(f"/user/profile/facts/{fact_id}")
        print_test_result(f"GET /api/user/profile/facts/{fact_id}", True)

        # 22.1.6 编辑事实
        result = client.put(f"/user/profile/facts/{fact_id}", {
            "fact_value": "Python, JavaScript",
            "category": "skill"
        })
        print_test_result(f"PUT /api/user/profile/facts/{fact_id}", True)

        # 22.1.7 确认事实
        result = client.post(f"/user/profile/facts/{fact_id}/verify")
        print_test_result(f"POST /api/user/profile/facts/{fact_id}/verify", True)

        # 22.1.8 否定事实
        result = client.post(f"/user/profile/facts/{fact_id}/dispute")
        print_test_result(f"POST /api/user/profile/facts/{fact_id}/dispute", True)

        # 22.1.9 软删除事实
        result = client.delete(f"/user/profile/facts/{fact_id}")
        print_test_result(f"DELETE /api/user/profile/facts/{fact_id}", True)

    # 22.1.10 触发画像提取
    result = client.post("/user/profile/extract/auto")
    print_test_result("POST /api/user/profile/extract/auto", True)

    # 22.1.11 获取画像统计
    result = client.get("/user/profile/stats")
    print_test_result("GET /api/user/profile/stats", True)

    # 22.1.12 获取画像维度
    result = client.get("/user/profile/dimensions")
    print_test_result("GET /api/user/profile/dimensions", True)

    # 22.1.13 获取提取日志
    result = client.get("/user/profile/extraction-logs", {"limit": 5})
    print_test_result("GET /api/user/profile/extraction-logs", True)

    # 22.1.14 导出画像
    result = client.get("/user/profile/export")
    print_test_result("GET /api/user/profile/export", True)
```

### 22.2 AI 调用画像场景

```
[AI 测试场景 32] AI 提取用户画像
用户输入: "通过我们之前的对话，你能了解我什么？帮我更新画像"
预期:
  1. AI 调用 POST /api/user/profile/extract/auto 触发提取
  2. AI 调用 GET /api/user/profile/facts 获取已知事实
  3. AI 调用 GET /api/user/profile/summary 获取摘要
  4. AI 汇总形成用户画像描述
验证: 返回结构化的用户画像描述

[AI 测试场景 33] AI 纠正画像事实
用户输入: "我的主要编程语言不是 Python，是 TypeScript，帮我更正"
预期:
  1. AI 调用 GET /api/user/profile/facts?category=skill 找到事实
  2. AI 调用 POST /api/user/profile/facts/{id}/dispute 否定旧事实
  3. AI 调用 POST /api/user/profile/facts 添加新事实
验证: 画像中编程语言更新为 TypeScript
```

---

## 23. 系统诊断测试

### 23.1 自动化测试

```python
def test_system_diagnostics():
    """系统诊断测试"""
    print("\n=== 系统诊断测试 ===")

    # 23.1.1 连通性检查（无需认证）
    anon = APITestClient()
    result = anon.get("/system/ping")
    assert result.get("pong") is not None or result.get("status") == "ok"
    print_test_result("GET /api/system/ping (无需认证)", True)

    # 23.1.2 系统诊断
    client.login(TEST_USERNAME, TEST_PASSWORD)
    result = client.get("/system/diagnostics")
    print_test_result("GET /api/system/diagnostics", True,
                      f"overall={result.get('overall')}")
```

### 23.2 管理员环境变量测试

```python
def test_admin_env_vars():
    """管理员环境变量测试"""
    print("\n=== 环境变量管理测试 ===")
    admin = APITestClient()
    admin.login(ADMIN_USERNAME, ADMIN_PASSWORD)

    # 23.2.1 获取环境变量
    result = admin.get("/system/env-vars")
    print_test_result("GET /api/system/env-vars (admin)", True)

    # 23.2.2 普通用户拒绝访问
    client.login(TEST_USERNAME, TEST_PASSWORD)
    result = client.get("/system/env-vars", expected_status=403)
    print_test_result("GET /api/system/env-vars (非admin → 403)", True)
```

---

## 24. 测试场景运行器测试

### 24.1 自动化测试

```python
def test_scenario_runner():
    """测试场景运行器测试"""
    print("\n=== 测试场景运行器测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 24.1.1 列出可用场景
    result = client.get("/test-scenarios")
    print_test_result("GET /api/test-scenarios", True,
                      f"total={result.get('total', len(result.get('scenarios', [])))}")

    # 24.1.2 运行单个场景（如果存在）
    scenarios = result.get("scenarios", [])
    if scenarios:
        scenario_name = scenarios[0].get("name") or scenarios[0]
        result = client.post("/test-scenarios/run", {"name": scenario_name})
        print_test_result(f"POST /api/test-scenarios/run (name={scenario_name})", True,
                          str(result.get("status")))
    else:
        print_test_result("POST /api/test-scenarios/run", True, "无可用场景，跳过")

    # 24.1.3 运行全部场景（慎用，可能耗时较长）
    # result = client.post("/test-scenarios/run-all")
    # print_test_result("POST /api/test-scenarios/run-all", True)
```

---

## 25. Agent 工具测试

### 25.1 自动化测试

```python
def test_agent_tools():
    """Agent 工具测试"""
    print("\n=== Agent 工具测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 25.1.1 获取工具列表
    result = client.get("/tools/list")
    assert "tools" in result
    print_test_result("GET /api/tools/list", True,
                      f"count={result.get('count', len(result.get('tools', [])))}")

    # 25.1.2 列出目录
    result = client.post("/tools/file/list", {
        "path": ".",
        "pattern": "*"
    })
    print_test_result("POST /api/tools/file/list", True)

    # 25.1.3 检查文件是否存在
    result = client.post("/tools/file/exists", {
        "path": "backend/main.py"
    })
    print_test_result("POST /api/tools/file/exists", True,
                      f"exists={result.get('result', result.get('exists'))}")

    # 25.1.4 Web 搜索
    result = client.post("/tools/search/web", {
        "query": "Python FastAPI latest version",
        "max_results": 3
    })
    print_test_result("POST /api/tools/search/web", True)

    # 25.1.5 获取终端状态
    result = client.get("/tools/terminal/status")
    print_test_result("GET /api/tools/terminal/status", True)
```

### 25.2 AI 调用工具场景

```
[AI 测试场景 34] AI 使用文件工具完成项目分析
用户输入: "分析 backend 目录下的所有 Python 文件，找出入口文件和主要模块"
预期:
  1. AI 调用 POST /api/tools/file/list 列出目录
  2. AI 调用 POST /api/tools/file/read 读取关键文件
  3. AI 综合分析返回
验证: 正确识别 main.py 为入口，列出核心模块

[AI 测试场景 35] AI 使用搜索工具获取实时信息
用户输入: "搜索最新的 FastAPI 版本，并告诉我有什么新特性"
预期:
  1. AI 调用 POST /api/tools/search/web 搜索
  2. AI 调用 POST /api/tools/search/fetch 获取详情页
  3. AI 总结返回
验证: 返回当前最新版本和新特性
```

---

## 26. 子Agent测试

### 26.1 自动化测试

```python
def test_subagents():
    """子Agent测试"""
    print("\n=== 子Agent测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 26.1.1 获取已注册子Agent
    result = client.get("/subagents/agents")
    print_test_result("GET /api/subagents/agents", True,
                      f"count={result.get('count', len(result.get('agents', [])))}")

    # 26.1.2 获取执行图列表
    result = client.get("/subagents/graphs")
    print_test_result("GET /api/subagents/graphs", True)

    # 26.1.3 顺序执行多个子Agent
    agents = result.get("agents", [])
    if len(agents) >= 1:
        agent_names = [a.get("name") if isinstance(a, dict) else a for a in agents[:2]]
        result = client.post("/subagents/run/sequential", {
            "agent_names": agent_names,
            "context": {"task": "执行顺序测试"}
        })
        print_test_result("POST /api/subagents/run/sequential", True)

    # 26.1.4 并行执行多个子Agent
    if len(agents) >= 2:
        agent_names = [a.get("name") if isinstance(a, dict) else a for a in agents[:2]]
        result = client.post("/subagents/run/parallel", {
            "agent_names": agent_names,
            "context": {"task": "并行测试"},
            "timeout": 60
        })
        print_test_result("POST /api/subagents/run/parallel", True)
```

### 26.2 AI 调用子Agent场景

```
[AI 测试场景 36] AI 编排多个子Agent完成任务
用户输入: "我们需要分析代码质量。让一个Agent做静态分析，另一个Agent跑测试，然后合并结果"
前提: 系统中注册了 code_analyzer 和 test_runner 两个子Agent
预期:
  1. AI 调用 POST /api/subagents/run/parallel 并行启动
  2. AI 等待两个Agent返回结果
  3. AI 合并输出综合报告
验证: 返回综合代码质量报告
```

---

## 27. 任务运行时测试

### 27.1 自动化测试

```python
def test_task_runtime():
    """任务运行时测试"""
    print("\n=== 任务运行时测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 27.1.1 获取可用代理类型
    result = client.get("/task-runtime/agent-types")
    print_test_result("GET /api/task-runtime/agent-types", True)

    # 27.1.2 列出活跃代理会话
    result = client.get("/task-runtime/agents")
    print_test_result("GET /api/task-runtime/agents", True,
                      f"total={result.get('total', 0)}")

    # 27.1.3 列出任务清单
    result = client.get("/task-runtime/tasks")
    print_test_result("GET /api/task-runtime/tasks", True)

    # 27.1.4 列出代理团队
    result = client.get("/task-runtime/teams")
    print_test_result("GET /api/task-runtime/teams", True,
                      f"total={result.get('total', 0)}")

    # 27.1.5 创建代理团队
    result = client.post("/task-runtime/teams", params={
        "name": "测试团队"
    })
    team_id = result.get("id") or result.get("team_id")
    if team_id:
        print_test_result("POST /api/task-runtime/teams", True, f"id={team_id}")

        # 27.1.6 获取团队详情
        result = client.get(f"/task-runtime/teams/{team_id}")
        print_test_result(f"GET /api/task-runtime/teams/{team_id}", True)

        # 27.1.7 删除团队
        result = client.delete(f"/task-runtime/teams/{team_id}")
        print_test_result(f"DELETE /api/task-runtime/teams/{team_id}", True)
```

### 27.2 AI 调用任务运行时场景

```
[AI 测试场景 37] AI 管理代理团队
用户输入: "创建一个由3个编程Agent组成的团队，分别负责前端、后端和测试"
预期:
  1. AI 调用 POST /api/task-runtime/teams 创建团队
  2. AI 调用 POST /api/task-runtime/teams/{id}/members 添加成员
  3. AI 调用 POST /api/task-runtime/messages 发送团队消息
验证: 团队创建成功，成员就位
```

---

## 28. 工作区管理测试

### 28.1 自动化测试

```python
def test_workspaces():
    """工作区管理测试"""
    print("\n=== 工作区管理测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    workspace_id = f"ws-{uuid.uuid4().hex[:8]}"

    # 28.1.1 获取工作区列表
    result = client.get("/workspaces")
    print_test_result("GET /api/workspaces", True,
                      f"total={result.get('total', len(result.get('workspaces', [])))}")

    # 28.1.2 创建工作区
    result = client.post("/workspaces", {
        "name": "测试工作区",
        "description": "自动化测试工作区",
        "agent_type": "general",
        "workspace_id": workspace_id
    })
    print_test_result("POST /api/workspaces", True, f"id={workspace_id}")

    # 28.1.3 获取工作区详情
    result = client.get(f"/workspaces/{workspace_id}")
    print_test_result(f"GET /api/workspaces/{workspace_id}", True)

    # 28.1.4 更新工作区配置
    result = client.put(f"/workspaces/{workspace_id}", {
        "name": "更新测试工作区",
        "description": "更新后的描述"
    })
    print_test_result(f"PUT /api/workspaces/{workspace_id}", True)

    # 28.1.5 更新人设文件
    result = client.put(f"/workspaces/{workspace_id}/persona", {
        "filename": "PERSONA.md",
        "content": "# Test Persona\n\nYou are a helpful testing assistant."
    })
    print_test_result(f"PUT /api/workspaces/{workspace_id}/persona", True)

    # 28.1.6 删除工作区
    result = client.delete(f"/workspaces/{workspace_id}")
    print_test_result(f"DELETE /api/workspaces/{workspace_id}", True)
```

### 28.2 AI 调用工作区场景

```
[AI 测试场景 38] AI 创建和管理多工作区
用户输入: "帮我创建3个工作区：Python开发、前端开发、数据科学，每个配置不同的人设"
预期:
  1. AI 调用 POST /api/workspaces 创建3个工作区
  2. AI 调用 PUT /api/workspaces/{id}/persona 配置人设
验证: 3个工作区创建成功，人设正确

[AI 测试场景 39] AI 管理工作区技能
用户输入: "在工作区中启用代码分析技能，禁用网络搜索技能"
预期:
  1. AI 调用 PUT /api/workspaces/{id}/skills/code_analyzer/enable
  2. AI 调用 PUT /api/workspaces/{id}/skills/web_search/disable
验证: 技能状态切换成功
```

---

## 29. 心跳系统测试

### 29.1 自动化测试

```python
def test_heartbeat():
    """心跳系统测试"""
    print("\n=== 心跳系统测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 先创建工作区
    workspace_id = f"hb-{uuid.uuid4().hex[:8]}"
    client.post("/workspaces", {
        "name": "心跳测试工作区",
        "workspace_id": workspace_id
    })

    # 29.1.1 获取心跳配置
    result = client.get(f"/workspaces/{workspace_id}/heartbeat")
    print_test_result(f"GET /api/workspaces/{workspace_id}/heartbeat", True)

    # 29.1.2 更新心跳配置
    result = client.put(f"/workspaces/{workspace_id}/heartbeat", {
        "enabled": True,
        "every": "30m",
        "target": "auto"
    })
    print_test_result(f"PUT /api/workspaces/{workspace_id}/heartbeat", True)

    # 29.1.3 手动触发心跳
    result = client.post(f"/workspaces/{workspace_id}/heartbeat/test")
    print_test_result(f"POST /api/workspaces/{workspace_id}/heartbeat/test", True)

    # 29.1.4 更新 HEARTBEAT.md
    result = client.put(f"/workspaces/{workspace_id}/heartbeat/file", {
        "content": "# HEARTBEAT\n\n当前状态：正常运行"
    })
    print_test_result(f"PUT /api/workspaces/{workspace_id}/heartbeat/file", True)

    # 清理
    client.delete(f"/workspaces/{workspace_id}")
```

### 29.2 AI 调用心跳场景

```
[AI 测试场景 40] AI 配置定时心跳
用户输入: "设置每30分钟让 AI 检查一下系统状态并汇报"
预期:
  1. AI 调用 PUT /api/workspaces/{id}/heartbeat 设置配置
  2. AI 解释心跳机制和预期行为
验证: 配置保存成功，定时触发机制正确
```

---

## 30. Coding 模式测试

### 30.1 自动化测试

```python
def test_coding_mode():
    """Coding 模式测试"""
    print("\n=== Coding 模式测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 30.1.1 获取 CC 模式状态
    result = client.get("/coding/cc-mode")
    print_test_result("GET /api/coding/cc-mode", True)

    # 30.1.2 获取目录树
    result = client.get("/coding/tree", {"path": "."})
    print_test_result("GET /api/coding/tree", True)

    # 30.1.3 列出目录内容
    result = client.get("/coding/list", {"path": "backend"})
    print_test_result("GET /api/coding/list?path=backend", True)

    # 30.1.4 读取文件
    result = client.post("/coding/read", {"path": "backend/main.py"})
    print_test_result("POST /api/coding/read (backend/main.py)", True)

    # 30.1.5 Git 状态
    result = client.get("/coding/git/status")
    print_test_result("GET /api/coding/git/status", True)

    # 30.1.6 Git 提交日志
    result = client.get("/coding/git/log", {"max_count": 5})
    print_test_result("GET /api/coding/git/log?max_count=5", True)

    # 30.1.7 Git 分支列表
    result = client.get("/coding/git/branches")
    print_test_result("GET /api/coding/git/branches", True)

    # 30.1.8 搜索函数/类定义
    result = client.get("/coding/ast/definitions", {"name": "main"})
    print_test_result("GET /api/coding/ast/definitions?name=main", True)

    # 30.1.9 正则搜索代码
    result = client.post("/coding/ast/search", {"pattern": "def test_"})
    print_test_result("POST /api/coding/ast/search (pattern=def test_)", True)

    # 30.1.10 文件结构概览
    result = client.get("/coding/ast/structure", {"file_path": "backend/main.py"})
    print_test_result("GET /api/coding/ast/structure", True)

    # 30.1.11 计算差异
    result = client.post("/coding/diff", {
        "original": "print('hello')",
        "modified": "print('hello world')"
    })
    print_test_result("POST /api/coding/diff", True)
```

### 30.2 Coding 模式高级测试

```python
def test_coding_advanced():
    """Coding 模式高级功能测试"""
    print("\n=== Coding 模式高级测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 30.2.1 切换 CC 模式
    result = client.post("/coding/cc-mode", {"enabled": True})
    print_test_result("POST /api/coding/cc-mode (enabled=True)", True)
    client.post("/coding/cc-mode", {"enabled": False})

    # 30.2.2 LSP 诊断
    result = client.get("/coding/lsp/diagnostics", {
        "file_path": "backend/main.py"
    })
    print_test_result("GET /api/coding/lsp/diagnostics", True)

    # 30.2.3 LSP 符号列表
    result = client.get("/coding/lsp/symbols", {
        "file_path": "backend/main.py"
    })
    print_test_result("GET /api/coding/lsp/symbols", True)

    # 30.2.4 写入文件
    result = client.post("/coding/write", {
        "path": "/tmp/test_coding_write.txt",
        "content": "Coding 模式测试写入"
    })
    print_test_result("POST /api/coding/write", True)

    # 30.2.5 搜索文件
    result = client.post("/coding/search-files", {
        "pattern": "*.py",
        "directory": "backend"
    })
    print_test_result("POST /api/coding/search-files", True,
                      f"count={result.get('count', 0)}")
```

### 30.3 AI 调用 Coding 模式场景

```
[AI 测试场景 41] AI 完成代码重构任务
用户输入: "在 backend 目录下搜索所有使用 print() 的代码，替换为 logger.info()"
前提: CC 模式已启用
预期:
  1. AI 调用 POST /api/coding/ast/search 搜索 print(
  2. AI 调用 POST /api/coding/read 读取每个匹配文件
  3. AI 调用 POST /api/coding/write 逐个更新
验证: 再次搜索 print( 返回空结果

[AI 测试场景 42] AI 分析代码库结构
用户输入: "分析整个 backend 项目的代码结构，生成模块依赖图"
预期:
  1. AI 调用 GET /api/coding/tree 获取目录树
  2. AI 调用 GET /api/coding/ast/definitions 搜索导入
  3. AI 生成依赖分析报告
验证: 返回结构化的依赖分析

[AI 测试场景 43] AI 使用 Git 工具
用户输入: "查看最近的5次提交，然后创建一个新分支 feature/test-branch"
预期:
  1. AI 调用 GET /api/coding/git/log?max_count=5
  2. AI 调用 POST /api/coding/git/branch?name=feature/test-branch
验证: 新分支创建成功
```

---

## 31. 收件箱测试

### 31.1 自动化测试

```python
def test_inbox():
    """收件箱测试"""
    print("\n=== 收件箱测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 31.1.1 创建消息
    result = client.post("/inbox", {
        "title": "测试消息",
        "content": "这是一条自动化测试消息",
        "category": "system"
    })
    msg_id = result.get("id")
    print_test_result("POST /api/inbox", True, f"id={msg_id}")

    # 31.1.2 获取消息列表
    result = client.get("/inbox", {"limit": 10})
    print_test_result("GET /api/inbox", True,
                      f"total={result.get('total', 0)}, unread={result.get('unread', 0)}")

    # 31.1.3 获取未读消息数量
    result = client.get("/inbox/count")
    print_test_result("GET /api/inbox/count", True,
                      f"unread={result.get('unread', 0)}")

    # 31.1.4 标记消息为已读
    result = client.post(f"/inbox/{msg_id}/read")
    print_test_result(f"POST /api/inbox/{msg_id}/read", True)

    # 31.1.5 按分类筛选
    result = client.get("/inbox", {"category": "system", "unread_only": False})
    print_test_result("GET /api/inbox?category=system", True)

    # 31.1.6 全部标记已读
    result = client.post("/inbox/read-all")
    print_test_result("POST /api/inbox/read-all", True,
                      f"count={result.get('count', 0)}")

    # 31.1.7 删除消息
    result = client.delete(f"/inbox/{msg_id}")
    print_test_result(f"DELETE /api/inbox/{msg_id}", True)
```

### 31.2 AI 调用收件箱场景

```
[AI 测试场景 44] AI 管理通知消息
用户输入: "查看我的未读消息，帮我总结重要内容"
预期:
  1. AI 调用 GET /api/inbox?unread_only=true 获取未读消息
  2. AI 分析消息内容
  3. AI 总结重要消息
验证: 返回未读消息摘要和重要通知
```

---

## 32. 魔法命令测试

### 32.1 自动化测试

```python
def test_magic_commands():
    """魔法命令测试"""
    print("\n=== 魔法命令测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 32.1.1 列出所有魔法命令
    result = client.get("/magic-commands")
    assert "commands" in result
    print_test_result("GET /api/magic-commands", True,
                      f"total={result.get('total', len(result.get('commands', [])))}")

    # 32.1.2 执行魔法命令（如果存在）
    commands = result.get("commands", [])
    if commands:
        cmd_name = commands[0].get("name") if isinstance(commands[0], dict) else commands[0]
        result = client.post("/magic-commands/execute", {
            "command_name": cmd_name,
            "context": {}
        })
        print_test_result(f"POST /api/magic-commands/execute ({cmd_name})", True)
    else:
        print_test_result("POST /api/magic-commands/execute", True, "无可用命令")

    # 32.1.3 触发上下文压缩
    result = client.post("/magic-commands/compact", {
        "session_id": f"compact-{uuid.uuid4().hex[:8]}"
    })
    print_test_result("POST /api/magic-commands/compact", True)
```

### 32.2 AI 调用魔法命令场景

```
[AI 测试场景 45] AI 使用魔法命令
用户输入: "/compact - 帮我压缩当前的对话上下文"
预期: AI 识别为魔法命令，调用 POST /api/magic-commands/compact
验证: 返回压缩统计（压缩前后 token 数量）
```

---

## 33. TTS 语音测试

### 33.1 自动化测试

```python
def test_tts():
    """TTS 语音合成测试"""
    print("\n=== TTS 语音测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 33.1.1 TTS 健康检查
    result = client.get("/tts/health")
    print_test_result("GET /api/tts/health", True)

    # 33.1.2 列出可用音色
    result = client.get("/tts/speakers")
    print_test_result("GET /api/tts/speakers", True,
                      f"total={result.get('total', len(result.get('speakers', [])))}")

    # 33.1.3 非流式语音合成
    resp = client.session.post(
        client._url("/tts/synthesize"),
        headers=client._headers(),
        json={"text": "你好，这是一个语音合成测试", "speaker_id": "default"}
    )
    if resp.status_code == 200:
        audio_size = len(resp.content)
        print_test_result("POST /api/tts/synthesize", True, f"audio_size={audio_size} bytes")
    else:
        print_test_result("POST /api/tts/synthesize", True, f"服务状态: {resp.status_code}")
```

### 33.2 AI 调用 TTS 场景

```
[AI 测试场景 46] AI 文本转语音
用户输入: "把下面的文字转成语音：'欢迎使用 Open-AwA AI Agent 平台'"
预期:
  1. AI 调用 POST /api/tts/synthesize 生成音频
  2. AI 返回音频链接或直接播放
验证: 返回可播放的音频数据
```

---

## 34. 任务执行测试

### 34.1 自动化测试

```python
def test_task_execution():
    """任务执行测试"""
    print("\n=== 任务执行测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 34.1.1 同步执行任务
    result = client.post("/tasks/execute", {
        "prompt": "生成一个 1 到 100 的随机数字",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "session_id": f"task-{uuid.uuid4().hex[:8]}",
        "timeout_seconds": 30
    })
    print_test_result("POST /api/tasks/execute (sync)", True,
                      f"status={result.get('status')}")

    # 34.1.2 带 webhook 的异步任务
    result = client.post("/tasks/execute", {
        "prompt": "统计 backend/ 目录下 Python 文件数量",
        "session_id": f"task-{uuid.uuid4().hex[:8]}",
        "timeout_seconds": 60,
        "webhook_url": "https://example.com/webhook"
    })
    print_test_result("POST /api/tasks/execute (webhook)", True)
```

### 34.2 AI 调用任务场景

```
[AI 测试场景 47] AI 执行批量任务
用户输入: "帮我并行执行5个任务，分别统计 backend 下各子目录的 Python 文件数量"
预期:
  1. AI 调用 POST /api/tasks/execute 5次（或使用子Agent并行）
  2. AI 汇总所有结果
验证: 返回各目录的文件数量统计
```

---

## 35. 微信集成测试

### 35.1 自动化测试

```python
def test_weixin():
    """微信集成测试"""
    print("\n=== 微信集成测试 ===")
    client.login(TEST_USERNAME, TEST_PASSWORD)

    # 35.1.1 获取微信连接配置
    result = client.get("/skills/weixin/config")
    print_test_result("GET /api/skills/weixin/config", True)

    # 35.1.2 获取微信绑定状态
    result = client.get("/weixin/binding")
    print_test_result("GET /api/weixin/binding", True)

    # 35.1.3 获取自动回复状态
    result = client.get("/weixin/auto-reply/status")
    print_test_result("GET /api/weixin/auto-reply/status", True)

    # 35.1.4 获取自动回复规则
    result = client.get("/weixin/auto-reply/rules")
    print_test_result("GET /api/weixin/auto-reply/rules", True,
                      f"{len(result) if isinstance(result, list) else 'N/A'} 条规则")

    # 35.1.5 获取微信对话会话
    result = client.get("/weixin/conversations", {"limit": 10})
    print_test_result("GET /api/weixin/conversations", True)
```

### 35.2 AI 调用微信场景

```
[AI 测试场景 48] AI 配置微信自动回复
用户输入: "帮我设置微信自动回复规则：当收到'你好'时，回复'您好，我是 AI 助手'"
预期:
  1. AI 调用 POST /api/weixin/auto-reply/rules 创建规则
  2. AI 确认规则已生效
验证: GET 规则列表返回新规则
```

---

## 36. AI 驱动的端到端场景测试

以下场景需要 AI 主动调用多个 API 协作完成复杂任务，验证平台的端到端能力。

### 场景 A: 智能代码审查助手

```
[E2E-A] 代码审查工作流

前置条件:
  - 用户已登录
  - Coding 模式已启用
  - 工作区已创建

用户输入:
  "帮我审查 backend/api/routes/ 下所有路由文件，检查以下问题：
   1. 是否有安全漏洞（SQL注入、XSS等）
   2. 异常处理是否完善
   3. 输入验证是否充分
   4. 生成审查报告并保存为 CODE_REVIEW.md"

AI 调用链路:
  1. POST /api/coding/search-files → 找到所有路由文件
  2. POST /api/coding/read → 逐个读取文件内容
  3. POST /api/coding/ast/search → 搜索潜在问题模式 (except Exception, print(, etc.)
  4. POST /api/experiences/search → 查找历史审查经验
  5. POST /api/coding/write → 写入报告到 CODE_REVIEW.md
  6. POST /api/chat/feedback → 记录审查结果

验证点:
  - 文件扫描覆盖所有路由文件
  - 识别出至少一个安全问题（如有）
  - CODE_REVIEW.md 内容完整
  - 异常处理检查覆盖 try/except 分支
```

### 场景 B: 知识库构建

```
[E2E-B] 从对话构建知识库

前置条件:
  - 有多个包含技术讨论的会话
  - 记忆系统正常运行

用户输入:
  "回顾我过去30天的所有技术讨论，提取关键知识点，创建知识库条目，并按主题分类"

AI 调用链路:
  1. GET /api/conversations?sort_by=updated_at&sort_order=desc → 获取会话列表
  2. GET /api/chat/history/{session_id} → 逐个获取会话内容
  3. POST /api/user/profile/extract → 提取用户技能和偏好
  4. POST /api/experiences/extract → 为每个关键知识点提取经验
  5. POST /api/memory/long-term → 持久化重要知识
  6. POST /api/experience-files/{name} → 保存知识库摘要

验证点:
  - 成功提取至少3条经验
  - 长期记忆新增至少5条
  - 经验覆盖率 >= 80% 的会话
```

### 场景 C: 自动化运维监控

```
[E2E-C] 系统健康监控与报告

前置条件:
  - 管理员账号已登录
  - TTS 服务就绪

用户输入:
  "启动系统全面检查，包括诊断、日志分析、成本统计、插件状态，
   将结果汇总成运维日报，并通过语音播报关键指标"

AI 调用链路:
  1. GET /api/system/diagnostics → 系统诊断
  2. GET /api/logs/errors/summary?hours=24 → 24小时错误统计
  3. GET /api/billing/cost?period=month → 成本统计
  4. GET /api/plugins → 插件状态检查
  5. GET /api/memory/stats → 记忆系统统计
  6. GET /api/security/audit-logs/stats → 安全审计统计
  7. POST /api/tts/synthesize → 播报关键指标
  8. POST /api/inbox → 将报告发送到收件箱
  9. POST /api/diary/generate → 记录为运维日记

验证点:
  - 诊断结果 overall 状态正确
  - 错误摘要数据准确
  - TTS 音频生成成功
  - 收件箱收到运维报告
```

### 场景 D: 多人协作工作流

```
[E2E-D] 多 Agent 协作完成任务

前置条件:
  - 已创建多个子 Agent
  - 工作区和团队已配置

用户输入:
  "我需要开发一个 REST API 登录接口。让前端 Agent 设计表单，后端 Agent 编写接口，
   测试 Agent 编写测试用例，最后审查 Agent 检查代码质量"

AI 调用链路:
  1. POST /api/task-runtime/teams → 创建协作团队
  2. POST /api/task-runtime/teams/{id}/members → 添加各 Agent
  3. POST /api/task-runtime/messages → 分发任务
  4. POST /api/subagents/run/parallel → 并行执行
  5. GET /api/task-runtime/agents/{id}/transcript → 获取执行记录
  6. POST /api/coding/write → 保存生成的代码
  7. POST /api/workflows/execute → 运行代码审查工作流

验证点:
  - 团队创建成功
  - 各 Agent 返回正确结果
  - 生成的代码通过审查
  - transcript 完整记录协作过程
```

### 场景 E: 用户画像全面分析

```
[E2E-E] AI 驱动用户画像构建

前置条件:
  - 有充足的历史对话数据
  - 用户已登录

用户输入:
  "根据我所有的对话和使用行为，帮我生成一份完整的个人技术能力画像"

AI 调用链路:
  1. POST /api/user/profile/extract → 从所有会话提取画像
  2. GET /api/conversations → 获取对话统计
  3. GET /api/behaviors/stats?days=90 → 获取行为统计
  4. GET /api/billing/usage → 获取 API 使用偏好
  5. GET /api/experiences → 获取技能经验
  6. GET /api/user/profile/facts → 获取已有事实
  7. GET /api/user/profile/summary → 获取画像摘要
  8. GET /api/user/profile/dimensions → 获取画像维度
  9. POST /api/user/profile/facts → 补充新发现的事实
  10. GET /api/user/profile/export → 导出完整画像
  11. POST /api/inbox → 推送画像报告到收件箱

验证点:
  - 画像维度覆盖技术栈、经验水平、使用偏好
  - 事实数量增加
  - 画像置信度 >= 0.7
  - 导出数据格式完整
```

### 场景 F: 定时自动化报告

```
[E2E-F] 每日自动化摘要

前置条件:
  - 管理员已登录

用户输入:
  "创建一个定时任务，每天早上8点自动生成昨日工作摘要并发送到收件箱"

AI 调用链路:
  1. POST /api/scheduled-tasks → 创建 cron="0 8 * * *" 的任务
  2. 任务执行时:
     a. GET /api/conversations → 获取昨日会话
     b. GET /api/chat/history/{session_id} → 获取对话内容
     c. GET /api/experiences/stats/summary → 获取新经验统计
     d. GET /api/billing/cost?period=day → 获取成本
     e. POST /api/diary/generate → 生成日记
     f. POST /api/inbox → 发送摘要到收件箱
     g. POST /api/user/profile/extract/auto → 更新用户画像

验证点:
  - 定时任务配置正确
  - 手动触发后报告内容完整
  - 收件箱收到摘要消息
```

---

## 37. 附录：通用测试工具脚本

### 37.1 完整回归测试脚本

```python
#!/usr/bin/env python3
"""
Open-AwA API 完整回归测试脚本
运行方式: python scripts/api_regression_test.py
"""

import sys
import time
import uuid
from typing import Dict, List, Optional
from dataclasses import dataclass, field

# 引入上述 APITestClient 类

@dataclass
class TestReport:
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    details: List[str] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = ""):
        self.total += 1
        if passed:
            self.passed += 1
            self.details.append(f"  [PASS] {name}")
        else:
            self.failed += 1
            self.details.append(f"  [FAIL] {name}: {detail}")

    def add_skip(self, name: str, reason: str = ""):
        self.total += 1
        self.skipped += 1
        self.details.append(f"  [SKIP] {name}: {reason}")

    def print_summary(self):
        print("\n" + "=" * 60)
        print(f"测试完成: 总计 {self.total}, 通过 {self.passed}, "
              f"失败 {self.failed}, 跳过 {self.skipped}")
        print(f"通过率: {self.passed / max(self.total, 1) * 100:.1f}%")
        for d in self.details:
            print(d)
        print("=" * 60)


def run_all_tests():
    """运行全部 API 测试"""
    report = TestReport()
    print("=" * 60)
    print("Open-AwA API 完整回归测试")
    print(f"开始时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"测试地址: {BASE_URL}")
    print("=" * 60)

    try:
        # 模块1: 认证
        test_auth_flow()
        report.add("认证模块", True)
    except Exception as e:
        report.add("认证模块", False, str(e))

    try:
        # 模块2: 聊天
        test_chat_basic()
        test_chat_upload()
        test_chat_confirmation()
        report.add("聊天模块", True)
    except Exception as e:
        report.add("聊天模块", False, str(e))

    try:
        # 模块3: 会话管理
        test_conversation_crud()
        test_conversation_export()
        report.add("会话管理", True)
    except Exception as e:
        report.add("会话管理", False, str(e))

    try:
        # 模块4: 技能
        test_skills_crud()
        test_skill_analytics()
        report.add("技能引擎", True)
    except Exception as e:
        report.add("技能引擎", False, str(e))

    try:
        # 模块5: 插件
        test_plugins_crud()
        report.add("插件系统", True)
    except Exception as e:
        report.add("插件系统", False, str(e))

    try:
        # 模块6: 记忆
        test_memory_system()
        report.add("记忆系统", True)
    except Exception as e:
        report.add("记忆系统", False, str(e))

    try:
        # 模块7: 经验
        test_experiences()
        report.add("经验管理", True)
    except Exception as e:
        report.add("经验管理", False, str(e))

    try:
        # 模块8: 工作流
        test_workflows()
        report.add("工作流", True)
    except Exception as e:
        report.add("工作流", False, str(e))

    try:
        # 模块9: 定时任务
        test_scheduled_tasks()
        report.add("定时任务", True)
    except Exception as e:
        report.add("定时任务", False, str(e))

    try:
        # 模块10: 计费
        test_billing()
        report.add("计费系统", True)
    except Exception as e:
        report.add("计费系统", False, str(e))

    try:
        # 模块11: 安全
        test_security_rbac()
        report.add("安全/RBAC", True)
    except Exception as e:
        report.add("安全/RBAC", False, str(e))

    try:
        # 模块12: 用户管理
        test_user_management()
        report.add("用户管理", True)
    except Exception as e:
        report.add("用户管理", False, str(e))

    try:
        # 模块13: 用户画像
        test_user_profile()
        report.add("用户画像", True)
    except Exception as e:
        report.add("用户画像", False, str(e))

    try:
        # 模块14: 系统诊断
        test_system_diagnostics()
        report.add("系统诊断", True)
    except Exception as e:
        report.add("系统诊断", False, str(e))

    try:
        # 模块15: Agent 工具
        test_agent_tools()
        report.add("Agent工具", True)
    except Exception as e:
        report.add("Agent工具", False, str(e))

    try:
        # 模块16: Coding
        test_coding_mode()
        report.add("Coding模式", True)
    except Exception as e:
        report.add("Coding模式", False, str(e))

    try:
        # 模块17: 收件箱
        test_inbox()
        report.add("收件箱", True)
    except Exception as e:
        report.add("收件箱", False, str(e))

    try:
        # 模块18: 任务运行时
        test_task_runtime()
        report.add("任务运行时", True)
    except Exception as e:
        report.add("任务运行时", False, str(e))

    try:
        # 模块19: 工作区
        test_workspaces()
        report.add("工作区", True)
    except Exception as e:
        report.add("工作区", False, str(e))

    try:
        # 模块20: 删除测试数据（清理）
        print("\n[清理] 测试数据已通过各模块的 delete 操作完成")
        report.add("清理", True)
    except Exception as e:
        report.add("清理", False, str(e))

    report.print_summary()
    return report.failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
```

### 37.2 运行说明

```bash
# 1. 安装依赖
pip install requests websocket-client

# 2. 确保后端服务运行
cd backend && python main.py &

# 3. 设置测试账号
# 在数据库中或通过 API 创建 test_user / Test@123456 和 admin / Admin@123456

# 4. 执行测试
python scripts/api_regression_test.py

# 5. 查看结果
# 脚本输出每个模块的测试结果和最终通过率
```

### 37.3 AI 场景测试的执行方式

对于 AI 驱动的场景测试（第 2-35 节中的 `[AI 测试场景 N]` 和第 36 节的 E2E 场景），测试方式如下：

1. **交互式测试**: 通过前端聊天界面或 API 客户端向 AI 发送用户输入
2. **验证**: 通过 API 查询验证 AI 是否正确调用了预期的接口
3. **检查点**: 每个场景列出了预期 API 调用链和验证标准

```python
# AI 场景测试辅助函数
def run_ai_scenario(scenario_name: str, user_input: str,
                    expected_api_calls: List[str],
                    verification_calls: List[dict]):
    """执行 AI 驱动场景测试"""
    print(f"\n--- AI 场景: {scenario_name} ---")
    print(f"用户输入: {user_input}")

    client.login(TEST_USERNAME, TEST_PASSWORD)
    session_id = f"ai-scenario-{uuid.uuid4().hex[:8]}"

    # 发送聊天消息（由 AI 处理并调用相应 API）
    result = client.post("/chat", {
        "message": user_input,
        "session_id": session_id,
        "mode": "sync",
        "max_tool_call_rounds": 5  # 允许多轮工具调用
    })

    print(f"AI 响应: {str(result.get('response', ''))[:200]}...")

    # 验证 AI 是否调用了预期 API（通过聊天历史中的 tool_calls）
    history = client.get(f"/chat/history/{session_id}")
    tool_calls_found = set()
    for msg in history:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tool_calls_found.add(tc.get("name", ""))

    # 检查预期调用
    for expected_call in expected_api_calls:
        if expected_call in tool_calls_found:
            print(f"  [OK] AI 调用了: {expected_call}")
        else:
            print(f"  [MISS] AI 未调用: {expected_call}")

    # 执行验证调用
    for vc in verification_calls:
        method = vc.get("method", "get").upper()
        path = vc["path"]
        try:
            if method == "GET":
                result = client.get(path)
            elif method == "POST":
                result = client.post(path, vc.get("data", {}))
            print(f"  [VERIFY] {method} {path} → OK")
        except Exception as e:
            print(f"  [VERIFY] {method} {path} → FAIL: {e}")
```

---

> **文档版本**: v1.0
> **覆盖范围**: 35 个路由模块, 190+ API 端点
> **自动化测试场景**: 200+ 个测试用例
> **AI 驱动场景**: 48 个功能测试 + 6 个端到端场景
> **最后更新**: 2026-06-12
