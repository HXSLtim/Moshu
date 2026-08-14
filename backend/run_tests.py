"""测试运行脚本，确保pytest退出码能够传递给调用方。"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence


BACKEND_DIR = Path(__file__).resolve().parent


def _run_pytest(arguments: Sequence[str]) -> int:
    """执行pytest并原样返回退出码，避免失败被误报为成功。"""
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", *arguments],
        check=False,
        cwd=BACKEND_DIR,
    )
    return completed.returncode


def run_all_tests() -> int:
    """运行所有测试。"""
    print("运行所有测试...")
    return _run_pytest(["tests/"])


def run_unit_tests() -> int:
    """运行不依赖真实外部服务的测试。"""
    print("运行单元测试...")
    return _run_pytest(["tests/", "-m", "not integration"])


def run_integration_tests() -> int:
    """只运行显式标记且允许访问真实外部服务的集成测试。"""
    print("运行集成测试...")
    return _run_pytest([
        "tests/",
        "-m",
        "integration",
        "--run-integration",
    ])


def run_with_coverage() -> int:
    """运行测试并生成覆盖率报告。"""
    print("运行测试并生成覆盖率报告...")
    exit_code = _run_pytest([
        "tests/",
        "--cov=app",
        "--cov-report=html",
        "--cov-report=term",
    ])
    if exit_code == 0:
        print("\n覆盖率报告已生成: htmlcov/index.html")
    return exit_code


def run_specific_test(test_file: str) -> int:
    """运行指定测试文件。"""
    print(f"运行测试文件: {test_file}")
    return _run_pytest([f"tests/{test_file}", "-v"])


def main() -> int:
    """解析参数并返回最终测试退出码。"""
    parser = argparse.ArgumentParser(description="运行测试")
    parser.add_argument(
        "--mode",
        choices=["all", "unit", "integration", "coverage"],
        default="all",
        help="测试模式",
    )
    parser.add_argument(
        "--file",
        help="运行特定测试文件（如 test_rag_service.py）",
    )
    args = parser.parse_args()

    if args.file:
        return run_specific_test(args.file)
    if args.mode == "unit":
        return run_unit_tests()
    if args.mode == "integration":
        return run_integration_tests()
    if args.mode == "coverage":
        return run_with_coverage()
    return run_all_tests()


if __name__ == "__main__":
    raise SystemExit(main())
