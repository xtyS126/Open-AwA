"""
AbortController 单元测试：验证树状传播与级联中止。

覆盖：
- AbortController 初始状态与基本方法（is_aborted/signal/abort）
- abort 传播到子 controller 与孙 controller
- create_child 父子关系建立
- 父已 aborted 时新创建子 controller 立即 aborted
- sibling 级联中止（共享父 controller 的兄弟节点）
- 独立 sibling 互不影响
- 带 reason 的 abort 传播
- signal 作为 is_aborted 别名
"""

import pytest

from core.abort_controller import AbortController


class TestAbortControllerInitialState:
    """AbortController 初始状态测试"""

    def test_abort_controller_initial_state(self):
        """验证初始状态：未中止、无子节点、无父节点、reason 为 None"""
        controller = AbortController()
        assert controller.is_aborted() is False
        assert controller.signal() is False
        assert controller.reason is None
        assert controller.parent is None
        assert controller.children == []

    def test_abort_controller_with_parent_registers_as_child(self):
        """验证传入 parent 时自动注册为父的子节点"""
        parent = AbortController()
        child = AbortController(parent=parent)
        assert child.parent is parent
        assert child in parent.children
        assert len(parent.children) == 1


class TestAbortControllerAbort:
    """AbortController abort 方法测试"""

    def test_abort_sets_aborted(self):
        """验证 abort 设置 aborted 标志"""
        controller = AbortController()
        assert controller.is_aborted() is False
        controller.abort()
        assert controller.is_aborted() is True

    def test_abort_is_idempotent(self):
        """验证 abort 幂等：多次调用不报错"""
        controller = AbortController()
        controller.abort()
        controller.abort()
        controller.abort()
        assert controller.is_aborted() is True

    def test_abort_with_reason(self):
        """验证带 reason 的 abort 设置 reason 字段"""
        controller = AbortController()
        controller.abort(reason="user_cancelled")
        assert controller.is_aborted() is True
        assert controller.reason == "user_cancelled"

    def test_abort_without_reason_sets_none(self):
        """验证不带 reason 的 abort 设置 reason 为 None"""
        controller = AbortController()
        controller.abort()
        assert controller.reason is None

    def test_abort_reason_propagates_to_children(self):
        """验证 abort reason 传播到子 controller"""
        parent = AbortController()
        child = parent.create_child()
        parent.abort(reason="parent_cancelled")
        assert child.is_aborted() is True
        assert child.reason == "parent_cancelled"


class TestAbortControllerPropagation:
    """AbortController 树状传播测试"""

    def test_abort_propagates_to_children(self):
        """验证 abort 传播到所有子 controller"""
        parent = AbortController()
        child1 = parent.create_child()
        child2 = parent.create_child()
        child3 = parent.create_child()

        parent.abort()

        assert parent.is_aborted() is True
        assert child1.is_aborted() is True
        assert child2.is_aborted() is True
        assert child3.is_aborted() is True

    def test_abort_propagates_to_grandchildren(self):
        """验证 abort 传播到孙 controller（递归传播）"""
        root = AbortController()
        child = root.create_child()
        grandchild1 = child.create_child()
        grandchild2 = child.create_child()
        great_grandchild = grandchild1.create_child()

        root.abort()

        assert root.is_aborted() is True
        assert child.is_aborted() is True
        assert grandchild1.is_aborted() is True
        assert grandchild2.is_aborted() is True
        assert great_grandchild.is_aborted() is True

    def test_abort_does_not_propagate_to_parent(self):
        """验证子 controller abort 不影响父 controller"""
        parent = AbortController()
        child = parent.create_child()

        child.abort()

        assert child.is_aborted() is True
        assert parent.is_aborted() is False

    def test_abort_does_not_propagate_to_siblings(self):
        """验证一个子 controller abort 不影响兄弟 controller"""
        parent = AbortController()
        child1 = parent.create_child()
        child2 = parent.create_child()
        child3 = parent.create_child()

        child1.abort()

        assert child1.is_aborted() is True
        assert child2.is_aborted() is False
        assert child3.is_aborted() is False
        assert parent.is_aborted() is False


