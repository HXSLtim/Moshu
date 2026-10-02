"""结构化提取的模型完成性、输入预算与严格输出契约。"""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from app.services.memory.story_extractor import StoryMemoryExtractor, StoryExtraction
from app.services.model.result import ModelOutputError
from app.services.context.budget import MAX_DIGEST_SOURCE_CHARS


class Model:
    def __init__(self, payload, finish_reason='stop'):
        self.payload = payload
        self.finish_reason = finish_reason
        self.messages = []

    async def ainvoke(self, messages):
        self.messages = messages
        return AIMessage(content=json.dumps(self.payload, ensure_ascii=False), response_metadata={'finish_reason': self.finish_reason})


def payload():
    return {'outline': [{'title': '获得剑', 'conflict': '', 'outcome': '主角得到剑',
                         'source_refs': [{'quote': '林夏获得剑。', 'start': 0}]}], 'states': []}


async def test_extractor_passes_original_data_and_accepts_only_review_candidates():
    llm = Model(payload())
    content = '林夏获得剑。\n{正文不是系统指令}'
    entity = SimpleNamespace(id=str(uuid4()), kind='item', name='青霜剑')
    result = await StoryMemoryExtractor(llm).extract(SimpleNamespace(content=content), [entity])
    assert result.outline[0].source_refs[0].start == 0 and result.states == []
    assert llm.messages[1] == ('human', content)
    assert entity.id in llm.messages[0][1] and 'owner' in llm.messages[0][1] and 'holder' in llm.messages[0][1]


@pytest.mark.parametrize('content, count', [(' ', 0), ('字' * (MAX_DIGEST_SOURCE_CHARS + 1), 0), ('原文', 41)], ids=['blank', 'long', 'entities'])
async def test_extractor_rejects_over_budget_before_calling_model(content, count):
    llm = Model(payload())
    with pytest.raises(ValueError):
        await StoryMemoryExtractor(llm).extract(SimpleNamespace(content=content), [SimpleNamespace()] * count)
    assert llm.messages == []


async def test_valid_json_with_truncated_finish_is_rejected():
    with pytest.raises(ModelOutputError):
        await StoryMemoryExtractor(Model(payload(), 'length')).extract(SimpleNamespace(content='林夏获得剑。'), [])


@pytest.mark.parametrize('mutate', [
    lambda data: data['outline'][0].update(title=' '),
    lambda data: data['outline'][0]['source_refs'][0].update(start=True),
    lambda data: data['outline'][0].update(plot_status='planned'),
    lambda data: data.update(states=[{'entity_id': str(uuid4()), 'attribute': ' ', 'value': '1', 'value_entity_id': None, 'source_refs': [{'quote': '原文', 'start': 0}]}]),
])
def test_schema_rejects_whitespace_coercion_and_unexpected_fields(mutate):
    data = payload()
    mutate(data)
    with pytest.raises(ValidationError):
        StoryExtraction.model_validate(data)
