"""
P1-05: Add Pydantic Field validation constraints to WeixinConfigReq
"""
path = r"d:\代码\Open-AwA\backend\api\routes\skills.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Step 1: Update import - add Field
content = content.replace(
    "from pydantic import BaseModel",
    "from pydantic import BaseModel, Field"
)

# Step 2: Replace WeixinConfigReq class
old_class = '''class WeixinConfigReq(BaseModel):
    """
    微信配置请求模型，包含连接参数和绑定信息。
    """
    account_id: str
    token: str
    base_url: Optional[str] = DEFAULT_BASE_URL
    timeout_seconds: Optional[int] = 15
    user_id: Optional[str] = ""
    binding_status: Optional[str] = "unbound"
    bot_type: Optional[str] = None
    channel_version: Optional[str] = None'''

new_class = '''class WeixinConfigReq(BaseModel):
    """
    微信配置请求模型，包含连接参数和绑定信息。
    """
    account_id: str = Field(..., min_length=1, max_length=128, description="微信账号ID")
    token: str = Field(..., min_length=1, max_length=512, description="认证Token")
    base_url: Optional[str] = Field(default=DEFAULT_BASE_URL, max_length=512, description="基础URL")
    timeout_seconds: Optional[int] = Field(default=15, ge=1, le=300, description="超时秒数")
    user_id: Optional[str] = Field(default="", max_length=128, description="用户ID")
    binding_status: Optional[str] = Field(default="unbound", pattern=r"^(unbound|binding|bound|failed)$", description="绑定状态")
    bot_type: Optional[str] = Field(default=None, max_length=64, description="机器人类型")
    channel_version: Optional[str] = Field(default=None, max_length=32, description="渠道版本")'''

if old_class not in content:
    print("ERROR: old_class not found!")
    idx = content.find("class WeixinConfigReq")
    if idx >= 0:
        print(repr(content[idx:idx+400]))
else:
    content = content.replace(old_class, new_class)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("P1-05: WeixinConfigReq updated successfully")
