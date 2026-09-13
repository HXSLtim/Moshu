"""在固定合成原文上运行真实简介提取，保存实际输入/输出与结构验收。

从backend运行：.venv/bin/python ../evaluations/run_digest_cases.py --output ../.Codex/digest-real.json
本脚本不连接作者数据库，不生成作者评分。
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from time import monotonic
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from langchain_core.callbacks import BaseCallbackHandler
from app.core.config import settings
from app.services.digest_extractor import DigestExtractor, validate_digest
from app.services.model_provider import create_chat_model


class Capture(BaseCallbackHandler):
    def __init__(self):
        self.calls = []

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self.calls.append({'run_id': str(run_id), 'messages': [[{'role': message.type, 'content': message.content} for message in batch] for batch in messages]})

    def on_llm_end(self, response, *, run_id, **kwargs):
        call = next(item for item in self.calls if item['run_id'] == str(run_id))
        message = response.generations[0][0].message
        call.update(output=message.content, response_metadata=message.response_metadata,
                    usage=getattr(message, 'usage_metadata', None))

    def on_llm_error(self, error, *, run_id, **kwargs):
        call = next(item for item in self.calls if item['run_id'] == str(run_id))
        call['error_type'] = type(error).__name__


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', default=None)
    parser.add_argument('--cases', type=Path, default=Path(__file__).with_name('novel_memory_cases.json'))
    args = parser.parse_args()
    fixture = args.cases
    cases = json.loads(fixture.read_text())['cases']
    report = {'status': '真实运行中', 'started_at': datetime.now(timezone.utc).isoformat(),
              'fixture_sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(),
              'configured_model': settings.OPENAI_MODEL_SIMPLE, 'author_scores': None, 'cases': []}
    report['runtime'] = {'reasoning_effort': settings.LLM_REASONING_EFFORT,
                         'json_schema_enabled': settings.LLM_JSON_SCHEMA_ENABLED,
                         'max_output_tokens': settings.LLM_MAX_OUTPUT_TOKENS}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        if case['task_type'] != 'digest_extraction' or (args.case and args.case != case['id']):
            continue
        source = next(source for source in case['source_chapters'] if source['chapter_number'] == case['target_chapter'] and source['version'] == case['current_versions'][str(case['target_chapter'])])
        capture = Capture()
        model = create_chat_model(model=settings.OPENAI_MODEL_SIMPLE, temperature=0.2, max_retries=0)
        model.callbacks = [capture]
        revision = SimpleNamespace(id=case['id'], content=source['content'], content_hash=source['sha256'])
        result = {'id': case['id'], 'source_sha256': source['sha256']}
        started = monotonic()
        try:
            payload = await DigestExtractor(model).extract(revision)
            result.update(status='结构与出处通过', digest=validate_digest(payload, revision))
        except Exception as exc:
            result.update(status='失败', error_type=type(exc).__name__, error_code=getattr(exc, 'code', None), error=str(exc))
        result.update(latency_ms=round((monotonic()-started)*1000), calls=capture.calls)
        report['cases'].append(result)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        print(case['id'], result['status'], result['latency_ms'], flush=True)
    report['status'] = '已完成真实运行，作者质量评分待执行'
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    asyncio.run(main())
