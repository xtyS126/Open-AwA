"""OptimizationLoop — 受 SGD/RL 启发的画像迭代优化。

运行带有探索/利用、早停和基于验证集提交/回滚的
mini-batch 评估循环。
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openbiliclaw.eval.evaluator import EvalReport, ProfileEvaluator
    from openbiliclaw.eval.event_simulator import EventSimulator
    from openbiliclaw.eval.optimizer import PromptOptimizer
    from openbiliclaw.eval.persona_generator import PersonaGenerator
    from openbiliclaw.soul.profile import OnionProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 配置与结果
# ---------------------------------------------------------------------------


@dataclass
class OptimizationConfig:
    """优化循环的配置。"""

    batch_size: int = 5
    max_epochs: int = 20
    exploration_rate: float = 0.2
    early_stop_patience: int = 3
    validation_split: int = 2
    score_target: float = 0.85
    param_change_limit: int = 2
    event_count_per_persona: int = 80


@dataclass
class EpochResult:
    """单个优化 epoch 的结果。"""

    epoch: int
    train_mean: float
    val_mean: float
    params_changed: list[str] = field(default_factory=list)
    exploration: bool = False
    accepted: bool = False
    train_reports: list[dict[str, object]] = field(default_factory=list)
    val_reports: list[dict[str, object]] = field(default_factory=list)


@dataclass
class OptimizationResult:
    """优化循环的最终结果。"""

    epochs_run: int = 0
    best_score: float = 0.0
    best_epoch: int = 0
    stop_reason: str = ""
    history: list[EpochResult] = field(default_factory=list)
    final_attributions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "epochs_run": self.epochs_run,
            "best_score": self.best_score,
            "best_epoch": self.best_epoch,
            "stop_reason": self.stop_reason,
            "history": [
                {
                    "epoch": h.epoch,
                    "train_mean": h.train_mean,
                    "val_mean": h.val_mean,
                    "params_changed": h.params_changed,
                    "exploration": h.exploration,
                    "accepted": h.accepted,
                }
                for h in self.history
            ],
            "final_attributions": self.final_attributions,
        }


# ---------------------------------------------------------------------------
# OptimizationLoop
# ---------------------------------------------------------------------------


class OptimizationLoop:
    """受 SGD/RL 启发的画像生成优化循环。

    每个 epoch：
    1. 采样一个多样化的 mini-batch 人格（ground truth）
    2. 为每个人格生成模拟事件
    3. 将事件通过真实 pipeline → 预测画像
    4. 评估预测画像 vs ground truth → EvalReport
    5. 利用（修复最差字段）或探索（随机扰动）
    6. 在留出人格上验证
    7. 接受或回滚改动
    """

    def __init__(
        self,
        *,
        config: OptimizationConfig,
        evaluator: ProfileEvaluator,
        persona_generator: PersonaGenerator,
        event_simulator: EventSimulator,
        optimizer: PromptOptimizer,
        pipeline_factory: Any,  # 创建全新 pipeline 用于评估的 Callable
        data_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._evaluator = evaluator
        self._persona_generator = persona_generator
        self._event_simulator = event_simulator
        self._optimizer = optimizer
        self._pipeline_factory = pipeline_factory
        self._data_dir = data_dir or Path("data")

    async def run(self) -> OptimizationResult:
        """运行完整优化循环。"""
        cfg = self._config
        best_score = 0.0
        best_epoch = 0
        patience_counter = 0
        history: list[EpochResult] = []

        logger.info(
            "Starting optimization: %d epochs, batch=%d, explore=%.0f%%",
            cfg.max_epochs,
            cfg.batch_size,
            cfg.exploration_rate * 100,
        )

        for epoch in range(cfg.max_epochs):
            logger.info("=== Epoch %d/%d ===", epoch + 1, cfg.max_epochs)

            # 1. 生成 mini-batch 人格
            personas = await self._persona_generator.generate_batch(cfg.batch_size)
            if len(personas) < cfg.validation_split + 1:
                logger.warning("Not enough personas generated, skipping epoch")
                continue

            train_personas = personas[: -cfg.validation_split]
            val_personas = personas[-cfg.validation_split :]

            # 2. 在训练集上前向传播
            train_reports = await self._evaluate_batch(train_personas)
            train_mean = _mean(r.overall_score for r in train_reports)

            # 3. 反向传播：利用或探索
            is_exploration = random.random() < cfg.exploration_rate
            if is_exploration:
                changes = await self._optimizer.explore()
                logger.info("Epoch %d: EXPLORE — %d changes", epoch + 1, len(changes))
            else:
                worst_fields = _aggregate_worst(train_reports)
                changes = await self._optimizer.exploit(worst_fields)
                logger.info("Epoch %d: EXPLOIT — %d changes", epoch + 1, len(changes))

            # 4. 应用改动
            if changes:
                self._optimizer.apply(changes)

            # 5. 在留出集上验证
            val_reports = await self._evaluate_batch(val_personas)
            val_mean = _mean(r.overall_score for r in val_reports)

            # 6. 接受或回滚
            accepted = False
            if val_mean > best_score and changes:
                best_score = val_mean
                best_epoch = epoch + 1
                patience_counter = 0
                self._optimizer.commit()
                accepted = True
                logger.info(
                    "Epoch %d: ACCEPT — val=%.3f (new best)",
                    epoch + 1,
                    val_mean,
                )
            elif changes:
                patience_counter += 1
                self._optimizer.rollback()
                logger.info(
                    "Epoch %d: ROLLBACK — val=%.3f <= best=%.3f",
                    epoch + 1,
                    val_mean,
                    best_score,
                )
            else:
                logger.info("Epoch %d: NO CHANGES — val=%.3f", epoch + 1, val_mean)

            epoch_result = EpochResult(
                epoch=epoch + 1,
                train_mean=round(train_mean, 4),
                val_mean=round(val_mean, 4),
                params_changed=[c.description for c in changes],
                exploration=is_exploration,
                accepted=accepted,
                train_reports=[r.to_dict() for r in train_reports],
                val_reports=[r.to_dict() for r in val_reports],
            )
            history.append(epoch_result)
            self._save_epoch(epoch_result)

            # 7. 早停检查
            if patience_counter >= cfg.early_stop_patience:
                logger.info("Early stopping: patience exhausted")
                return OptimizationResult(
                    epochs_run=epoch + 1,
                    best_score=best_score,
                    best_epoch=best_epoch,
                    stop_reason="early_stop",
                    history=history,
                )
            if val_mean >= cfg.score_target:
                logger.info("Target score reached: %.3f >= %.3f", val_mean, cfg.score_target)
                return OptimizationResult(
                    epochs_run=epoch + 1,
                    best_score=best_score,
                    best_epoch=best_epoch,
                    stop_reason="target_reached",
                    history=history,
                )

        # 从最后一个 epoch 收集最终归因
        final_attrs: list[str] = []
        if history:
            last_train = history[-1].train_reports
            for r in last_train:
                attrs = r.get("attributions")
                if not isinstance(attrs, list):
                    continue
                for a in attrs:
                    if isinstance(a, str) and a not in final_attrs:
                        final_attrs.append(a)

        return OptimizationResult(
            epochs_run=len(history),
            best_score=best_score,
            best_epoch=best_epoch,
            stop_reason="max_epochs",
            history=history,
            final_attributions=final_attrs,
        )

    async def _evaluate_batch(
        self,
        personas: list[OnionProfile],
    ) -> list[EvalReport]:
        """评估一批人格：模拟事件 → pipeline → 评分。"""
        from openbiliclaw.soul.pipeline import signals_from_events

        reports: list[EvalReport] = []
        for persona in personas:
            try:
                # 生成事件
                events = await self._event_simulator.simulate(
                    persona,
                    event_count=self._config.event_count_per_persona,
                )

                # 通过 pipeline 处理
                pipeline = self._pipeline_factory()
                signals = signals_from_events(events)
                await pipeline.ingest_batch(signals)
                await pipeline.flush()

                # 获取预测画像
                predicted = pipeline._load_profile()

                # 评估
                report = await self._evaluator.evaluate(persona, predicted)
                reports.append(report)
            except Exception:
                logger.exception("Failed to evaluate persona")

        return reports

    def _save_epoch(self, result: EpochResult) -> None:
        """将 epoch 结果持久化到 data/eval/reports/。"""
        report_dir = self._data_dir / "eval" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / f"auto_epoch_{result.epoch:03d}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "epoch": result.epoch,
                    "train_mean": result.train_mean,
                    "val_mean": result.val_mean,
                    "params_changed": result.params_changed,
                    "exploration": result.exploration,
                    "accepted": result.accepted,
                    "timestamp": datetime.now().isoformat(),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _mean(values: Any) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def _aggregate_worst(reports: list[Any]) -> list[Any]:
    """收集所有报告中最差的字段，按字段去重。"""
    field_map: dict[str, Any] = {}
    for report in reports:
        for f in report.worst_fields:
            key = f"{f.layer}.{f.field}"
            if key not in field_map or f.score < field_map[key].score:
                field_map[key] = f

    return sorted(field_map.values(), key=lambda f: f.score)[:5]
