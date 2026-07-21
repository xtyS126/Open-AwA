"""
沙箱路径安全模块单元测试 — 覆盖 Task 10 的五层检查、TOCTOU 防护、路径标准化等。

测试覆盖：
- is_path_allowed 五层检查（deny 规则、内部可编辑、工作目录、默认拒绝）
- validate_path TOCTOU 防护（UNC、tilde、$、%、.. 等）
- is_dangerous_removal_path 危险删除路径检测
- normalize_path 路径标准化
- 写操作禁止 glob 模式和路径穿越
"""

import os
import sys
from pathlib import Path

import pytest

# 确保可以导入 backend 模块
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from security.sandbox import (
    is_path_allowed,
    validate_path,
    normalize_path,
    is_dangerous_removal_path,
    _INTERNAL_EDITABLE_PATHS,
)


class TestIsPathAllowedDenyRule:
    """测试 is_path_allowed 的 deny 规则。"""

    def test_is_path_allowed_deny_rule(self):
        """验证 deny 规则匹配的路径被拒绝。"""
        # /etc/ 目录被拒绝
        assert is_path_allowed('/etc/passwd') is False
        # /root/ 目录被拒绝
        assert is_path_allowed('/root/.ssh/id_rsa') is False
        # /proc 目录被拒绝
        assert is_path_allowed('/proc/self/environ') is False
        # /sys 目录被拒绝
        assert is_path_allowed('/sys/kernel') is False
        # /var/log/ 目录被拒绝
        assert is_path_allowed('/var/log/syslog') is False
        # .env 文件被拒绝（任意位置）
        assert is_path_allowed('/tmp/.env') is False
        assert is_path_allowed('/home/user/.env') is False

    def test_is_path_allowed_deny_rule_windows(self):
        """验证 Windows 系统目录被拒绝。"""
        # Windows 系统目录被拒绝（大小写不敏感）
        assert is_path_allowed('C:\\Windows\\System32\\config\\SAM') is False
        assert is_path_allowed('C:\\Windows\\win.ini') is False
        assert is_path_allowed('D:\\Windows\\System32\\drivers\\etc\\hosts') is False


class TestIsPathAllowedInternalEditable:
    """测试 is_path_allowed 的内部可编辑路径检查。"""

    def test_is_path_allowed_internal_editable(self):
        """验证内部可编辑路径（项目目录）允许访问。"""
        # 使用项目目录内的路径
        editable_path = os.path.join(_INTERNAL_EDITABLE_PATHS[0], 'test_file.txt')
        assert is_path_allowed(editable_path) is True

    def test_is_path_allowed_internal_editable_project_dir(self):
        """验证项目根目录内的路径允许访问。"""
        if len(_INTERNAL_EDITABLE_PATHS) > 1:
            project_path = os.path.join(_INTERNAL_EDITABLE_PATHS[1], 'some_file.txt')
            assert is_path_allowed(project_path) is True


class TestIsPathAllowedWorkingDir:
    """测试 is_path_allowed 的工作目录检查。"""

    def test_is_path_allowed_working_dir(self, tmp_path):
        """验证工作目录内的路径允许访问。"""
        # 使用临时目录作为工作目录
        working_dir = str(tmp_path)
        # 在工作目录内构造一个路径
        test_path = str(tmp_path / 'test.txt')
        assert is_path_allowed(test_path, working_dir=working_dir) is True

    def test_is_path_allowed_outside_working_dir(self, tmp_path):
        """验证工作目录外的路径被拒绝（默认拒绝）。"""
        working_dir = str(tmp_path)
        # 使用一个不在工作目录内的路径（也不在其他白名单内）
        # 注意：这个路径不能匹配 deny 规则，不能含危险字符
        outside_path = str(tmp_path.parent / 'other_dir' / 'test.txt')
        assert is_path_allowed(outside_path, working_dir=working_dir) is False


class TestIsPathAllowedDefaultDeny:
    """测试 is_path_allowed 的默认拒绝。"""

    def test_is_path_allowed_default_deny(self):
        """验证不匹配任何规则的路径被默认拒绝。"""
        # 使用一个不在任何白名单内的路径
        # 这个路径不含危险字符，会通过 validate_path
        # 但不在工作目录、白名单、allow 规则内
        assert is_path_allowed('/random/nonexistent/path/file.txt') is False

    def test_is_path_allowed_empty_path(self):
        """验证空路径被拒绝。"""
        assert is_path_allowed('') is False
        assert is_path_allowed('   ') is False


