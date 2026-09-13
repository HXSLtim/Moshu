"""Agent 运行时的模型替身：实现 bind_tools/astream 契约，同时保留按调用计数的能力。"""
from types import SimpleNamespace

from langchain_core.messages import AIMessageChunk


class AgentStub:
    """把 AsyncMock 包装成支持工具调用的模型替身。

    测试仍然通过设置 ``model.return_value`` 控制单次返回，并可用
    ``model.await_count`` 断言调用次数。
    """

    def __init__(self, model):
        self.model = model
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def ainvoke(self, payload):
        return await self.model(payload)

    async def astream(self, payload):
        result = await self.model(payload)
        if isinstance(result, SimpleNamespace) or result is not None:
            content = getattr(result, 'content', '')
            metadata = getattr(result, 'response_metadata', None) or {}
            additional = getattr(result, 'additional_kwargs', None) or {}
            usage = getattr(result, 'usage_metadata', None)
            chunk = AIMessageChunk(content=content if isinstance(content, str) else content,
                                   response_metadata=metadata, additional_kwargs=additional)
            if usage:
                chunk.usage_metadata = usage
            yield chunk
