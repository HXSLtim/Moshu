"""Core Agent provider 层：openai 官方 SDK 薄封装(设计稿 §3.4 四纪律)。

①透传不吞不猜：SDK 的 finish_reason/usage 缺失原样可见，推断归本层
  compat 逻辑——supportsFinishReason=false 时流结束看有无工具调用判
  toolUse/stop；宣称支持却缺失直接报错不静默猜(pi api/openai-completions.ts
  :690-698 同款纪律)。
②max_retries=0：SDK 内置重试与自控预算冲突，归零后重试全走自控计量。
③usage 采集走 stream_options include_usage，网关不支持时 compat 关闭该
  参数，usage 缺席保持 None 不伪造(record_stream_usage 同纪律)。
流式/非流式统一：失败不是异常逃逸，而是 stopReason 为 error/aborted 的
ModelResponse——「取消不是异常，是一条消息」。
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import AsyncIterator

import openai
from loguru import logger

from app.core.config import settings
from app.services.conversation.core.types import ModelResponse, ProviderEvent

_FINISH_MAP = {'stop': 'stop', 'length': 'length', 'tool_calls': 'toolUse',
               'function_call': 'toolUse', 'content_filter': 'error'}


@dataclass
class ProviderCompat:
    """网关差异开关：坑位显式化而非散落特判。"""
    supports_usage_in_streaming: bool = True
    supports_finish_reason: bool = True


class OpenAIStreamProvider:
    """openai-completions 单协议流式 provider(P2 再扩 Model 元数据面)。"""

    def __init__(self, *, client=None, model: str | None = None,
                 compat: ProviderCompat | None = None, temperature: float = 0.8,
                 max_tokens: int | None = None):
        from app.services.conversation.core.models import get_model
        self.model = model or settings.OPENAI_MODEL_COMPLEX
        info = get_model(self.model)
        # 元数据命中优先于全局档：per-model max_tokens/compat(设计稿 §3.4)；
        # 未注册名回退缺省档时不覆盖 settings，保持既有全局行为。
        known = info.id != 'default'
        self.compat = compat or (ProviderCompat(
            supports_usage_in_streaming=info.supports_usage_in_streaming,
            supports_finish_reason=info.supports_finish_reason) if known else ProviderCompat())
        self.temperature = temperature
        self.max_tokens = max_tokens or (info.max_tokens if known else settings.LLM_MAX_OUTPUT_TOKENS)
        self._client = client or openai.AsyncClient(
            api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_API_BASE,
            timeout=settings.LLM_TIMEOUT_SECONDS, max_retries=0)

    async def stream(self, messages: list[dict], tools: list[dict] | None = None) -> AsyncIterator[ProviderEvent]:
        """流式调用模型，产出统一增量事件，终值事件 response_done 永不缺席。"""
        kwargs: dict = {'model': self.model, 'messages': messages, 'stream': True,
                        'temperature': self.temperature, 'max_tokens': self.max_tokens}
        if tools:
            kwargs['tools'] = tools
        if self.compat.supports_usage_in_streaming:
            kwargs['stream_options'] = {'include_usage': True}

        text_parts: list[str] = []
        tool_calls: dict[int, dict] = {}  # index -> {'id','name','args': str}
        finish_raw: str | None = None
        usage_raw = None
        try:
            async for chunk in await self._client.chat.completions.create(**kwargs):
                if getattr(chunk, 'usage', None):
                    usage_raw = chunk.usage
                choices = getattr(chunk, 'choices', None) or []
                if not choices:
                    continue
                choice = choices[-1]
                finish_raw = choice.finish_reason or finish_raw
                delta = choice.delta
                content = getattr(delta, 'content', None)
                if content:
                    text_parts.append(content)
                    yield {'type': 'text_delta', 'delta': content}
                for call in getattr(delta, 'tool_calls', None) or []:
                    index = call.index or 0
                    entry = tool_calls.setdefault(index, {'id': None, 'name': None, 'args': ''})
                    # openai SDK 流式增量：call.id 平铺，name/arguments 嵌套在 call.function；
                    # 旧版平铺形状以 getattr 容错兼容，防再犯「fake 随实现走」盲区（真 SDK 实证 2026-10-03）。
                    fn = getattr(call, 'function', None)
                    fn_name = getattr(fn, 'name', None) if fn else getattr(call, 'name', None)
                    fn_args = getattr(fn, 'arguments', None) if fn is not None else getattr(call, 'arguments', None)
                    if call.id or fn_name:
                        first_seen = entry['id'] is None and entry['name'] is None
                        entry['id'] = call.id or entry['id']
                        entry['name'] = fn_name or entry['name']
                        if first_seen and (entry['id'] or entry['name']):
                            yield {'type': 'toolcall_start', 'index': index,
                                   'id': entry['id'], 'name': entry['name']}
                    if fn_args:
                        entry['args'] += fn_args
                        yield {'type': 'toolcall_delta', 'index': index, 'args_delta': fn_args}
        except asyncio.CancelledError:
            # 取消同样以事件收束，不向上抛断流——「取消不是异常，是一条消息」。
            yield {'type': 'response_done', 'response': self._finalize(
                text_parts, tool_calls, finish_raw, usage_raw, aborted=True)}
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning('Core provider 模型调用失败：{}', exc)
            yield {'type': 'response_done', 'response': ModelResponse(
                stop_reason='error', text=''.join(text_parts),
                error_message=str(exc)[:500], finish_reason_raw=finish_raw)}
            return
        yield {'type': 'response_done', 'response': self._finalize(
            text_parts, tool_calls, finish_raw, usage_raw, aborted=False)}

    def _finalize(self, text_parts, tool_calls, finish_raw, usage_raw, *, aborted: bool) -> ModelResponse:
        calls: list[dict] = []
        for index in sorted(tool_calls):
            entry = tool_calls[index]
            try:
                args = json.loads(entry['args']) if entry['args'] else {}
                if not isinstance(args, dict):
                    args = {}
            except ValueError:
                # 与旧链 _args 容错口径一致：坏 JSON 不让整轮失败，参数交由
                # 工具层校验兜底；这里保留告警不静默。
                logger.warning('工具 {} 参数 JSON 不完整，按空参数处理', entry['name'])
                args = {}
            calls.append({'id': entry['id'], 'name': entry['name'], 'arguments': args})

        if aborted:
            return ModelResponse(stop_reason='aborted', text=''.join(text_parts),
                                 tool_calls=calls, usage=self._usage(usage_raw),
                                 error_message='已取消', finish_reason_raw=finish_raw)
        if finish_raw is not None:
            stop = _FINISH_MAP.get(finish_raw, 'stop')
        elif self.compat.supports_finish_reason:
            # 宣称支持的端点流结束却没给：明确失败，不静默猜(纪律①反向)。
            return ModelResponse(stop_reason='error', text=''.join(text_parts),
                                 tool_calls=calls, error_message='Stream ended without finish_reason',
                                 usage=self._usage(usage_raw))
        else:
            stop = 'toolUse' if calls else 'stop'
        return ModelResponse(stop_reason=stop, text=''.join(text_parts), tool_calls=calls,
                             usage=self._usage(usage_raw), finish_reason_raw=finish_raw)

    @staticmethod
    def _usage(usage_raw) -> dict | None:
        """归一到 input/output/total；缺席保持 None 不伪造(纪律③)。"""
        if not usage_raw:
            return None

        def pick(*names):
            for name in names:
                value = usage_raw.get(name) if isinstance(usage_raw, dict) else getattr(usage_raw, name, None)
                if value is not None:
                    return value
            return None

        prompt = pick('prompt_tokens', 'input_tokens')
        completion = pick('completion_tokens', 'output_tokens')
        total = pick('total_tokens')
        if prompt is None and completion is None and total is None:
            return None
        return {'input': prompt or 0, 'output': completion or 0, 'total': total or 0}

    async def complete(self, messages: list[dict], max_tokens: int | None = None) -> ModelResponse:
        """非流式调用(摘要等一次性任务)；终值与流式同一纪律。"""
        kwargs: dict = {'model': self.model, 'messages': messages, 'stream': False,
                        'temperature': self.temperature,
                        'max_tokens': max_tokens or self.max_tokens}
        try:
            raw = await self._client.chat.completions.create(**kwargs)
        except asyncio.CancelledError:
            return ModelResponse(stop_reason='aborted', error_message='已取消')
        except Exception as exc:  # noqa: BLE001
            logger.warning('Core provider 非流式调用失败：{}', exc)
            return ModelResponse(stop_reason='error', error_message=str(exc)[:500])
        choice = (getattr(raw, 'choices', None) or [None])[0]
        finish_raw = getattr(choice, 'finish_reason', None) if choice else None
        message = getattr(choice, 'message', None) if choice else None
        text = getattr(message, 'content', None) or ''
        if finish_raw is None:
            if self.compat.supports_finish_reason:
                return ModelResponse(stop_reason='error', text=text,
                                     error_message='Stream ended without finish_reason')
            stop = 'stop'
        else:
            stop = _FINISH_MAP.get(finish_raw, 'stop')
        return ModelResponse(stop_reason=stop, text=text,
                             usage=self._usage(getattr(raw, 'usage', None)),
                             finish_reason_raw=finish_raw)

    async def close(self) -> None:
        await self._client.close()
