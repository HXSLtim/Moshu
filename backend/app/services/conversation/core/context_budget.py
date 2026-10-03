"""Core Agent 三层上下文预算模型+比例制 output reserve(设计稿 §3.4 预算重设计)。

三层：Persistent(长期投影 5-15%)/Session(会话层，下限=压缩 keepRecent 联动)/
Ephemeral(当前章正文+工具结果，吃剩余空间)。output reserve=窗口内预留非额外：
默认取大(window×20%, 绝对下限 16384)；低信任网关可上调至 30% 上限；小窗模型
被「输出不吞半窗」钳制(floor 不至于把 8k 窗的输出预留顶到 16k)。
"""
from __future__ import annotations

from dataclasses import dataclass

_PERSISTENT_RATIO = 0.10        # 设计稿带状 5-15% 取中值
_SESSION_MIN_RATIO = 0.20       # Session 至少两成窗口(与 keepRecent 取大)
_RESERVE_RATIO_DEFAULT = 0.20
_RESERVE_RATIO_LOW_TRUST = 0.30
_RESERVE_FLOOR = 16384


@dataclass(frozen=True)
class ContextBudgetPlan:
    persistent_cap: int
    session_cap: int
    ephemeral_cap: int
    output_reserve: int

    @property
    def total(self) -> int:
        return self.persistent_cap + self.session_cap + self.ephemeral_cap + self.output_reserve

    @staticmethod
    def for_window(context_window: int, keep_recent_tokens: int | None = None,
                   trust: str = 'default') -> 'ContextBudgetPlan':
        """按窗口合成三层预算；keep_recent 联动 Session 层下限。"""
        if context_window <= 0:
            raise ValueError('context_window 必须为正')
        ratio = _RESERVE_RATIO_LOW_TRUST if trust == 'low' else _RESERVE_RATIO_DEFAULT
        reserve = max(int(context_window * ratio), _RESERVE_FLOOR)
        reserve = min(reserve, context_window // 2)  # 输出预留不吞掉大半窗口
        persistent = int(context_window * _PERSISTENT_RATIO)
        session_floor = int(context_window * _SESSION_MIN_RATIO)
        session = max(session_floor, keep_recent_tokens or 0)
        # Session 不挤出 Persistent 与输出余量；Ephemeral 永不为负(至少留 1)。
        session_cap = min(session, context_window - reserve - persistent - 1)
        session_cap = max(session_cap, 1)
        ephemeral = context_window - persistent - session_cap - reserve
        return ContextBudgetPlan(persistent_cap=persistent, session_cap=session_cap,
                                 ephemeral_cap=ephemeral, output_reserve=reserve)
