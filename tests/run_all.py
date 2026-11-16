"""Runs every test file, each in its own fresh Python, and prints one summary.

    python tests/run_all.py            (on Windows, with Eris's packages installed)
    python tests/run_all.py --quick    (skips the real-window test)

Eris's keyboard hooks need a screen; on Linux without one the tests run under xvfb-run.
Windows always has one."""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = ["test_parts.py", "test_steps.py", "test_brains.py", "test_lab.py", "test_window.py"]


def command(name):
    cmd = [sys.executable, str(HERE / name)]
    if sys.platform != "linux" or os.environ.get("DISPLAY"):
        return cmd
    if shutil.which("xvfb-run"):
        return ["xvfb-run", "-a", "-s", "-screen 0 1440x900x24", *cmd]
    return None     # no screen at all: skipped


def main():
    quick = "--quick" in sys.argv
    results = []
    for name in FILES:
        cmd = None if quick and name == "test_window.py" else command(name)
        if cmd is None:
            results.append((name, "skipped", 0))
            continue
        start = time.time()
        proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=300)
        took = time.time() - start
        failed = proc.returncode != 0
        if failed:      # show what went wrong, quietly otherwise
            print(proc.stdout[-4000:] + proc.stderr[-4000:])
        results.append((name, "FAILED" if failed else "passed", took))
    print()
    for name, result, took in results:
        print(f"  {result:8} {name:16} {took:5.1f}s")
    bad = [n for n, r, _ in results if r == "FAILED"]
    print("\nAll tests passed." if not bad else f"\n{len(bad)} file(s) failed: {', '.join(bad)}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
