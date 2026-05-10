"""Smoke-test the local subprocess executor against all 5 problems."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from arena.match.piston import run_tests
from arena.match.problems import PROBLEMS, WRAPPERS


async def main():
    for prob in PROBLEMS:
        slug = prob["slug"]
        code = prob["reference_solution"]
        cases = prob["test_cases"]
        wrapper = WRAPPERS[slug]

        result = await run_tests(code, cases, wrapper)
        passed = result["tests_passed"]
        total = result["tests_total"]
        ok = "[OK]" if passed == total else "[FAIL]"
        print(f"{ok} {slug}: {passed}/{total} passed")

        for r in result["results"]:
            if not r["passed"]:
                print(f"     FAIL  in={r['input'][:40]!r}")
                print(f"           got={r['actual']!r}")
                print(f"           exp={r['expected']!r}")
                if r["stderr"]:
                    print(f"           stderr={r['stderr'][:120]}")


if __name__ == "__main__":
    asyncio.run(main())
