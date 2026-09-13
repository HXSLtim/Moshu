#!/usr/bin/env bash
# 后端测试入口：清理代理变量后调用 run_tests.py，并原样传递退出码。
#
# 本机开着 Clash 时，只 unset ALL_PROXY/all_proxy 不足以跑测试：NO_PROXY 里的
# `[::1]` 会让 httpx 在导入期抛 `InvalidURL: Invalid port: ':1]'`，测试在
# collection 阶段就崩，报错看起来与代理无关。这里统一清掉全部 8 个代理变量。
#
# 用法（参数原样转给 run_tests.py）：
#   ./run_tests.sh                              # 等同 --mode all
#   ./run_tests.sh --mode unit                  # 只跑不依赖外部服务的测试
#   ./run_tests.sh --mode coverage              # 生成覆盖率报告
#   ./run_tests.sh --file test_rag_service.py   # 跑单个测试文件
set -o pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$BACKEND_DIR/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
    echo "找不到虚拟环境解释器：$PYTHON" >&2
    echo "请先在 backend/ 下创建 .venv 并安装 requirements.txt" >&2
    exit 1
fi

if [ "$#" -eq 0 ]; then
    set -- --mode all
fi

exec env \
    -u ALL_PROXY -u all_proxy \
    -u HTTP_PROXY -u http_proxy \
    -u HTTPS_PROXY -u https_proxy \
    -u NO_PROXY -u no_proxy \
    "$PYTHON" "$BACKEND_DIR/run_tests.py" "$@"
