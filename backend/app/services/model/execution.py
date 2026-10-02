"""整轮执行预算与模型调用计量，不推测提供方未返回的使用量。"""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from time import monotonic
from uuid import uuid4

from app.core.config import settings


class ExecutionBudgetError(ValueError):
    """整轮调用预算已耗尽，调用方应保存明确失败。"""


@dataclass
class ExecutionMeter:
    timeout_seconds: float
    max_model_calls: int
    execution_id: str = field(default_factory=lambda: str(uuid4()))
    started: float = field(default_factory=monotonic)
    calls: list = field(default_factory=list)
    status: str = 'running'
    elapsed_ms: int | None = None
    error_code: str | None = None

    def check_deadline(self):
        """即便上游吞掉取消，也不能在截止时间后继续调用或交付。"""
        if monotonic() - self.started >= self.timeout_seconds:
            raise TimeoutError('本轮执行截止时间已到')

    def snapshot(self):
        usage = None
        if self.calls and all(isinstance(call.get('usage'), dict) for call in self.calls):
            keys = ('input_tokens', 'output_tokens', 'total_tokens')
            normalized = [{key: call['usage'].get(key, call['usage'].get(
                {'input_tokens': 'prompt_tokens', 'output_tokens': 'completion_tokens', 'total_tokens': 'total_tokens'}[key]))
                for key in keys} for call in self.calls]
            if all(all(type(item.get(key)) is int for key in keys) for item in normalized):
                usage = {key: sum(item[key] for item in normalized) for key in keys}
        return {'execution_id': self.execution_id, 'status': self.status, 'deadline_seconds': self.timeout_seconds,
                'max_model_calls': self.max_model_calls, 'model_calls': len(self.calls),
                'latency_ms': self.elapsed_ms if self.elapsed_ms is not None else int((monotonic() - self.started) * 1000),
                'usage': usage, 'transport_attempts': None, 'error_code': self.error_code, 'calls': deepcopy(self.calls)}


_current_meter: ContextVar[ExecutionMeter | None] = ContextVar('writing_execution_meter', default=None)


@asynccontextmanager
async def execution_scope(*, max_model_calls: int = 6, timeout_seconds: float | None = None, execution_id: str | None = None):
    """嵌套工作流共享同一截止时间和调用总额，避免逐节点重置预算。"""
    existing = _current_meter.get()
    if existing is not None:
        try:
            existing.check_deadline()
            yield existing
            existing.check_deadline()
        except BaseException as exc:
            existing.status = 'cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed'
            existing.error_code = classify_execution_error(exc)
            raise
        return
    timeout = timeout_seconds if timeout_seconds is not None else settings.LLM_TIMEOUT_SECONDS * (settings.LLM_MAX_RETRIES + 1)
    meter = ExecutionMeter(timeout, max_model_calls, **({"execution_id": execution_id} if execution_id else {}))
    token = _current_meter.set(meter)
    try:
        async with asyncio.timeout(timeout):
            yield meter
            meter.check_deadline()
        if meter.status == 'running':
            meter.status = 'completed'
    except asyncio.CancelledError:
        meter.status = 'cancelled'
        meter.error_code = 'cancelled'
        raise
    except Exception as exc:
        meter.status = 'failed'
        meter.error_code = classify_execution_error(exc)
        raise
    finally:
        meter.elapsed_ms = int((monotonic() - meter.started) * 1000)
        _current_meter.reset(token)


async def invoke_model(runnable, payload):
    """每次逻辑模型调用单独计量；SDK内部网络重试次数保持未知。"""
    meter = _current_meter.get()
    if meter is None:
        async with execution_scope():
            return await invoke_model(runnable, payload)
    meter.check_deadline()
    if len(meter.calls) >= meter.max_model_calls:
        raise ExecutionBudgetError('本轮模型调用次数已达到上限，请缩小任务后重新发送。')
    call = {'status': 'running', 'model': None, 'usage': None, 'finish_reason': None, 'latency_ms': None, 'error_code': None}
    meter.calls.append(call)
    started = monotonic()
    try:
        result = await runnable.ainvoke(payload)
        metadata = getattr(result, 'response_metadata', None)
        metadata = metadata if isinstance(metadata, dict) else {}
        usage = getattr(result, 'usage_metadata', None) or metadata.get('token_usage')
        model = metadata.get('model_name') or metadata.get('model')
        call.update(status='returned', model=model if isinstance(model, str) else None,
                    usage=deepcopy(usage) if isinstance(usage, dict) and usage else None,
                    finish_reason=metadata.get('finish_reason') or metadata.get('stop_reason'))
        meter.check_deadline()
        return result
    except asyncio.CancelledError:
        call['status'] = 'cancelled'
        call['error_code'] = 'cancelled'
        raise
    except Exception as exc:
        call['status'] = 'failed'
        call['error_code'] = classify_execution_error(exc)
        raise
    finally:
        call['latency_ms'] = int((monotonic() - started) * 1000)


def classify_execution_error(exc):
    if isinstance(exc, TimeoutError):
        return 'deadline_exceeded'
    if isinstance(exc, ExecutionBudgetError):
        return 'call_limit_exceeded'
    if isinstance(exc, asyncio.CancelledError):
        return 'cancelled'
    return getattr(exc, 'code', None) or 'model_request_failed'


async def stream_model(runnable, payload):
    """流式模型调用；与 invoke_model 共用同一份预算和计量口径。"""
    meter = _current_meter.get()
    if meter is None:
        async with execution_scope():
            async for chunk in stream_model(runnable, payload):
                yield chunk
        return
    meter.check_deadline()
    if len(meter.calls) >= meter.max_model_calls:
        raise ExecutionBudgetError('本轮模型调用次数已达到上限，请缩小任务后重新发送。')
    call = {'status': 'running', 'model': None, 'usage': None, 'finish_reason': None,
            'latency_ms': None, 'error_code': None, 'streamed': True}
    meter.calls.append(call)
    started = monotonic()
    try:
        async for chunk in runnable.astream(payload):
            yield chunk
        call['status'] = 'returned'
        meter.check_deadline()
    except asyncio.CancelledError:
        call['status'] = 'cancelled'
        call['error_code'] = 'cancelled'
        raise
    except Exception as exc:
        call['status'] = 'failed'
        call['error_code'] = classify_execution_error(exc)
        raise
    finally:
        call['latency_ms'] = int((monotonic() - started) * 1000)


def record_stream_usage(message) -> None:
    """把流式响应的最终用量补回最近一次流式调用，缺失保持 null。"""
    meter = _current_meter.get()
    if meter is None or not meter.calls:
        return
    call = meter.calls[-1]
    if not call.get('streamed'):
        return
    metadata = getattr(message, 'response_metadata', None)
    metadata = metadata if isinstance(metadata, dict) else {}
    usage = getattr(message, 'usage_metadata', None) or metadata.get('token_usage')
    model = metadata.get('model_name') or metadata.get('model')
    call['usage'] = deepcopy(usage) if isinstance(usage, dict) and usage else None
    call['model'] = model if isinstance(model, str) else None
    call['finish_reason'] = metadata.get('finish_reason') or metadata.get('stop_reason')

