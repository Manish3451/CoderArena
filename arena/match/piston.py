"""
Piston API wrapper.
Public endpoint: https://emkc.org/api/v2/piston
"""
import asyncio
import hashlib
import json
import time
from typing import Optional

import httpx

PISTON_URL = "https://emkc.org/api/v2/piston"
TIMEOUT_S = 8
PYTHON_VERSION = "3.10.0"

# Simple in-process cache: {code_hash: result} — cleared on restart (fine for free tier)
_cache: dict[str, dict] = {}


def _hash(code: str, stdin: str) -> str:
    return hashlib.sha256(f"{code}|{stdin}".encode()).hexdigest()


async def execute(code: str, stdin: str = "") -> dict:
    """
    Run Python code via Piston. Returns:
    {stdout, stderr, exit_code, runtime_ms}
    """
    key = _hash(code, stdin)
    if key in _cache:
        return _cache[key]

    payload = {
        "language": "python",
        "version": PYTHON_VERSION,
        "files": [{"content": code}],
        "stdin": stdin,
        "run_timeout": 5000,
    }

    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        for attempt in range(2):
            try:
                t0 = time.perf_counter()
                resp = await client.post(f"{PISTON_URL}/execute", json=payload)
                runtime_ms = int((time.perf_counter() - t0) * 1000)

                if resp.status_code == 429:
                    if attempt == 0:
                        await asyncio.sleep(1)
                        continue
                    return {"stdout": "", "stderr": "Rate limited by sandbox", "exit_code": 1, "runtime_ms": 0}

                resp.raise_for_status()
                data = resp.json()
                run = data.get("run", {})
                result = {
                    "stdout": run.get("stdout", "").strip(),
                    "stderr": run.get("stderr", "").strip(),
                    "exit_code": run.get("code", 1),
                    "runtime_ms": runtime_ms,
                }
                # Only cache successful runs
                if result["exit_code"] == 0:
                    _cache[key] = result
                return result

            except httpx.TimeoutException:
                return {"stdout": "", "stderr": "Execution timed out (8s)", "exit_code": 1, "runtime_ms": 8000}
            except Exception as e:
                return {"stdout": "", "stderr": str(e), "exit_code": 1, "runtime_ms": 0}

    return {"stdout": "", "stderr": "Piston unavailable", "exit_code": 1, "runtime_ms": 0}


async def run_tests(
    user_code: str,
    test_cases: list[dict],
    wrapper_template: str,
) -> dict:
    """
    Run user_code against a list of test cases.
    Returns {tests_passed, tests_total, results: [{input, expected, actual, passed}]}
    """
    results = []
    passed = 0

    tasks = []
    for tc in test_cases:
        wrapped = wrapper_template.format(user_code=user_code)
        tasks.append(execute(wrapped, tc["input"]))

    outputs = await asyncio.gather(*tasks)

    for tc, out in zip(test_cases, outputs):
        actual = out["stdout"].strip()
        expected = tc["expected"].strip()
        ok = actual == expected
        if ok:
            passed += 1
        results.append({
            "input": tc["input"],
            "expected": expected,
            "actual": actual,
            "passed": ok,
            "stderr": out["stderr"],
            "exit_code": out["exit_code"],
        })

    return {
        "tests_passed": passed,
        "tests_total": len(test_cases),
        "results": results,
    }
