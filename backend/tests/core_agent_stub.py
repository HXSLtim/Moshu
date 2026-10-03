"""Core Agent 模型替身：按脚本依次回 ModelResponse，供 writing_chat core
路径打桩（域流程测试用，替代旧链 AgentStub 的 bind_tools/astream 契约）。

用法：``model = CoreAgentStub(default_text='……')`` 或
``model.responses = [ModelResponse(...), ...]``；夹具里
``monkeypatch.setattr(writing_chat, 'OpenAIStreamProvider', lambda: model)``。
"""
import json

from app.services.conversation.core.types import ModelResponse


class CoreAgentStub:
    def __init__(self, responses=None, default_text: str = '这枚玉佩可以成为下一幕的线索。'):
        self.responses = list(responses or [])
        self.default_text = default_text
        self.calls: list[list[dict]] = []  # 每次模型调用的消息快照
        self.fail_with: BaseException | None = None  # 注入 provider 级失败
        self.hook = None  # stream 前异步回调(迟到标记类副作用)

    async def ainvoke(self, payload):
        """固定任务链(invoke_model→runnable.ainvoke)兼容面：返回带 content 的消息。"""
        from types import SimpleNamespace
        if self.responses:
            response = self.responses.pop(0)
            text = response.text
        else:
            text = self.default_text
        return SimpleNamespace(content=text)

    async def stream(self, messages, tools=None):
        self.calls.append([dict(m) for m in messages])
        if self.hook is not None:
            await self.hook()
        if self.fail_with is not None:
            raise self.fail_with
        if self.responses:
            response = self.responses.pop(0)
        else:
            response = ModelResponse(stop_reason='stop', text=self.default_text)
        if response.text:
            yield {'type': 'text_delta', 'delta': response.text}
        for index, call in enumerate(response.tool_calls):
            yield {'type': 'toolcall_start', 'index': index, 'id': call['id'], 'name': call['name']}
            yield {'type': 'toolcall_delta', 'index': index,
                   'args_delta': json.dumps(call['arguments'], ensure_ascii=False)}
        yield {'type': 'response_done', 'response': response}