class TestAbortControllerCreateChild:
    """AbortController create_child 方法测试"""

    def test_create_child_returns_new_controller(self):
        """验证 create_child 返回新的 AbortController 实例"""
        parent = AbortController()
        child = parent.create_child()

        assert isinstance(child, AbortController)
        assert child is not parent
        assert child.parent is parent
        assert child in parent.children

    def test_create_child_does_not_abort_new_child(self):
        """验证父未 aborted 时 create_child 返回未中止的子 controller"""
        parent = AbortController()
        child = parent.create_child()
        assert child.is_aborted() is False

    def test_child_created_after_parent_aborted_is_aborted(self):
        """验证父已 aborted 时新创建的子 controller 立即 aborted"""
        parent = AbortController()
        parent.abort(reason="already_cancelled")

        child = parent.create_child()

        assert child.is_aborted() is True
        assert child.reason == "already_cancelled"

    def test_create_multiple_children_all_registered(self):
        """验证多次 create_child 注册多个子节点"""
        parent = AbortController()
        children = [parent.create_child() for _ in range(5)]

        assert len(parent.children) == 5
        for child in children:
            assert child.parent is parent


class TestAbortControllerSignalAlias:
    """AbortController signal 方法测试"""

    def test_signal_alias(self):
        """验证 signal 是 is_aborted 的别名"""
        controller = AbortController()
        assert controller.signal() == controller.is_aborted()

        controller.abort()
        assert controller.signal() == controller.is_aborted()
        assert controller.signal() is True

    def test_signal_reflects_state_changes(self):
        """验证 signal 反映状态变化"""
        controller = AbortController()
        assert controller.signal() is False

        controller.abort()
        assert controller.signal() is True


class TestSiblingAbortCascades:
    """sibling 级联中止测试"""

    def test_sibling_abort_cascades(self):
        """验证 sibling 级联中止：共享父 controller 的兄弟节点级联中止"""
        # 模拟 StreamingToolExecutor 的 sibling controller 模式
        sibling_controller = AbortController()

        # 每个工具创建 sibling controller 的子 controller
        tool1_abort = sibling_controller.create_child()
        tool2_abort = sibling_controller.create_child()
        tool3_abort = sibling_controller.create_child()

        # 初始状态：所有工具未中止
        assert tool1_abort.is_aborted() is False
        assert tool2_abort.is_aborted() is False
        assert tool3_abort.is_aborted() is False

        # 模拟工具 1 出错，调用 sibling controller 的 abort
        sibling_controller.abort(reason="sibling_tool_error:tool1")

        # 所有 sibling 工具都被级联中止
        assert tool1_abort.is_aborted() is True
        assert tool2_abort.is_aborted() is True
        assert tool3_abort.is_aborted() is True
        assert sibling_controller.is_aborted() is True

        # reason 传播到所有子节点
        assert tool1_abort.reason == "sibling_tool_error:tool1"
        assert tool2_abort.reason == "sibling_tool_error:tool1"
        assert tool3_abort.reason == "sibling_tool_error:tool1"

    def test_sibling_abort_cascades_to_grandchildren(self):
        """验证 sibling 级联中止传播到孙节点"""
        sibling_controller = AbortController()
        tool_abort = sibling_controller.create_child()
        sub_task_abort = tool_abort.create_child()

        sibling_controller.abort(reason="cascade_test")

        assert tool_abort.is_aborted() is True
        assert sub_task_abort.is_aborted() is True
        assert sub_task_abort.reason == "cascade_test"

    def test_sibling_abort_after_some_completed(self):
        """验证部分 sibling 已完成后再 abort 仍级联中止其他 sibling"""
        sibling_controller = AbortController()
        tool1_abort = sibling_controller.create_child()
        tool2_abort = sibling_controller.create_child()

        # 模拟 tool1 已完成（abort_controller 仍存在但工具已结束）
        # tool2 仍在执行
        assert tool1_abort.is_aborted() is False
        assert tool2_abort.is_aborted() is False

        # tool2 出错，级联中止
        sibling_controller.abort(reason="tool2_error")

        # 即使 tool1 已完成，其 abort_controller 仍被中止（幂等）
        assert tool1_abort.is_aborted() is True
        assert tool2_abort.is_aborted() is True


