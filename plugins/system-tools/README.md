# system-tools 系统内置工具插件

系统内置工具插件，将文件管理和终端执行能力集成为一个统一的插件。

## 提供的工具

### 文件管理

- `read_file` - 读取文件内容
- `write_file` - 写入文件内容
- `list_files` - 列出目录下的文件
- `delete_file` - 删除文件或目录
- `file_exists` - 检查文件或目录是否存在
- `create_directory` - 创建目录

### 终端执行

- `run_command` - 在受控沙箱中执行安全的终端命令
- `get_system_status` - 获取当前系统状态信息

## 权限说明

- `file:read` - 文件读取权限
- `file:write` - 文件写入权限
- `command:execute` - 命令执行权限（受安全白名单限制）

## 安全策略

- 终端命令执行有白名单限制，禁止高危命令
- 文件操作路径有安全校验，防止路径遍历攻击
- 命令执行有超时限制（默认30秒）
