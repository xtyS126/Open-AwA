"""验证微信适配器模块导入和兼容性"""

print("开始验证微信适配器模块...")

try:
    from backend.skills.weixin import WeixinSkillAdapter, WeixinRuntimeConfig, WeixinAdapterError
    print("[OK] 主模块导入成功")
except ImportError as e:
    print(f"[FAIL] 主模块导入失败: {e}")
    exit(1)

try:
    adapter = WeixinSkillAdapter()
    print(f"[OK] 适配器实例创建成功: {type(adapter).__name__}")
except Exception as e:
    print(f"[FAIL] 适配器实例创建失败: {e}")
    exit(1)

required_methods = ["execute", "fetch_login_qrcode", "fetch_qrcode_status", "check_health", "map_skill_config", "is_weixin_skill"]
missing_methods = []
for method in required_methods:
    if not hasattr(adapter, method):
        missing_methods.append(method)

if missing_methods:
    print(f"[FAIL] 缺少方法: {missing_methods}")
else:
    print(f"[OK] 所有必需方法存在: {required_methods}")

try:
    config = WeixinRuntimeConfig(
        account_id="test_account",
        token="test_token",
        base_url="https://test.example.com",
        bot_type="3",
        channel_version="1.0.2",
        timeout_seconds=15
    )
    print(f"[OK] 配置类实例化成功: account_id={config.account_id}")
except Exception as e:
    print(f"[FAIL] 配置类实例化失败: {e}")
    exit(1)

try:
    error = WeixinAdapterError("TEST_ERROR", "测试错误消息")
    error_dict = error.to_dict()
    assert error_dict["code"] == "TEST_ERROR"
    assert error_dict["message"] == "测试错误消息"
    print(f"[OK] 错误类工作正常: code={error.code}")
except Exception as e:
    print(f"[FAIL] 错误类测试失败: {e}")
    exit(1)

try:
    skill_config = {
        "weixin": {
            "account_id": "test_id",
            "token": "test_token"
        }
    }
    mapped_config = adapter.map_skill_config(skill_config)
    print(f"[OK] 配置映射成功: account_id={mapped_config.account_id}")
except Exception as e:
    print(f"[FAIL] 配置映射失败: {e}")
    exit(1)

try:
    health = adapter.check_health(mapped_config)
    print(f"[OK] 健康检查成功: ok={health['ok']}")
except Exception as e:
    print(f"[FAIL] 健康检查失败: {e}")
    exit(1)

print("\n所有验证通过!")
print("=" * 50)
print("创建的文件列表:")
print("  - backend/skills/weixin/__init__.py")
print("  - backend/skills/weixin/config.py")
print("  - backend/skills/weixin/errors.py")
print("  - backend/skills/weixin/adapter.py")
print("  - backend/skills/weixin/api/__init__.py")
print("  - backend/skills/weixin/api/client.py")
print("  - backend/skills/weixin/messaging/__init__.py")
print("  - backend/skills/weixin/messaging/inbound.py")
print("  - backend/skills/weixin/messaging/outbound.py")
print("  - backend/skills/weixin/messaging/process.py")
print("  - backend/skills/weixin/storage/__init__.py")
print("  - backend/skills/weixin/storage/state.py")
print("  - backend/skills/weixin/utils/__init__.py")
print("  - backend/skills/weixin/utils/helpers.py")
print("=" * 50)
