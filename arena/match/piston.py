"""
Code execution backend.

Originally used Piston's public endpoint (https://emkc.org/api/v2/piston),
but Piston started 401-ing requests from cloud-hosted IPs (Render, Vercel)
without warning. We now execute Python directly in a subprocess on the API
host, with a hard timeout. For a personal-scale MVP this is fine; do NOT
deploy this to untrusted users without sandboxing.

Falls back to Piston only when explicitly enabled via env (PISTON_API_KEY).
"""
import asyncio
import hashlib
import os
import sys
import tempfile
import time
from typing import Optional

import httpx

PISTON_URL = "https://emkc.org/api/v2/piston"
TIMEOUT_S = 5

# Optional: a hosted Piston API key. If set, we try Piston first.
_PISTON_KEY = os.getenv("PISTON_API_KEY", "")

# Simple in-process cache: {(code,stdin) hash -> result}
_cache: dict[str, dict] = {}


def _hash(code: str, stdin: str) -> str:
    return hashlib.sha256(f"{code}|{stdin}".encode()).hexdigest()


async def _execute_subprocess(code: str, stdin: str) -> dict:
    """Run user Python code in a local subprocess with a hard timeout."""
    # Write code to a unique temp file
    fd, path = tempfile.mkstemp(suffix=".py", prefix="arena_")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)

        t0 = time.perf_counter()
        proc = await asyncio.create_subprocess_exec(
            sys.executable, path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin.encode("utf-8") if stdin else None),
                timeout=TIMEOUT_S,
            )
            runtime_ms = int((time.perf_counter() - t0) * 1000)
            return {
                "stdout": stdout.decode("utf-8", errors="replace").strip(),
                "stderr": stderr.decode("utf-8", errors="replace").strip(),
                "exit_code": proc.returncode if proc.returncode is not None else 1,
                "runtime_ms": runtime_ms,
            }
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return {
                "stdout": "",
                "stderr": f"Execution timed out ({TIMEOUT_S}s)",
                "exit_code": 124,
                "runtime_ms": TIMEOUT_S * 1000,
            }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": f"Subprocess failed: {e}",
            "exit_code": 1,
            "runtime_ms": 0,
        }
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


async def _execute_piston(code: str, stdin: str) -> dict:
    """Hosted Piston (only used if PISTON_API_KEY is set)."""
    headers = {"Authorization": f"Bearer {_PISTON_KEY}"} if _PISTON_KEY else {}
    payload = {
        "language": "python",
        "version": "3.10.0",
        "files": [{"content": code}],
        "stdin": stdin,
        "run_timeout": 5000,
    }
    async with httpx.AsyncClient(timeout=8) as client:
        t0 = time.perf_counter()
        resp = await client.post(f"{PISTON_URL}/execute", json=payload, headers=headers)
        runtime_ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code != 200:
            return {
                "stdout": "",
                "stderr": f"Piston {resp.status_code}: {resp.text[:120]}",
                "exit_code": 1,
                "runtime_ms": runtime_ms,
            }
        data = resp.json()
        run = data.get("run", {})
        return {
            "stdout": run.get("stdout", "").strip(),
            "stderr": run.get("stderr", "").strip(),
            "exit_code": run.get("code", 1),
            "runtime_ms": runtime_ms,
        }


async def execute(code: str, stdin: str = "") -> dict:
    """Run code, return {stdout, stderr, exit_code, runtime_ms}."""
    key = _hash(code, stdin)
    if key in _cache:
        return _cache[key]

    # Prefer subprocess: it's reliable, fast, and free.
    # Use Piston only when explicitly opted in via PISTON_API_KEY.
    if _PISTON_KEY:
        result = await _execute_piston(code, stdin)
        # Fall back to subprocess if Piston rejected us
        if "401" in result.get("stderr", "") or "403" in result.get("stderr", ""):
            result = await _execute_subprocess(code, stdin)
    else:
        result = await _execute_subprocess(code, stdin)

    if result["exit_code"] == 0:
        _cache[key] = result
    return result


async def run_tests(
    user_code: str,
    test_cases: list[dict],
    wrapper_template: str,
) -> dict:
    """Run user_code against a list of test cases. Returns aggregate + per-case."""
    results = []
    passed = 0

    # Run tests concurrently — each is its own subprocess
    tasks = [
        execute(wrapper_template.format(user_code=user_code), tc["input"])
        for tc in test_cases
    ]
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
