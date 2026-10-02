"""导出 OpenAPI 契约到 frontend/openapi.json,作为前端代码生成的唯一事实源。

用法(直接调 python 必须清掉全部 8 个代理变量,原因见 AGENTS.md「验证」节):

    cd backend && env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy \\
        -u HTTPS_PROXY -u https_proxy -u NO_PROXY -u no_proxy \\
        .venv/bin/python export_openapi.py           # 写出契约
        .venv/bin/python export_openapi.py --check   # 校验契约是否与代码漂移

`--check` 模式下契约不一致时退出码非 0,可用于 CI 或提交前自检;
任何 response_model 的改动都必须同 PR 更新 openapi.json 与前端生成物。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from app.main import app  # noqa: E402

TARGET = pathlib.Path(__file__).resolve().parent.parent / 'frontend' / 'openapi.json'


def build_spec() -> str:
    """序列化应用契约;键排序保证同代码生成的文本稳定可 diff。"""
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(description='导出或校验 OpenAPI 契约')
    parser.add_argument('--check', action='store_true', help='校验现有契约文件是否与代码一致')
    args = parser.parse_args()

    spec = build_spec()
    if not args.check:
        TARGET.write_text(spec, encoding='utf-8')
        print(f'契约已写出: {TARGET}')
        return 0

    if not TARGET.exists():
        print(f'契约文件不存在: {TARGET},请先运行导出')
        return 1
    current = TARGET.read_text(encoding='utf-8')
    if current == spec:
        print('openapi.json 与代码一致')
        return 0
    print('openapi.json 与代码不一致(契约漂移):请运行导出并同步前端生成物')
    return 1


if __name__ == '__main__':
    sys.exit(main())
