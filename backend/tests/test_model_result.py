"""模型输出完成性、预算和真实元数据契约。"""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from app.services.model.result import ModelOutputError, parse_model_result


def test_real_message_preserves_provider_usage_without_estimation():
    """标准用量优先，保留细分 token 数据，不从正文长度推算。"""
    response = AIMessage(
        content="  候选正文。\n",
        response_metadata={"model_name": "local-writer", "finish_reason": "stop", "token_usage": {"total_tokens": 999}},
        usage_metadata={"input_tokens": 12, "output_tokens": 4, "total_tokens": 16,
                        "input_token_details": {"cache_read": 3}},
    )
    result = parse_model_result(response, max_output_chars=100)
    assert result.text == "候选正文。"
    assert result.model == "local-writer"
    assert result.finish_reason == "stop"
    assert result.usage == response.usage_metadata
    result.usage["input_token_details"]["cache_read"] = 100
    assert response.usage_metadata["input_token_details"]["cache_read"] == 3


@pytest.mark.parametrize("response", [AIMessage(content="正文"), SimpleNamespace(content="正文")])
def test_missing_metadata_remains_unknown(response):
    """本地模型与既有替身不必提供元数据，未知值不可填入猜测。"""
    result = parse_model_result(response, max_output_chars=2)
    assert result.text == "正文"
    assert result.model is result.usage is result.finish_reason is None


def test_raw_provider_usage_is_preserved_without_manufactured_fields():
    """未提供标准用量时返回原始用量，不补齐提供方未返回的数字。"""
    result = parse_model_result(AIMessage(content="正文", response_metadata={
        "model": "writer-v2", "token_usage": {"completion_tokens": 2}, "finish_reason": "stop",
    }), max_output_chars=20)
    assert result.model == "writer-v2"
    assert result.usage == {"completion_tokens": 2}


@pytest.mark.parametrize(("finish_reason", "code"), [
    ("length", "truncated"), ("max_tokens", "truncated"), ("max_output_tokens", "truncated"),
    ("content_filter", "content_filtered"), ("tool_calls", "tool_call"),
    ("function_call", "tool_call"), ("tool_use", "tool_call"), ("unknown", "incomplete"),
    (123, "invalid_finish_reason"),
])
def test_incomplete_output_is_not_accepted_even_with_plausible_text(finish_reason, code):
    """有正文不等于生成成功，截断与未知完成状态必须失败。"""
    response = AIMessage(content="看似完整的正文。", response_metadata={"finish_reason": finish_reason})
    with pytest.raises(ModelOutputError) as caught:
        parse_model_result(response, max_output_chars=100)
    assert caught.value.code == code
    assert "看似完整的正文" not in str(caught.value)


@pytest.mark.parametrize("tool_field", [
    {"tool_calls": [{"name": "lookup", "args": {}, "id": "call_1", "type": "tool_call"}]},
    {"invalid_tool_calls": [{"name": "lookup", "args": "{", "id": "call_1", "error": "无效参数", "type": "invalid_tool_call"}]},
    {"additional_kwargs": {"tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}]}},
    {"additional_kwargs": {"function_call": {"name": "lookup", "arguments": "{}"}}},
])
def test_tool_requests_cannot_be_saved_as_candidates(tool_field):
    """工具调用即使附带文字，也不是可采纳的最终正文。"""
    with pytest.raises(ModelOutputError) as caught:
        parse_model_result(AIMessage(content="正在查询", **tool_field), max_output_chars=100)
    assert caught.value.code == "tool_call"


@pytest.mark.parametrize(("content", "code"), [
    (None, "non_text"), (42, "non_text"), ([{"type": "text", "text": "正文"}], "non_text"),
    ("", "empty"), (" \n\t", "empty"), ("正文超过预算", "too_long"), (" 正文 ", "too_long"),
])
def test_invalid_text_or_exceeded_budget_fails_without_silent_truncation(content, code):
    """不转换复杂内容块，也不静默截取超预算输出。"""
    with pytest.raises(ModelOutputError) as caught:
        parse_model_result(SimpleNamespace(content=content), max_output_chars=2)
    assert caught.value.code == code


def test_provider_refusal_is_not_an_empty_text_error():
    """拒绝响应保留明确原因，不误报网络故障或空白正文。"""
    with pytest.raises(ModelOutputError) as caught:
        parse_model_result(AIMessage(content="", additional_kwargs={"refusal": "提供方说明"}), max_output_chars=20)
    assert caught.value.code == "refused"
    assert "提供方说明" not in str(caught.value)


@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_invalid_application_budget_is_rejected(budget):
    """预算配置错误不能造成无界输出或伪成功。"""
    with pytest.raises(ValueError, match="正整数"):
        parse_model_result(SimpleNamespace(content="正文"), max_output_chars=budget)


def test_provider_stop_reason_is_checked():
    """兼容 stop_reason 字段，但同样拒绝长度截断。"""
    with pytest.raises(ModelOutputError) as caught:
        parse_model_result(AIMessage(content="正文", response_metadata={"stop_reason": "max_tokens"}), max_output_chars=20)
    assert caught.value.code == "truncated"


@pytest.mark.parametrize(("metadata", "code"), [
    ({"finish_reason": None, "stop_reason": "max_tokens"}, "truncated"),
    ({"finish_reason": "stop", "stop_reason": "max_tokens"}, "truncated"),
    ({"finish_reason": "max_tokens", "stop_reason": "end_turn"}, "truncated"),
    ({"finish_reason": "stop", "stop_reason": "content_filter"}, "content_filtered"),
    ({"finish_reason": "stop", "stop_reason": "tool_use"}, "tool_call"),
    ({"finish_reason": "stop", "stop_reason": "unknown"}, "incomplete"),
    ({"finish_reason": "stop", "stop_reason": 42}, "invalid_finish_reason"),
])
def test_both_completion_fields_are_checked(metadata, code):
    """兼容端点同时提供两个结束字段时，正常字段不能掩盖异常字段。"""
    with pytest.raises(ModelOutputError) as caught:
        parse_model_result(AIMessage(content="正文", response_metadata=metadata), max_output_chars=20)
    assert caught.value.code == code


def test_null_finish_reason_falls_back_to_actual_stop_reason():
    """显式空的 finish_reason 不得丢失有效 stop_reason 元数据。"""
    result = parse_model_result(AIMessage(content="正文", response_metadata={
        "finish_reason": None, "stop_reason": "end_turn",
    }), max_output_chars=20)
    assert result.finish_reason == "end_turn"
