"""Core Agent 类型契约：stopReason 分类学、内部事件与工具结果三通道。

参考 pi Core(packages/agent/src/types.ts)移植，双轨期与 runtime.py(LangGraph
链)平行建设：零共享可变状态、不改旧链一行。内部事件经 events.py 翻译回
墨枢前端既有形状(tool/chunk/final)，"前端零改动"验收线由适配层锁定。

stopReason 七态照 pi 全集移植；deferred(工具延迟)为墨枢当前无场景的
保留枚举，标注不产出。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Literal

# pending 仅存在于流式进行中；deferred 墨枢不产出，保留枚举与 pi 对齐。
StopReason = Literal['pending', 'stop', 'length', 'toolUse', 'error', 'aborted', 'deferred']

# 模型一轮响应的统一终值：无论流式与否、成功与否，都以一条结构化结果收尾。
@dataclass
class ModelResponse:
    """一次模型调用的权威终值。

    失败不是异常逃逸，而是 stopReason 为 error/aborted 的响应——
    「取消不是异常，是一条消息」(设计稿 §3.3)。
    """
    stop_reason: StopReason
    text: str = ''
    tool_calls: list[dict] = field(default_factory=list)  # [{'id','name','arguments':dict}]
    usage: dict | None = None  # provider 实报；缺席保持 None，不伪造
    error_message: str | None = None
    finish_reason_raw: str | None = None  # 网关原始 finish_reason，诊断用


# provider 层事件：openai SDK 增量面到内部统一事件的最小映射。
ProviderEvent = dict
# {'type': 'text_delta', 'delta': str}
# {'type': 'toolcall_start', 'index': int, 'id': str, 'name': str}
# {'type': 'toolcall_delta', 'index': int, 'args_delta': str}
# {'type': 'response_done', 'response': ModelResponse}


# 工具结果三通道(设计稿 §3.5)：content 回模型、details 给前端卡片、
# structured 给程序调用方；isError 不抛也能报失败；terminate 是批级拉闸权。
@dataclass
class ToolResult:
    content: str
    details: dict = field(default_factory=dict)
    structured: dict | None = None
    is_error: bool = False
    terminate: bool = False
    usage: dict | None = None


# 工具执行器沿用旧链受权入口形状：(name, args) -> awaitable[str]。
# 提案/稿件工具不经过执行器，由 loop 内登记(复用 runtime.execute_agent_tool)。
ToolExecutor = Callable[[str, dict], Any]

# 挂点形状：域策略在 FastAPI 层实现、经挂点注入，核心层零业务(设计稿 §3.5)。
# before 返回 {'block': True, 'reason': str, 'terminate': bool} 可拦截。
BeforeToolCall = Callable[[str, dict], dict | None]
AfterToolCall = Callable[[str, dict, ToolResult], ToolResult | None]


@dataclass
class AgentFinal:
    """一轮 Agent 的收尾载荷，形状对齐旧链 final 事件的 data 字段。"""
    actions: list[dict] = field(default_factory=list)
    manuscript: dict | None = None
    decided_mode: str = 'discuss'
    uncertainties: list[str] = field(default_factory=list)
    stop_reason: StopReason = 'stop'
    error_message: str | None = None
    rounds_used: int = 0
