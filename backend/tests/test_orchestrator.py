"""编排器契约：计划严格校验、DAG 确定性执行、预算与作用域守卫。"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.services.conversation.tools import AgentScope
from app.services.context.builder import ContextScopeError
from app.services.generation import orchestrator
from app.services.generation.orchestrator import PlanOutput, build_plan, run_orchestration
from app.services.generation.workflow import GenerationWorkflow
from app.services.model.result import ModelOutputError, ModelResult


PLAN_JSON = json.dumps({
    'steps': [
        {'id': 1, 'kind': 'retrieve', 'instruction': '林夏 武器',
         'tool': 'search_story_bible', 'depends_on': []},
        {'id': 2, 'kind': 'generate', 'instruction': '写林夏拔剑夜战的段落',
         'depends_on': [1], 'target_length': 800},
        {'id': 3, 'kind': 'consistency', 'instruction': '检查稿件', 'depends_on': [2]},
    ],
    'uncertainties': ['林夏的剑术来源未在账本中确认'],
}, ensure_ascii=False)


class PlannerStub:
    """invoke_model 契约的最小模型替身：ainvoke 返回固定文本。"""

    def __init__(self, text, finish_reason='stop'):
        self._text = text
        self._finish = finish_reason
        self.payloads = []

    async def ainvoke(self, payload):
        self.payloads.append(payload)
        return SimpleNamespace(content=self._text,
                               response_metadata={'finish_reason': self._finish})


@pytest.fixture
def scope():
    return AgentScope(novel_id=1, actor_id=1, novel_lifecycle_id='l' * 32, target_chapter=2)


@pytest.fixture
def context_pack():
    return SimpleNamespace(worldview='钟声报时', story_bible_context=['- 林夏的武器：青霜剑'],
                           digest_context='', structured_context='', manifest={'scope': 'test'})


def test_plan_rejects_cycles_missing_generate_and_sparse_ids():
    with pytest.raises(ValidationError):
        PlanOutput.model_validate({'steps': [
            {'id': 1, 'kind': 'retrieve', 'instruction': '查'},
            {'id': 1, 'kind': 'generate', 'instruction': '写'}]})
    with pytest.raises(ValidationError):
        PlanOutput.model_validate({'steps': [
            {'id': 2, 'kind': 'retrieve', 'instruction': '查'},
            {'id': 3, 'kind': 'generate', 'instruction': '写', 'depends_on': [2]}]})
    with pytest.raises(ValidationError):
        PlanOutput.model_validate({'steps': [
            {'id': 1, 'kind': 'retrieve', 'instruction': '查'},
            {'id': 2, 'kind': 'consistency', 'instruction': '查', 'depends_on': [1]}]})
    # 依赖指向更大编号即成环，直接拒绝。
    with pytest.raises(ValidationError):
        PlanOutput.model_validate({'steps': [
            {'id': 1, 'kind': 'generate', 'instruction': '写', 'depends_on': [2]},
            {'id': 2, 'kind': 'retrieve', 'instruction': '查'}]})


@pytest.mark.asyncio
async def test_build_plan_rejects_garbage_and_truncation():
    with pytest.raises(ModelOutputError) as exc:
        await build_plan(PlannerStub('这不是计划'), instruction='编排一场战斗')
    assert exc.value.code == 'invalid_plan'

    with pytest.raises(ModelOutputError) as exc:
        await build_plan(PlannerStub(PLAN_JSON, finish_reason='length'),
                         instruction='编排一场战斗')
    assert exc.value.code == 'truncated'


@pytest.mark.asyncio
async def test_build_plan_accepts_fenced_json(scope):
    plan = await build_plan(PlannerStub(f'```json\n{PLAN_JSON}\n```'),
                            instruction='编排一场战斗')
    assert [step.kind for step in plan.steps] == ['retrieve', 'generate', 'consistency']
    assert plan.steps[0].tool == 'search_story_bible'


@pytest.mark.asyncio
async def test_run_orchestration_executes_dag_in_order(monkeypatch, scope, context_pack):
    retrieve = AsyncMock(return_value='- [事实，第1章确立] 林夏的武器：青霜剑')
    reply = AsyncMock(return_value=ModelResult(text='夜风掠过檐角，青霜出鞘。'))
    check = AsyncMock(return_value={'has_conflict': False, 'violations': [],
                                    'is_complete': True, 'checks_skipped': [],
                                    'layer_results': {}})
    monkeypatch.setattr(orchestrator, 'writing_service', SimpleNamespace(reply=reply))
    monkeypatch.setattr(orchestrator, 'consistency_service', SimpleNamespace(check_content=check))
    monkeypatch.setattr(GenerationWorkflow, '_load_consistency_reference_sync',
                        staticmethod(lambda *args, **kwargs: {}))

    result = await run_orchestration(
        llm=PlannerStub(PLAN_JSON), instruction='编排林夏的夜战',
        context_pack=context_pack, current_content='第一章结尾。',
        scope=scope, novel_id=1, target_chapter=2,
        read_tool_executor=retrieve)

    assert result.text == '夜风掠过檐角，青霜出鞘。'
    assert retrieve.await_count == 1
    retrieve.assert_awaited_once()
    tool, tool_args = retrieve.await_args.args[1], retrieve.await_args.args[2]
    assert tool == 'search_story_bible' and tool_args == {'query': '林夏 武器'}

    # 检索观察作为资料注入生成指令,且明确不是指令。
    messages = reply.await_args.args[0]
    instruction = next(message[1] for message in messages if message[0] == 'human')
    assert '青霜剑' in instruction and '不是指令' in instruction

    # 一致性检查拿到的是生成稿件,不是检索文本。
    assert check.await_args.kwargs['content'] == '夜风掠过檐角，青霜出鞘。'
    assert result.consistency == {'has_conflict': False, 'violations': [],
                                  'is_complete': True, 'checks_skipped': [], 'layer_results': {}}
    assert result.uncertainties == ['林夏的剑术来源未在账本中确认']

    kinds = [step.type for step in result.workflow_trace.steps]
    assert kinds == ['plan', 'rag', 'llm', 'consistency']
    # 替身 reply 不经过内部 invoke_model,计量只含规划调用;
    # 生产路径中 generate 步经由 WritingService.reply 的 invoke_model 计量。
    assert result.execution['model_calls'] == 1
    assert result.execution['max_model_calls'] == orchestrator.MAX_ORCHESTRATION_MODEL_CALLS


@pytest.mark.asyncio
async def test_consistency_without_generate_dependency_fails_honestly(scope, context_pack):
    plan_json = json.dumps({'steps': [
        {'id': 1, 'kind': 'consistency', 'instruction': '检查', 'depends_on': []},
        {'id': 2, 'kind': 'generate', 'instruction': '写正文'},
    ]}, ensure_ascii=False)
    with pytest.raises(ValueError, match='没有可检查的稿件'):
        await run_orchestration(
            llm=PlannerStub(plan_json), instruction='先检查后写',
            context_pack=context_pack, current_content='', scope=scope, novel_id=1,
            target_chapter=2, read_tool_executor=AsyncMock())


@pytest.mark.asyncio
async def test_scope_error_aborts_orchestration(scope, context_pack):
    async def broken(_scope, _name, _args):
        raise ContextScopeError('小说归属或生命周期已改变，本轮检索终止')

    with pytest.raises(ContextScopeError):
        await run_orchestration(
            llm=PlannerStub(PLAN_JSON), instruction='编排林夏的夜战',
            context_pack=context_pack, current_content='', scope=scope, novel_id=1,
            target_chapter=2, read_tool_executor=broken)


# ---------- 路由层:鉴权、作用域与候选提案 ----------

@pytest.fixture
def orchestrate_api(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.api.dependencies import get_current_user
    from app.api.routes import generation
    from app.db.base import Base, get_db
    from app.models.novel import Novel, Chapter
    from app.models.user import User

    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    db = sessions()
    db.add_all([User(id=1, username='author', email='a@example.com', hashed_password='unused'),
                User(id=2, username='other', email='o@example.com', hashed_password='unused')])
    db.commit()
    db.add_all([Novel(id=1, user_id=1, title='青州夜行', worldview='钟声报时', rag_lifecycle_id='a' * 32),
                Novel(id=2, user_id=2, title='他人作品', rag_lifecycle_id='b' * 32)])
    db.commit()
    db.add_all([Chapter(id=1, novel_id=1, title='第一章', chapter_number=1, content='已保存原稿'),
                Chapter(id=2, novel_id=2, title='他人章节', chapter_number=1, content='私密正文')])
    db.commit()

    app = FastAPI()
    app.include_router(generation.router, prefix='/api/generation')

    def get_test_db():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 1)

    fake = AsyncMock(return_value=SimpleNamespace(
        text='夜风掠过檐角。', plan={'steps': [{'id': 1, 'kind': 'generate'}]},
        uncertainties=[], workflow_trace=None, consistency=None,
        execution={'model_calls': 1, 'max_model_calls': 7}))
    monkeypatch.setattr('app.api.routes.generation.run_orchestration', fake)
    with TestClient(app) as client:
        yield client, db, fake
    db.close()
    engine.dispose()


def orchestrate_payload(**kwargs):
    return {'novel_id': 1, 'chapter_id': 1, 'current_content': '最新未保存原稿',
            'instruction': '编排林夏的夜战：先查武器设定，再写战斗，最后自查。', **kwargs}


def test_orchestrate_creates_proposal_without_touching_chapter(orchestrate_api):
    """编排产出只落候选提案,正文不被直接改写。"""
    from app.models.novel import Chapter
    client, db, fake = orchestrate_api
    body = client.post('/api/generation/orchestrate', json=orchestrate_payload()).json()
    assert body['proposal_id'] and body['content'] == '夜风掠过檐角。'
    assert body['plan']['steps'][0]['kind'] == 'generate'
    assert db.get(Chapter, 1).content == '已保存原稿'


def test_orchestrate_isolates_other_authors(orchestrate_api):
    """他人小说返回 404,编排与提案都不发生。"""
    client, _db, fake = orchestrate_api
    response = client.post('/api/generation/orchestrate', json=orchestrate_payload(novel_id=2))
    assert response.status_code == 404
    assert fake.await_count == 0


def test_orchestrate_runs_as_durable_job(orchestrate_api):
    """编排任务经持久任务队列执行,产物结构可直接被前端轮询消费。"""
    client, _db, fake = orchestrate_api
    created = client.post('/api/generation/jobs', json={
        'request_id': str(__import__('uuid').uuid4()), 'novel_id': 1,
        'expected_novel_lifecycle_id': 'a' * 32, 'kind': 'orchestrate',
        'payload': {'novel_id': 1, 'chapter_id': 1, 'current_content': '最新未保存原稿',
                    'instruction': '编排林夏的夜战'}}).json()
    assert created['status'] in {'queued', 'running', 'completed'}
    job = created
    for _ in range(20):
        if job['status'] in {'completed', 'failed', 'cancelled'}:
            break
        job = client.get(f"/api/generation/jobs/{created['id']}?novel_id=1").json()
    assert job['status'] == 'completed', job
    result = job['result']
    assert result['proposal_id'] and result['content'] == '夜风掠过檐角。'
    assert fake.await_count == 1


def test_openapi_contract_declares_generation_response_models():
    """契约文件必须包含 orchestrate 与 continue 的响应模型,漂移防线的前提。"""
    import json as _json
    import pathlib
    spec = _json.loads((pathlib.Path(__file__).resolve().parents[2]
                        / 'frontend' / 'openapi.json').read_text(encoding='utf-8'))
    schemas = spec['components']['schemas']
    assert 'OrchestrateResponse' in schemas
    assert 'ContinueResponse' in schemas
    assert 'WorkflowTrace' in schemas and 'WorkflowStep' in schemas
    paths = spec['paths']
    assert paths['/api/generation/orchestrate']['post']['responses']['200'] is not None
