"""测试运行脚本的模式选择与退出码回归测试。"""

import run_tests


def test_unit_mode_runs_everything_except_explicit_integration(monkeypatch):
    captured = []

    def fake_run(arguments):
        captured.append(list(arguments))
        return 0

    monkeypatch.setattr(run_tests, "_run_pytest", fake_run)

    assert run_tests.run_unit_tests() == 0
    assert captured == [["tests/", "-m", "not integration"]]


def test_integration_mode_is_opt_in_and_propagates_failure(monkeypatch):
    captured = []

    def fake_run(arguments):
        captured.append(list(arguments))
        return 7

    monkeypatch.setattr(run_tests, "_run_pytest", fake_run)

    assert run_tests.run_integration_tests() == 7
    assert captured == [[
        "tests/",
        "-m",
        "integration",
        "--run-integration",
    ]]
