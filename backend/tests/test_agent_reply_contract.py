"""创作对话 Agent 输出的宽松解析：任何波动都不能把原始 JSON 丢给作者。"""
import json

from app.services.context.budget import MAX_CHAT_OUTPUT_CHARS
from app.services.conversation.tasks import _parse_agent_reply


def test_plain_text_falls_back_without_actions():
    """模型返回普通文本时按普通回答处理，不报错、不产生写入动作。"""
    assert _parse_agent_reply('他们为什么互不信任？可以这样想……') == ('他们为什么互不信任？可以这样想……', None, None, None)


def test_overlong_reply_never_leaks_raw_json():
    """回复超长时截断保留正文，而不是把整个 JSON 原样显示给作者。"""
    payload = {'reply': '长' * (MAX_CHAT_OUTPUT_CHARS + 5000), 'actions': [], 'uncertainties': []}
    text, result, operation, decided = _parse_agent_reply(json.dumps(payload, ensure_ascii=False))

    assert not text.startswith('{')
    assert len(text) == MAX_CHAT_OUTPUT_CHARS
    assert result is None and operation is None and decided is None


def test_invalid_action_is_dropped_but_valid_ones_survive():
    """单条动作不合规不能连坐整轮；能用的动作照常保留。"""
    payload = {
        'reply': '我把能确定的先记下来。',
        'actions': [
            {'kind': 'fact', 'subject': '记忆', 'attribute': '货币性', 'value': '可提取、可转让、可支付'},
            {'kind': 'invented_kind', 'x': 1},
            {'kind': 'entity', 'name': '童年', 'entity_kind': 'item', 'description': '最值钱也最先被卖掉'},
        ],
        'uncertainties': ['记忆定价规则未确定'],
    }
    text, result, operation, decided = _parse_agent_reply(json.dumps(payload, ensure_ascii=False))

    assert text == '我把能确定的先记下来。'
    assert [action['kind'] for action in result['actions']] == ['fact', 'entity']
    assert result['uncertainties'] == ['记忆定价规则未确定']
    assert decided == 'discuss' and operation is None


def test_agent_manuscript_decides_its_own_mode():
    """作者没有声明意图时，由 Agent 的稿件决定这次是续写还是新章。"""
    payload = {'reply': '接在前面写了一段。', 'actions': [],
               'manuscript': {'operation': 'append', 'content': '他推开门，风灌了进来。'}, 'uncertainties': []}
    text, result, operation, decided = _parse_agent_reply(json.dumps(payload, ensure_ascii=False))

    assert text == '他推开门，风灌了进来。'
    assert operation == 'append' and decided == 'continue'
    assert result['decided_mode'] == 'continue'


def test_broken_json_is_treated_as_plain_text():
    """JSON 截断时退回文本，而不是抛给调用方。"""
    broken = '{"reply":"还没写完'
    assert _parse_agent_reply(broken) == (broken, None, None, None)