class TestValidatePathUNC:
    """测试 validate_path 的 UNC 路径拒绝。"""

    def test_validate_path_unc(self):
        """验证 UNC 路径被拒绝。"""
        # Windows UNC 路径（\\server\share）
        assert validate_path('\\\\server\\share\\file.txt') is False
        # Unix UNC 风格路径（//server/share）
        assert validate_path('//server/share/file.txt') is False
        assert validate_path('//localhost/c$/file.txt') is False


class TestValidatePathTildeSpecial:
    """测试 validate_path 的 tilde 特殊扩展拒绝。"""

    def test_validate_path_tilde_special(self):
        """验证 tilde 特殊扩展被拒绝。"""
        # ~root（某些 Unix 系统支持）
        assert validate_path('~root/file.txt') is False
        # ~+ （bash 特殊变量，表示当前工作目录）
        assert validate_path('~+/file.txt') is False
        # ~- （bash 特殊变量，表示上一个工作目录）
        assert validate_path('~-/file.txt') is False


class TestValidatePathDollarSign:
    """测试 validate_path 的 $ 字符拒绝。"""

    def test_validate_path_dollar_sign(self):
        """验证含 $ 的路径被拒绝（环境变量注入）。"""
        assert validate_path('$HOME/file.txt') is False
        assert validate_path('/tmp/$USER_file') is False
        assert validate_path('/path/to/${HOME}') is False
        assert validate_path('/path/$(whoami)') is False


class TestValidatePathPercent:
    """测试 validate_path 的 % 字符拒绝。"""

    def test_validate_path_percent(self):
        """验证含 % 的路径被拒绝（Windows 环境变量注入）。"""
        assert validate_path('%PATH%/file.txt') is False
        assert validate_path('/tmp/%USERPROFILE%_file') is False
        assert validate_path('C:/%APPDATA%/secret') is False


class TestValidatePathDotDot:
    """测试 validate_path 的 .. 路径穿越拒绝。"""

    def test_validate_path_dot_dot(self):
        """验证含 .. 的路径被拒绝（路径穿越）。"""
        assert validate_path('../etc/passwd') is False
        assert validate_path('/tmp/../etc/passwd') is False
        assert validate_path('/var/log/../../root/.ssh/id_rsa') is False
        assert validate_path('/home/user/../../../etc/shadow') is False


class TestValidatePathNormal:
    """测试 validate_path 的正常路径通过。"""

    def test_validate_path_normal(self):
        """验证正常路径通过校验。"""
        assert validate_path('/tmp/test.txt') is True
        assert validate_path('/home/user/file.txt') is True
        assert validate_path('/var/log/app.log') is True
        # 相对路径（不含 ..）也应该通过
        assert validate_path('test.txt') is True
        assert validate_path('subdir/test.txt') is True

    def test_validate_path_empty(self):
        """验证空路径被拒绝。"""
        assert validate_path('') is False
        assert validate_path('   ') is False


class TestIsDangerousRemovalPathRoot:
    """测试 is_dangerous_removal_path 的根目录检测。"""

    def test_is_dangerous_removal_path_root(self):
        """验证根目录被视为危险删除路径。"""
        assert is_dangerous_removal_path('/') is True
        # Unix 根子目录
        assert is_dangerous_removal_path('/home') is True
        assert is_dangerous_removal_path('/usr') is True
        assert is_dangerous_removal_path('/etc') is True
        assert is_dangerous_removal_path('/var') is True
        assert is_dangerous_removal_path('/bin') is True

    def test_is_dangerous_removal_path_windows_root(self):
        """验证 Windows 驱动器根被视为危险删除路径。"""
        assert is_dangerous_removal_path('C:\\') is True
        assert is_dangerous_removal_path('D:\\') is True
        assert is_dangerous_removal_path('C:') is True
        assert is_dangerous_removal_path('E:/') is True


class TestIsDangerousRemovalPathHome:
    """测试 is_dangerous_removal_path 的主目录检测。"""

    def test_is_dangerous_removal_path_home(self):
        """验证用户主目录被视为危险删除路径。"""
        # ~ 表示用户主目录
        assert is_dangerous_removal_path('~') is True
        # /home 根子目录
        assert is_dangerous_removal_path('/home') is True


class TestIsDangerousRemovalPathWildcard:
    """测试 is_dangerous_removal_path 的通配符检测。"""

    def test_is_dangerous_removal_path_wildcard(self):
        """验证含通配符的路径被视为危险删除路径。"""
        assert is_dangerous_removal_path('/tmp/*') is True
        assert is_dangerous_removal_path('/home/user/*.txt') is True
        assert is_dangerous_removal_path('/var/log/??.log') is True
        assert is_dangerous_removal_path('*') is True


