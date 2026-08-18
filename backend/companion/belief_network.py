"""
信念网络模块：陪伴者人格演化的确定性计算基底。

对应 NSP-roleplay 心智模型的「信念网络」层。每个角色的心理维度被建模为
[0, 1] 区间的连续状态变量，通过以下机制随时间、事件和记忆演化：

- 精度 (precision)：信念抵抗变化的程度，由极端度、累积负荷、当前情绪共同决定
- 应变 (strain)：可恢复的心理压力，随时间指数衰减
- 负荷 (load)：不可逆的心理损伤（疤痕组织），永不衰减
- 灾变 (catastrophe)：负荷越过阈值时，信念断裂式跳变到中线对侧（尖点灾变理论）
- 维度共振 (v9)：关联维度的应力溢出会侵蚀本维度的精度
- 渐进式突变 (v9)：跳跃距离与累积负荷成正比，而非固定二值
- 正面事件恢复 (v9)：合意事件轻微减少负荷，提供喘息空间

本模块为纯确定性代码，不依赖 LLM 与数据库，可独立单元测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from loguru import logger


# 学习率：每轮信念微更新的幅度，几乎不可感知
LEARNING_RATE: float = 0.05

# 应变衰减系数：应变每轮按此比例指数衰减
STRAIN_DECAY: float = 0.95

# 应变阈值：超过部分才会转化为不可逆负荷
STRAIN_THRESHOLD: float = 0.3

# 负荷转移系数：超阈值应变转化为负荷的比例
LOAD_TRANSFER_RATE: float = 0.1

# 灾变阈值：负荷超过此值触发信念断裂式跳变
CATASTROPHE_THRESHOLD: float = 0.5

# 情绪对精度的临时削弱系数
EMOTION_PRECISION_DAMP: float = 0.3

# v9 维度共振强度：关联维度溢出应力对精度的削弱比例
RESONANCE_STRENGTH: float = 0.3

# v9 渐进式突变：跳跃距离的最小基线与负荷缩放系数
CATASTROPHE_BASE_DISTANCE: float = 0.05
CATASTROPHE_LOAD_SCALE: float = 0.30

# v9 正面事件恢复：合意事件（desirability > 0）每单位减少的负荷量
POSITIVE_RECOVERY_RATE: float = 0.02

# v9 应力持续加速：连续高应力轮次的负荷转移加速因子
STRESS_ACCELERATION: float = 1.0


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """将数值钳制到 [low, high] 区间。"""
    return max(low, min(high, value))


@dataclass
class BeliefNode:
    """单个信念维度的完整心理状态。"""

    value: float = 0.5
    strain: float = 0.0
    load: float = 0.0
    # 历史轨迹：记录每次更新后的值，供观察者检测涌现弧线
    history: List[float] = field(default_factory=list)
    # 连续高应力轮次计数（v9 应力持续加速）
    high_stress_streak: int = 0


class BeliefNetwork:
    """信念网络：一组相互关联的心理维度，随事件确定性演化。"""

    def __init__(
        self,
        beliefs: Dict[str, float],
        links: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        """
        Args:
            beliefs: 信念维度名 -> 初始值（[0, 1]）
            links: v9 维度共振矩阵，维度名 -> 关联维度名列表
        """
        self.nodes: Dict[str, BeliefNode] = {
            name: BeliefNode(value=clamp(value))
            for name, value in beliefs.items()
        }
        self.links: Dict[str, List[str]] = links or {}

    # ---- 查询 ----

    def extremity(self, name: str) -> float:
        """信念距离中性点的极端度，范围 [0, 1]。"""
        return abs(self.nodes[name].value - 0.5) * 2.0

    def resonance_factor(self, name: str) -> float:
        """
        v9 维度共振：关联维度的高应力溢出会侵蚀本维度的精度。
        关联维度应变越高，本维度精度越低。
        """
        overflow_total = 0.0
        for linked in self.links.get(name, []):
            overflow = max(0.0, self.nodes[linked].strain - STRAIN_THRESHOLD)
            overflow_total += overflow
        return clamp(1.0 - RESONANCE_STRENGTH * overflow_total)

    def precision(self, name: str, emotion_intensity: float = 0.0) -> float:
        """
        计算信念当前抵抗变化的精度。

        precision = extremity * (1 - load) * (1 - emotion * damp) * resonance

        关键特性：
        - 极端信念刚性、温和信念流动
        - 累积负荷侵蚀精度
        - 强烈情绪暂时降低精度
        - 关联维度应力溢出传导降低精度（v9）
        """
        node = self.nodes[name]
        extremity = self.extremity(name)
        precision = (
            extremity
            * (1.0 - node.load)
            * (1.0 - emotion_intensity * EMOTION_PRECISION_DAMP)
            * self.resonance_factor(name)
        )
        return clamp(precision)

    # ---- 演化 ----

    def update(
        self,
        weighted_errors: Dict[str, float],
        emotion_intensity: float = 0.0,
        desirability: float = 0.0,
    ) -> List[str]:
        """
        对受影响的信念执行一轮确定性更新，返回触发灾变的信念名列表。

        Args:
            weighted_errors: 信念维度名 -> 本轮加权预测误差（正负均可）
            emotion_intensity: 当前情绪强度 [0, 1]
            desirability: 本轮事件合意性 [-1, 1]，正值触发正面恢复

        Returns:
            触发灾变的信念名列表（用于记录里程碑）
        """
        milestones: List[str] = []
        for name, weighted_error in weighted_errors.items():
            if name not in self.nodes:
                continue
            node = self.nodes[name]

            # 1. 信念值微更新（学习率缩放）
            node.value = clamp(node.value + weighted_error * LEARNING_RATE)
            node.history.append(node.value)

            # 2. 应变更新（指数衰减 + 新误差的可恢复压力）
            node.strain = abs(weighted_error) + node.strain * STRAIN_DECAY

            # 3. 连续高应力状态标记（v9 应力持续加速）
            if node.strain > STRAIN_THRESHOLD:
                node.high_stress_streak += 1
            else:
                node.high_stress_streak = 0

            # 4. 负荷转移（超过阈值的应变转化为不可逆负荷）
            if node.strain > STRAIN_THRESHOLD:
                # 连续高压按 streak 加速转移（第 N 轮加速 N 倍）
                acceleration = (1.0 + STRESS_ACCELERATION * (node.high_stress_streak - 1))
                node.load = clamp(
                    node.load + (node.strain - STRAIN_THRESHOLD) * LOAD_TRANSFER_RATE * acceleration
                )

            # 5. 正面事件恢复（v9：合意事件轻微减少负荷，非治愈而是喘息）
            if desirability > 0:
                node.load = clamp(node.load - POSITIVE_RECOVERY_RATE * desirability)

            # 6. 灾变检查（负荷越过阈值 -> 断裂式跳变）
            if node.load > CATASTROPHE_THRESHOLD:
                node.value = self._catastrophe_target(node)
                node.history.append(node.value)
                node.load = 0.0
                node.strain = 0.0
                node.high_stress_streak = 0
                milestones.append(name)
                logger.bind(
                    event="belief_catastrophe",
                    module="companion",
                    belief=name,
                    new_value=node.value,
                ).info(f"信念 {name} 触发灾变，跳变至 {node.value:.3f}")

        return milestones

    def _catastrophe_target(self, node: BeliefNode) -> float:
        """
        计算灾变后信念的目标值。

        v9 渐进式突变：跳跃距离与累积负荷成正比，
        使「轻微裂痕」与「毁灭性崩塌」跳向不同位置。
        """
        distance = CATASTROPHE_BASE_DISTANCE + CATASTROPHE_LOAD_SCALE * node.load
        if node.value > 0.5:
            return clamp(0.5 - distance)
        return clamp(0.5 + distance)

    # ---- 序列化 ----

    def to_dict(self) -> Dict[str, Dict[str, float]]:
        """导出为可 JSON 序列化的字典（含每信念的 value/strain/load）。"""
        return {
            name: {
                "value": node.value,
                "strain": node.strain,
                "load": node.load,
            }
            for name, node in self.nodes.items()
        }

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Dict[str, float]],
        links: Optional[Dict[str, List[str]]] = None,
    ) -> "BeliefNetwork":
        """从字典恢复信念网络。"""
        network = cls({}, links=links)
        network.nodes = {
            name: BeliefNode(
                value=node.get("value", 0.5),
                strain=node.get("strain", 0.0),
                load=node.get("load", 0.0),
            )
            for name, node in data.items()
        }
        return network