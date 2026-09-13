"""轻量编辑使用真实提示模板和模型消息，异常输出不得伪造成有效评价。"""

import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.models.novel import Chapter, Novel
from app.services.editor_service import EditorService


VALID_REVIEW = {
    "score": 78,
    "summary": "人物动机清楚，过场可以缩短。",
    "issues": [{
        "type": "节奏",
        "level": "warn",
        "message": "赶路段落重复交代目标。",
        "suggestion": "合并两段赶路描写。",
    }],
    "suggested_tags": ["冒险"],
}


def make_service(monkeypatch, response):
    """保留真实提示编排，仅将模型客户端替换为无网络的 Runnable。"""

    seen = []

    async def answer(prompt):
        seen.extend(prompt.to_messages())
        return response

    monkeypatch.setattr(
        "app.services.editor_service.create_chat_model",
        lambda **kwargs: RunnableLambda(answer),
    )
    return EditorService(), seen


def manuscripts():
    """构造不落库的作者数据，避免模型测试触碰真实数据库。"""

    return (
        Novel(id=1, title="远行", genre="奇幻", worldview="行者不能凭空获得物品"),
        Chapter(id=1, novel_id=1, chapter_number=2, title="启程", content="他整理行囊，踏上旅程。"),
    )


async def test_valid_editor_review_preserves_the_model_evaluation(monkeypatch):
    """严格校验后保留模型的全部评价字段，时间由服务端生成。"""

    service, _ = make_service(monkeypatch, AIMessage(content=json.dumps(VALID_REVIEW)))
    novel, chapter = manuscripts()

    result = await service.review_chapter(novel=novel, chapter=chapter)

    assert result is not None
    assert result.model_dump(exclude={"created_at"}) == VALID_REVIEW
    assert result.created_at is not None


async def test_editor_prompt_is_bounded_and_preserves_literal_braces(monkeypatch):
    """长正文只传尾部、长设定只传头部，花括号必须保留为作者原文。"""

    service, seen = make_service(monkeypatch, AIMessage(content=json.dumps(VALID_REVIEW)))
    novel, chapter = manuscripts()
    literal = '主角打开{背包}，查看{"宝剑": 1}，留下一枚{。'
    chapter.content = "不得传入的过远正文" + "旧" * 7000 + literal
    novel.worldview = "世界规则{原样保留}" + "设定" * 1000 + "不得传入的远端设定"
    novel.title = "书" * 500
    novel.genre = "奇" * 500
    chapter.title = "章" * 500

    result = await service.review_chapter(novel=novel, chapter=chapter)

    assert result is not None
    user_prompt = seen[-1].content
    assert literal in user_prompt
    assert "世界规则{原样保留}" in user_prompt
    assert "不得传入的过远正文" not in user_prompt
    assert "不得传入的远端设定" not in user_prompt
    assert len(user_prompt) < 7600


@pytest.mark.parametrize("field,invalid", [
    ("score", "78"),
    ("score", True),
    ("score", 78.5),
    ("score", -1),
    ("score", 101),
    ("summary", "  "),
    ("summary", {"内容": "好"}),
    ("issues", ["损坏的问题"]),
    ("issues", [{"type": "节奏", "level": "danger", "message": "重复"}]),
    ("issues", [{"type": "节奏", "level": "warn", "message": 9}]),
    ("issues", [{"type": "节奏", "level": "warn", "message": "重复", "suggestion": 9}]),
    ("issues", [{"type": "节奏", "message": "重复"}]),
    ("suggested_tags", [9]),
    ("suggested_tags", ["  "]),
    ("suggested_tags", "冒险"),
])
async def test_invalid_editor_fields_reject_the_whole_review(monkeypatch, field, invalid):
    """分数、必需字段和列表元素出错时整份拒绝，不能强制转换或静默删除。"""

    payload = deepcopy(VALID_REVIEW)
    payload[field] = invalid
    service, _ = make_service(monkeypatch, AIMessage(content=json.dumps(payload)))
    novel, chapter = manuscripts()

    assert await service.review_chapter(novel=novel, chapter=chapter) is None


@pytest.mark.parametrize("raw", ["{}", "null", "[]", "不是 JSON", json.dumps([VALID_REVIEW])])
async def test_missing_or_non_object_editor_payload_is_unavailable(monkeypatch, raw):
    """空对象和非对象响应不能被默认评分和固定好评补成成功。"""

    service, _ = make_service(monkeypatch, AIMessage(content=raw))
    novel, chapter = manuscripts()

    assert await service.review_chapter(novel=novel, chapter=chapter) is None


async def test_truncated_editor_review_is_rejected_even_when_json_is_valid(monkeypatch):
    """提供方声明截断时，即使正文能解析为 JSON 也不能发布为完成评价。"""

    response = AIMessage(content=json.dumps(VALID_REVIEW), response_metadata={"finish_reason": "length"})
    service, _ = make_service(monkeypatch, response)
    novel, chapter = manuscripts()

    assert await service.review_chapter(novel=novel, chapter=chapter) is None