class TestIsDangerousRemovalPathNormal:
    """测试 is_dangerous_removal_path 的正常路径检测。"""

    def test_is_dangerous_removal_path_normal(self):
        """验证正常路径不被视为危险删除路径。"""
        assert is_dangerous_removal_path('/tmp/test.txt') is False
        assert is_dangerous_removal_path('/home/user/file.txt') is False
        assert is_dangerous_removal_path('/var/log/app.log') is False
        # 子目录（非根子目录）
        assert is_dangerous_removal_path('/home/user/subdir') is False

    def test_is_dangerous_removal_path_empty(self):
        """验证空路径被视为危险删除路径。"""
        assert is_dangerous_removal_path('') is True


class TestNormalizePathMixedSlashes:
    """测试 normalize_path 的混合斜杠标准化。"""

    def test_normalize_path_mixed_slashes(self):
        """验证混合斜杠统一为正斜杠。"""
        assert normalize_path('a/b\\c') == 'a/b/c'
        assert normalize_path('C:\\Windows\\System32') == 'C:/Windows/System32'
        assert normalize_path('/usr/local\\bin') == '/usr/local/bin'
        # 多个连续反斜杠
        assert normalize_path('a\\\\b') == 'a/b'


class TestNormalizePathDotDot:
    """测试 normalize_path 的 .. 解析。"""

    def test_normalize_path_dot_dot(self):
        """验证 .. 被正确解析。"""
        assert normalize_path('a/b/../c') == 'a/c'
        assert normalize_path('/a/b/../c') == '/a/c'
        assert normalize_path('/a/b/../../c') == '/c'
        # . 被跳过
        assert normalize_path('a/./b') == 'a/b'
        assert normalize_path('/a/./b/./c') == '/a/b/c'
        # 混合 . 和 ..
        assert normalize_path('a/./b/../c') == 'a/c'


class TestNormalizePathTrailingSlash:
    """测试 normalize_path 的尾部斜杠处理。"""

    def test_normalize_path_trailing_slash(self):
        """验证尾部斜杠被去除（根目录除外）。"""
        assert normalize_path('/a/b/') == '/a/b'
        assert normalize_path('/a/b///') == '/a/b'
        assert normalize_path('a/b/') == 'a/b'
        # 根目录保留
        assert normalize_path('/') == '/'
        # 多个斜杠的根目录
        assert normalize_path('///') == '/'


class TestWriteOperationBlocksGlob:
    """测试写操作禁止 glob 模式。"""

    def test_write_operation_blocks_glob(self):
        """验证写操作禁止 glob 字符。"""
        # * 通配符
        assert is_path_allowed('/tmp/test*.txt', is_write=True) is False
        # ? 通配符
        assert is_path_allowed('/tmp/test?.txt', is_write=True) is False
        # [ ] 字符类
        assert is_path_allowed('/tmp/test[0-9].txt', is_write=True) is False
        assert is_path_allowed('/tmp/test[abc].txt', is_write=True) is False

    def test_read_operation_allows_glob_in_allow_path(self):
        """验证读操作不禁止 glob 字符（但会被默认拒绝）。"""
        # 读操作不禁止 glob，但 /tmp/test*.txt 会被 allow 规则匹配
        # 注意：/tmp/test*.txt 匹配 ^/tmp/ allow 规则
        # 但是 validate_path 会通过（不含危险字符）
        # 然后第 4 层工作目录检查（无 working_dir）跳过
        # 第 5 层沙箱白名单检查：/tmp/test*.txt resolve 后在 /tmp 内
        # 所以读操作应该返回 True
        result = is_path_allowed('/tmp/test*.txt', is_write=False)
        # 读操作允许 glob（结果取决于白名单匹配）
        # 这里只验证不因为 glob 被拒绝
        # 实际上 /tmp/test*.txt 会在第 5 层沙箱白名单匹配，返回 True
        assert result is True


class TestWriteOperationBlocksDotDot:
    """测试写操作禁止 .. 路径穿越。"""

    def test_write_operation_blocks_dot_dot(self):
        """验证写操作禁止 .. 路径穿越。"""
        assert is_path_allowed('/tmp/../etc/passwd', is_write=True) is False
        assert is_path_allowed('/var/log/../../root/.ssh/id_rsa', is_write=True) is False
        assert is_path_allowed('../secret.txt', is_write=True) is False
        assert is_path_allowed('/home/user/../../../etc/shadow', is_write=True) is False

    def test_write_operation_allows_normal_path(self, tmp_path):
        """验证写操作允许正常路径。"""
        # 使用临时目录作为工作目录
        working_dir = str(tmp_path)
        test_path = str(tmp_path / 'write_test.txt')
        assert is_path_allowed(test_path, is_write=True, working_dir=working_dir) is True


