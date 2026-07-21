"""
AbortController：树状中止控制器，支持父子级联中止。

设计参考浏览器 AbortController + Node.js AbortSignal：
- 每个 controller 可拥有任意数量的子 controller
- 父 controller abort 时递归中止所有子 controller
- 子 controller abort 时不影响父 controller 与兄弟 controller
- 父 controller 已 aborted 时，新创建的子 controller 立即 aborted

应用场景：
- Agent.process_stream 创建根 controller，工具执行创建子 controller
- 同一轮工具调用共享一个 sibling controller，工具出错时级联中止兄弟工具
- 流结束时调用根 controller.abort() 清理所有子任务

本类为同步类，不涉及 asyncio。
"""

from typing import List, Optional


class AbortController:
    """
    树状中止控制器。

    通过 parent/children 引用构成树状结构，abort 操作自顶向下递归传播。
    """

    def __init__(self, parent: Optional['AbortController'] = None):
        """
        初始化中止控制器。

        Args:
            parent: 父控制器，传入时自动将本控制器注册为父的子节点。
                    若父控制器已 aborted，本控制器立即标记为 aborted。
        """
        self._aborted: bool = False
        self._reason: Optional[str] = None
        self._children: List['AbortController'] = []
        self._parent: Optional['AbortController'] = parent
        if parent is not None:
            parent._children.append(self)
            # 父已 aborted 时子立即 aborted，继承父的 reason
            if parent._aborted:
                self._aborted = True
                self._reason = parent._reason

    def abort(self, reason: Optional[str] = None) -> None:
        """
        中止本控制器及其所有子控制器。

        已 aborted 的控制器再次调用 abort 为幂等操作，仅更新 reason（若新 reason 非空）。
        中止操作递归传播到所有子节点，深度无限制。

        Args:
            reason: 中止原因，可选。传播到子节点时使用同一 reason。
        """
        # 幂等保护：已 aborted 时仅更新 reason
        if self._aborted:
            if reason is not None and self._reason is None:
                self._reason = reason
            return
        self._aborted = True
        self._reason = reason
        # 递归中止所有子节点，传播同一 reason
        for child in self._children:
            child.abort(reason)

    def is_aborted(self) -> bool:
        """
        返回本控制器是否已被中止。

        Returns:
            是否已中止
        """
        return self._aborted

    def signal(self) -> bool:
        """
        is_aborted 的别名，提供与浏览器 AbortSignal 类似的语义。

        Returns:
            是否已中止
        """
        return self.is_aborted()

    def create_child(self) -> 'AbortController':
        """
        创建子控制器，父 abort 时传播到子。

        若本控制器已 aborted，新创建的子控制器立即 aborted。

        Returns:
            新的子 AbortController 实例
        """
        return AbortController(parent=self)

    @property
    def reason(self) -> Optional[str]:
        """
        返回中止原因，未中止时为 None。

        Returns:
            中止原因或 None
        """
        return self._reason

    @property
    def parent(self) -> Optional['AbortController']:
        """
        返回父控制器，根控制器为 None。

        Returns:
            父控制器或 None
        """
        return self._parent

    @property
    def children(self) -> List['AbortController']:
        """
        返回子控制器列表的副本，避免外部修改内部状态。

        Returns:
            子控制器列表副本
        """
        return list(self._children)
