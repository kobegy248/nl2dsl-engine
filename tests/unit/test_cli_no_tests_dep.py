"""P1-8：正式 CLI 不依赖 tests 包，且 --help / 必填参数行为正确。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _nl2dsl_py_files() -> list[Path]:
    return [p for p in (PROJECT_ROOT / "nl2dsl").rglob("*.py")]


def test_no_tests_import_in_formal_package():
    """正式包内不得出现 ``from tests`` 或 ``import tests`` 运行时导入。"""
    import re
    pattern = re.compile(r"^\s*(from\s+tests\b|import\s+tests\b)", re.MULTILINE)
    offenders: list[str] = []
    for p in _nl2dsl_py_files():
        txt = p.read_text(encoding="utf-8")
        for m in pattern.finditer(txt):
            offenders.append(f"{p}: {m.group(0).strip()}")
    assert not offenders, "正式包存在 tests 导入：\n" + "\n".join(offenders)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_console_scripts_help_succeed():
    """三个核心 console script 的 --help 都能成功执行。"""
    for mod in (
        "nl2dsl.evaluation.v2_cli",
        "nl2dsl.quality.cli",
        "nl2dsl.feedback.exporter",
    ):
        r = _run(["-m", mod, "--help"])
        assert r.returncode == 0, f"{mod} --help 失败: {r.stderr}"
        assert "usage" in (r.stdout + r.stderr).lower()


def test_feedback_exporter_requires_db_url():
    """Feedback Exporter 未提供 --db-url 时必须明确报错（非零退出）。"""
    r = _run(["-m", "nl2dsl.feedback.exporter", "--output", "x.yaml"])
    assert r.returncode != 0
    assert "--db-url" in (r.stderr + r.stdout)


def test_cli_modules_import_without_tests_package():
    """模拟 tests 包不可用，正式 CLI 模块仍可导入。"""
    code = (
        "import sys; sys.modules['tests'] = None; "
        "import nl2dsl.evaluation.v2_cli, nl2dsl.quality.cli, "
        "nl2dsl.feedback.exporter, nl2dsl.evaluation.cli; "
        "print('ok')"
    )
    r = _run(["-c", code])
    assert r.returncode == 0, f"CLI 模块在 tests 不可用时导入失败: {r.stderr}"
    assert "ok" in r.stdout
