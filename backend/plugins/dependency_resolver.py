"""
插件依赖解析器，负责解析插件间依赖关系、检测冲突和确定加载顺序。
使用拓扑排序确保依赖被先于依赖方加载。
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger


@dataclass
class DependencyNode:
    """
    依赖图中的节点，代表一个插件。
    """
    name: str
    version: str = ""
    dependencies: List[str] = field(default_factory=list)


@dataclass
class DependencyConflict:
    """
    依赖冲突描述。
    """
    plugin_name: str
    missing_dependency: Optional[str] = None
    circular_path: Optional[List[str]] = None
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        result: Dict[str, Any] = {
            "plugin_name": self.plugin_name,
            "message": self.message,
        }
        if self.missing_dependency:
            result["missing_dependency"] = self.missing_dependency
        if self.circular_path:
            result["circular_path"] = self.circular_path
        return result


@dataclass
class ResolutionResult:
    """
    依赖解析结果。
    """
    # 按依赖顺序排列的插件名称列表（先加载依赖，后加载依赖方）
    load_order: List[str] = field(default_factory=list)
    # 解析过程中发现的冲突
    conflicts: List[DependencyConflict] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """无冲突时返回 True。"""
        return len(self.conflicts) == 0

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        return {
            "success": self.success,
            "load_order": self.load_order,
            "conflicts": [c.to_dict() for c in self.conflicts],
        }


class DependencyResolver:
    """
    插件依赖解析器。
    基于有向无环图（DAG）拓扑排序确定加载顺序，
    并检测缺失依赖和循环依赖。
    """

    def resolve(self, plugins: Dict[str, DependencyNode]) -> ResolutionResult:
        """
        解析所有插件的依赖关系并返回有序加载列表。

        Args:
            plugins: 插件名称到依赖节点的映射。

        Returns:
            ResolutionResult 包含加载顺序和冲突列表。
        """
        result = ResolutionResult()

        # 第一步：检测缺失依赖
        for name, node in plugins.items():
            for dep in node.dependencies:
                if dep not in plugins:
                    result.conflicts.append(DependencyConflict(
                        plugin_name=name,
                        missing_dependency=dep,
                        message=f"插件 '{name}' 依赖 '{dep}'，但 '{dep}' 未注册",
                    ))

        # 如果有缺失依赖，提前返回（不进行排序）
        if result.conflicts:
            return result

        # 第二步：构建有向图并执行拓扑排序
        in_degree: Dict[str, int] = {name: 0 for name in plugins}
        adjacency: Dict[str, List[str]] = defaultdict(list)

        for name, node in plugins.items():
            for dep in node.dependencies:
                adjacency[dep].append(name)
                in_degree[name] += 1

        # BFS 拓扑排序（Kahn 算法）
        queue: deque[str] = deque()
        for name, degree in in_degree.items():
            if degree == 0:
                queue.append(name)

        sorted_plugins: List[str] = []
        while queue:
            current = queue.popleft()
            sorted_plugins.append(current)
            for neighbor in adjacency[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # 第三步：检测循环依赖
        if len(sorted_plugins) < len(plugins):
            # 存在循环依赖，找出环中的节点
            cycle_nodes = set(plugins.keys()) - set(sorted_plugins)
            cycle_path = self._find_cycle(plugins, cycle_nodes)
            result.conflicts.append(DependencyConflict(
                plugin_name=", ".join(sorted(cycle_nodes)),
                circular_path=cycle_path,
                message=f"检测到循环依赖: {' -> '.join(cycle_path)}" if cycle_path else "检测到循环依赖",
            ))
        else:
            result.load_order = sorted_plugins

        return result

    def _find_cycle(
        self,
        plugins: Dict[str, DependencyNode],
        cycle_candidates: Set[str],
    ) -> List[str]:
        """
        在候选节点中查找一条环路径。

        Returns:
            环路径列表（如 ["A", "B", "C", "A"]），未找到时返回空列表。
        """
        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        path: List[str] = []

        def _dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            node_obj = plugins.get(node)
            if node_obj:
                for dep in node_obj.dependencies:
                    if dep in cycle_candidates:
                        if dep not in visited:
                            if _dfs(dep):
                                return True
                        elif dep in rec_stack:
                            # 找到环
                            cycle_start_idx = path.index(dep)
                            path.append(dep)
                            del path[:cycle_start_idx]
                            return True

            path.pop()
            rec_stack.discard(node)
            return False

        for candidate in cycle_candidates:
            if candidate not in visited:
                path.clear()
                if _dfs(candidate):
                    return path

        return list(cycle_candidates)