class TestIndependentSiblings:
    """独立 sibling 测试：不同父 controller 的兄弟节点互不影响"""

    def test_independent_siblings(self):
        """验证独立 sibling：一个 abort 不影响另一个（不同父 controller）"""
        # 两个独立的根 controller，模拟不同的工具执行轮次
        root1 = AbortController()
        root2 = AbortController()

        # 第一轮工具
        tool1_round1 = root1.create_child()
        tool2_round1 = root1.create_child()

        # 第二轮工具（独立的根 controller）
        tool1_round2 = root2.create_child()

        # 第一轮 tool1 出错，级联中止第一轮所有工具
        root1.abort(reason="round1_error")

        # 第一轮工具都被中止
        assert tool1_round1.is_aborted() is True
        assert tool2_round1.is_aborted() is True
        assert root1.is_aborted() is True

        # 第二轮工具不受影响
        assert tool1_round2.is_aborted() is False
        assert root2.is_aborted() is False

    def test_independent_sibling_trees(self):
        """验证独立的 sibling 树互不影响"""
        # 构建两棵独立的树
        tree1_root = AbortController()
        tree1_child = tree1_root.create_child()
        tree1_grandchild = tree1_child.create_child()

        tree2_root = AbortController()
        tree2_child = tree2_root.create_child()
        tree2_grandchild = tree2_child.create_child()

        # 中止树 1
        tree1_root.abort(reason="tree1_cancelled")

        # 树 1 全部中止
        assert tree1_root.is_aborted() is True
        assert tree1_child.is_aborted() is True
        assert tree1_grandchild.is_aborted() is True

        # 树 2 不受影响
        assert tree2_root.is_aborted() is False
        assert tree2_child.is_aborted() is False
        assert tree2_grandchild.is_aborted() is False


class TestAbortControllerEdgeCases:
    """AbortController 边界情况测试"""

    def test_abort_with_empty_reason(self):
        """验证 abort 传入空字符串 reason"""
        controller = AbortController()
        controller.abort(reason="")
        assert controller.is_aborted() is True
        assert controller.reason == ""

    def test_abort_with_none_reason_overwrites_after_set(self):
        """验证已设置 reason 后再 abort 不覆盖原 reason"""
        controller = AbortController()
        controller.abort(reason="first_reason")
        assert controller.reason == "first_reason"

        # 再次 abort 不带 reason，不应覆盖
        controller.abort()
        assert controller.reason == "first_reason"

    def test_deep_nesting_propagation(self):
        """验证深层嵌套的 abort 传播（10 层）"""
        root = AbortController()
        current = root
        children = [root]
        for _ in range(10):
            current = current.create_child()
            children.append(current)

        root.abort(reason="deep_test")

        for child in children:
            assert child.is_aborted() is True
            assert child.reason == "deep_test"

    def test_children_property_returns_copy(self):
        """验证 children 属性返回列表副本，修改不影响内部状态"""
        parent = AbortController()
        child = parent.create_child()

        children_copy = parent.children
        children_copy.clear()

        # 内部状态不受影响
        assert len(parent.children) == 1
        assert child in parent.children

    def test_root_controller_has_no_parent(self):
        """验证根 controller 的 parent 为 None"""
        root = AbortController()
        assert root.parent is None

        child = root.create_child()
        assert child.parent is root
        assert child.parent is not None
