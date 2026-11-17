"""Best-effort local runner for coding-question submissions.

WHAT THIS IS
------------
A student's program is executed as a normal subprocess in a temporary
directory, with each test case's ``input`` piped to stdin and stdout compared
against the case's ``expected_output``. Only Python and JavaScript are
supported (see ``CodingLanguage``); both are available in this project's
development environment.

WHAT THIS IS **NOT**
--------------------
This is NOT a hardened security sandbox. A determined student can still
import ``os``/``fs`` in Python or use Node's standard library to touch the
machine running the backend. Safeguards implemented here are best-effort:

    * a fixed per-test and overall timeout,
    * a minimal environment (no app secrets / API keys),
    * an isolated Python interpreter (``-I``) and a fresh temp cwd,
    * code and output size limits,
    * a language allowlist.

For a real deployment, run submissions in a disposable container / dedicated
judge service (e.g. Judge0 or a Kubernetes job with no network and a
read-only filesystem). ``CODE_EXECUTION_ENABLED=False`` disables execution
entirely and the API returns a clear error instead of running anything.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass

from app.core.config import get_settings
from app.models.assessment import (
    CodeRunSummary,
    CodeTestCaseResult,
    CodingLanguage,
    TestCase,
)


class CodeExecutionError(Exception):
    """Raised when the runner itself cannot be set up (not a student error)."""


@dataclass(frozen=True)
class _LanguageSpec:
    filename: str
    command: list[str]


def _node_path() -> str | None:
    return shutil.which("node") or shutil.which("node.exe")


def _language_spec(language: CodingLanguage) -> _LanguageSpec:
    if language == CodingLanguage.PYTHON:
        # -I: isolated mode (ignore PYTHON* env vars and user site-packages)
        # -B: don't write .pyc files into the temp dir
        return _LanguageSpec("solution.py", [sys.executable, "-I", "-B", "solution.py"])
    if language == CodingLanguage.JAVASCRIPT:
        node = _node_path()
        if not node:
            raise CodeExecutionError(
                "JavaScript execution is unavailable: the 'node' executable was not found on the server."
            )
        return _LanguageSpec("solution.js", [node, "--no-warnings", "solution.js"])
    raise CodeExecutionError(f"Unsupported coding language: {language!r}")


def supported_languages() -> list[str]:
    """Languages that can actually run on this machine right now."""
    available = [CodingLanguage.PYTHON.value]
    if _node_path():
        available.append(CodingLanguage.JAVASCRIPT.value)
    return available


_ALLOWED_ENV_KEYS = {
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "PATHEXT",
    "NUMBER_OF_PROCESSORS",
    "OS",
    "PROCESSOR_ARCHITECTURE",
}


def _minimal_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() in _ALLOWED_ENV_KEYS}
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return env


def normalize_output(value: str) -> str:
    """Normalise judge output for comparison.

    Judges conventionally ignore trailing spaces on each line and trailing
    blank lines at the end, while still caring about the content of each line.
    """
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in value.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n… truncated ({len(value)} chars total)"


def _kill_process_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
        else:
            proc.kill()
    except Exception:
        # Killing is best-effort; the communicate() below still drains pipes.
        try:
            proc.kill()
        except Exception:
            pass


def _base_result(index: int, case: TestCase, *, status: str, passed: bool) -> CodeTestCaseResult:
    visible = not case.is_hidden
    return CodeTestCaseResult(
        index=index,
        name=case.name,
        is_hidden=case.is_hidden,
        passed=passed,
        status=status,
        input=case.input if visible else None,
        expected_output=case.expected_output if visible else None,
        actual_output=None,
        stderr=None,
        runtime_ms=None,
    )


def _run_case(
    index: int,
    proc_spec: _LanguageSpec,
    workdir: str,
    env: dict[str, str],
    case: TestCase,
    timeout_sec: float,
    max_output_bytes: int,
) -> CodeTestCaseResult:
    result = _base_result(index, case, status="skipped", passed=False)
    started = time.perf_counter()

    try:
        proc = subprocess.Popen(
            proc_spec.command,
            cwd=workdir,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        result.status = "error"
        result.stderr = str(exc)
        return result

    try:
        try:
            stdout_b, stderr_b = proc.communicate(
                input=case.input.encode("utf-8"), timeout=timeout_sec
            )
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc)
            try:
                stdout_b, stderr_b = proc.communicate(timeout=2)
            except Exception:
                stdout_b, stderr_b = b"", b""
            result.status = "timeout"
            result.stderr = "Execution timed out."
            result.runtime_ms = round((time.perf_counter() - started) * 1000, 1)
            return result
        except Exception as exc:
            _kill_process_tree(proc)
            result.status = "error"
            result.stderr = f"Could not run the submission: {exc}"
            result.runtime_ms = round((time.perf_counter() - started) * 1000, 1)
            return result
    finally:
        result.runtime_ms = round((time.perf_counter() - started) * 1000, 1)

    if len(stdout_b) > max_output_bytes or len(stderr_b) > max_output_bytes:
        result.status = "output_limit_exceeded"
        result.actual_output = _truncate(
            normalize_output(stdout_b.decode("utf-8", errors="replace")), 2000
        )
        if not case.is_hidden:
            result.stderr = _truncate(stderr_b.decode("utf-8", errors="replace"), 2000)
        return result

    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        result.status = "runtime_error"
        result.actual_output = _truncate(normalize_output(stdout), 2000)
        if not case.is_hidden:
            result.stderr = _truncate(stderr, 2000) or f"Process exited with code {proc.returncode}."
        return result

    if normalize_output(stdout) == normalize_output(case.expected_output):
        result.passed = True
        result.status = "passed"
        result.actual_output = (
            _truncate(normalize_output(stdout), 2000) if not case.is_hidden else None
        )
        return result

    result.status = "wrong_answer"
    if not case.is_hidden:
        result.actual_output = _truncate(normalize_output(stdout), 2000)
        result.stderr = _truncate(stderr, 2000) or None
    return result


def execute_code(
    language: CodingLanguage | str | None,
    code: str,
    test_cases: list[TestCase],
    *,
    only_visible: bool = False,
) -> CodeRunSummary:
    """Run ``code`` against ``test_cases`` and summarise the outcome.

    Never raises for ordinary compilation/runtime problems — those are
    represented in the returned summary so the API can show per-case feedback.
    Setup problems (disabled runner, unsupported language) are also reported
    in the summary; the caller decides whether that should block grading.
    """
    settings = get_settings()
    cases = [c for c in test_cases if (not only_visible or not c.is_hidden)]

    if not settings.CODE_EXECUTION_ENABLED:
        return CodeRunSummary(
            passed=0,
            total=len(cases),
            all_passed=False,
            status="disabled",
            error="Code execution is disabled on this server.",
        )

    if language is None:
        return CodeRunSummary(
            passed=0,
            total=len(cases),
            all_passed=False,
            status="error",
            error="This coding question has no language configured.",
        )

    try:
        lang = language if isinstance(language, CodingLanguage) else CodingLanguage(language)
    except ValueError:
        return CodeRunSummary(
            passed=0,
            total=len(cases),
            all_passed=False,
            status="unsupported_language",
            error=f"Unsupported coding language: {language!r}.",
        )

    code_bytes = len(code.encode("utf-8"))
    if code_bytes > settings.CODE_EXECUTION_MAX_CODE_BYTES:
        return CodeRunSummary(
            passed=0,
            total=len(cases),
            all_passed=False,
            status="error",
            error=(
                "Submitted code is too large "
                f"({code_bytes} bytes; limit is {settings.CODE_EXECUTION_MAX_CODE_BYTES})."
            ),
        )

    try:
        spec = _language_spec(lang)
    except CodeExecutionError as exc:
        return CodeRunSummary(
            passed=0,
            total=len(cases),
            all_passed=False,
            status="unsupported_language",
            error=str(exc),
        )

    if not cases:
        return CodeRunSummary(
            passed=0,
            total=0,
            all_passed=False,
            status="completed",
            error=None,
        )

    env = _minimal_env()
    results: list[CodeTestCaseResult] = []
    passed = 0
    overall_deadline = time.monotonic() + settings.CODE_EXECUTION_TOTAL_TIMEOUT_SECONDS

    with tempfile.TemporaryDirectory(prefix="placer_code_") as workdir:
        try:
            with open(os.path.join(workdir, spec.filename), "w", encoding="utf-8", newline="\n") as handle:
                handle.write(code)
        except OSError as exc:
            return CodeRunSummary(
                passed=0,
                total=len(cases),
                all_passed=False,
                status="error",
                error=f"Could not prepare the submission: {exc}",
            )

        for index, case in enumerate(cases, start=1):
            remaining = overall_deadline - time.monotonic()
            if remaining <= 0:
                results.append(_base_result(index, case, status="skipped", passed=False))
                continue
            per_case_timeout = max(0.1, min(settings.CODE_EXECUTION_TIMEOUT_SECONDS, remaining))
            try:
                result = _run_case(
                    index,
                    spec,
                    workdir,
                    env,
                    case,
                    per_case_timeout,
                    settings.CODE_EXECUTION_MAX_OUTPUT_BYTES,
                )
            except Exception as exc:  # noqa: BLE001 - one bad case must not kill the run
                result = _base_result(index, case, status="error", passed=False)
                result.stderr = f"Runner error: {exc}"
            results.append(result)
            if result.passed:
                passed += 1

    return CodeRunSummary(
        passed=passed,
        total=len(cases),
        all_passed=passed == len(cases) and len(cases) > 0,
        status="completed",
        results=results,
    )
