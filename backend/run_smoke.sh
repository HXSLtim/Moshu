#!/usr/bin/env bash
# 真实模型冒烟闸门：清理代理变量后运行 smoke_agent_real_model.py。
#
# 与 run_tests.sh 同一个坑：本机开着 Clash 时，残留的 HTTP_PROXY/HTTPS_PROXY/NO_PROXY
# 会让 httpx 在导入期抛 `InvalidURL: Invalid port: ':1]'`，报错看起来与代理无关。
# 只清 ALL_PROXY/all_proxy 不够，必须清掉全部 8 个。把清理由文档变成代码，
# 避免每次手敲时漏掉其中几个。
#
# 该脚本会真实调用模型服务，按需手动运行，不进入 pytest 基线。
set -o pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$BACKEND_DIR/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
    echo "找不到虚拟环境解释器：$PYTHON" >&2
    exit 1
fi

exec env \
    -u ALL_PROXY -u all_proxy \
    -u HTTP_PROXY -u http_proxy \
    -u HTTPS_PROXY -u https_proxy \
    -u NO_PROXY -u no_proxy \
    "$PYTHON" "$BACKEND_DIR/smoke_agent_real_model.py" "$@"
