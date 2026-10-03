"""Core Agent 预算三口径：次数 + token + 钱(设计稿 §3.4)。

一期落次数+token；钱随 ModelInfo.cost 就绪即开——cost 未配置或该次
usage 缺席(网关不给，null 不伪造)时对应口径休眠，不误判也不虚计。
超限抛 BudgetExceeded(与旧链 ExecutionBudgetError 同族语义，由消费层
转文案)，检查点在 loop 每轮模型响应之后。
"""
from __future__ import annotations

from app.services.model.execution import ExecutionBudgetError


class BudgetExceeded(ExecutionBudgetError):
    """预算任一口径耗尽；message 面向作者，说明该缩小任务还是换模型。

    继承旧链异常族：消费层 except ExecutionBudgetError 统一可捕，不裂族。
    """


class CoreBudget:
    """一轮 Agent 的预算与累计；域策略注入上限，核心层只记账与拦截。"""

    def __init__(self, *, max_model_calls: int = 20, max_total_tokens: int | None = None,
                 max_cost_usd: float | None = None, model_cost: dict | None = None):
        self.max_model_calls = max_model_calls
        self.max_total_tokens = max_total_tokens
        self.max_cost_usd = max_cost_usd
        self.model_cost = model_cost or None
        self.total_tokens = 0
        self.total_cost_usd = 0.0

    def record_call(self, usage: dict | None) -> None:
        """记录一次模型调用的用量；usage 缺席跳过 token/钱累计。"""
        if not usage:
            return
        total = usage.get('total') or 0
        self.total_tokens += int(total)
        if self.model_cost:
            inp = usage.get('input') or 0
            out = usage.get('output') or 0
            self.total_cost_usd += (inp / 1_000_000) * self.model_cost.get('input', 0.0) \
                + (out / 1_000_000) * self.model_cost.get('output', 0.0)

    def check(self, *, total_calls: int) -> None:
        """检查全部口径；越限抛 BudgetExceeded(先到先抛，口径间不互抵)。"""
        if total_calls >= self.max_model_calls:
            raise BudgetExceeded('本轮模型调用次数已达到上限，请缩小任务后重新发送。')
        if self.max_total_tokens is not None and self.total_tokens > self.max_total_tokens:
            raise BudgetExceeded(
                f'本轮 token 预算已耗尽(约 {self.total_tokens})，请缩小任务或换更大上下文的模型。')
        if self.max_cost_usd is not None and self.total_cost_usd > self.max_cost_usd:
            raise BudgetExceeded(
                f'本轮成本预算已耗尽(约 ${self.total_cost_usd:.4f})，请缩小任务后重新发送。')

    def snapshot(self, *, total_calls: int) -> dict:
        """三口径报表快照；供 final/审计按 novel 可查(验收 6)。"""
        return {'model_calls': total_calls,
                'max_model_calls': self.max_model_calls,
                'total_tokens': self.total_tokens,
                'max_total_tokens': self.max_total_tokens,
                'cost_usd': round(self.total_cost_usd, 6),
                'max_cost_usd': self.max_cost_usd}