class TestTOCTUProtection:
    """测试 TOCTOU 防护。"""

    def test_toctou_protection(self):
        """验证 TOCTOU 防护：含 .. 的路径被拒绝。"""
        # validate_path 拒绝含 .. 的路径
        assert validate_path('/tmp/../etc/passwd') is False
        assert validate_path('/var/log/../../root/.ssh/id_rsa') is False
        # is_path_allowed 也拒绝含 .. 的路径（第 3 层安全性检查）
        assert is_path_allowed('/tmp/../etc/passwd') is False
        assert is_path_allowed('/var/log/../../root/.ssh/id_rsa') is False

    def test_toctou_protection_unc(self):
        """验证 TOCTOU 防护：UNC 路径被拒绝。"""
        assert validate_path('\\\\malicious\\share\\file') is False
        assert is_path_allowed('\\\\malicious\\share\\file') is False

    def test_toctou_protection_env_injection(self):
        """验证 TOCTOU 防护：环境变量注入被拒绝。"""
        # $ 注入
        assert validate_path('$HOME/secret') is False
        assert is_path_allowed('$HOME/secret') is False
        # % 注入
        assert validate_path('%PATH%/secret') is False
        assert is_path_allowed('%PATH%/secret') is False

    def test_toctou_protection_tilde_special(self):
        """验证 TOCTOU 防护：tilde 特殊扩展被拒绝。"""
        assert validate_path('~root/secret') is False
        assert validate_path('~+/secret') is False
        assert validate_path('~-/secret') is False
        # is_path_allowed 也应该拒绝
        assert is_path_allowed('~root/secret') is False
        assert is_path_allowed('~+/secret') is False


class TestIsPathAllowedSandboxWhitelist:
    """测试 is_path_allowed 的沙箱白名单检查。"""

    def test_is_path_allowed_sandbox_whitelist_tmp(self):
        """验证 /tmp 目录在沙箱白名单内。"""
        # /tmp/test.txt 应该通过沙箱白名单检查
        assert is_path_allowed('/tmp/test.txt') is True

    def test_is_path_allowed_sandbox_whitelist_var_tmp(self):
        """验证 /var/tmp 目录在沙箱白名单内。"""
        assert is_path_allowed('/var/tmp/test.txt') is True


class TestIsPathAllowedAllowRule:
    """测试 is_path_allowed 的 allow 规则。"""

    def test_is_path_allowed_allow_rule_tmp(self):
        """验证 /tmp/ 路径匹配 allow 规则。"""
        # /tmp/ 路径匹配 allow 规则
        assert is_path_allowed('/tmp/somefile.txt') is True

    def test_is_path_allowed_allow_rule_var_tmp(self):
        """验证 /var/tmp/ 路径匹配 allow 规则。"""
        assert is_path_allowed('/var/tmp/somefile.txt') is True


class TestNormalizePathEdgeCases:
    """测试 normalize_path 的边界情况。"""

    def test_normalize_path_empty(self):
        """验证空路径处理。"""
        assert normalize_path('') == ''

    def test_normalize_path_single_dot(self):
        """验证单个 . 处理。"""
        assert normalize_path('.') == '.'
        assert normalize_path('./') == '.'

    def test_normalize_path_double_dot(self):
        """验证单个 .. 处理。"""
        assert normalize_path('..') == '..'
        assert normalize_path('../') == '..'

    def test_normalize_path_complex(self):
        """验证复杂路径标准化。"""
        assert normalize_path('/a/b/c/../../d') == '/a/d'
        assert normalize_path('a/b/c/../../../d') == 'd'
        assert normalize_path('/a/./b/./c') == '/a/b/c'


class TestIsDangerousRemovalPathEdgeCases:
    """测试 is_dangerous_removal_path 的边界情况。"""

    def test_is_dangerous_removal_path_none(self):
        """验证 None 路径被视为危险。"""
        assert is_dangerous_removal_path(None) is True

    def test_is_dangerous_removal_path_subdir_safe(self):
        """验证子目录不被视为危险。"""
        # /home/user 是 /home 的子目录，不应被视为危险
        assert is_dangerous_removal_path('/home/user') is False
        # /usr/local 是 /usr 的子目录，不应被视为危险
        assert is_dangerous_removal_path('/usr/local') is False

    def test_is_dangerous_removal_path_windows_subdir_safe(self):
        """验证 Windows 子目录不被视为危险。"""
        assert is_dangerous_removal_path('C:\\Users\\test\\file.txt') is False
        assert is_dangerous_removal_path('D:\\data\\file.txt') is False
