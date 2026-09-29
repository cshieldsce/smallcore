"""Run the existing model suite on every candidate's model and report.

    python experiments/can/suite.py [base A B Bc C D AB ABc AC AD]

Prints one line per candidate: passed, failed, and the failing tests by
function with how many of their cases failed. The failures a candidate is
allowed are the tests that pin the rejected words it takes and the
adversarial sweep's model of a word; any other failure is a program it
disturbed. The counts differ by candidate because the sweep enumerates the
ISA's words: more words, more cases. tests/model/test_can_candidates.py and
tests/model/test_repeat_candidates.py are left out: they build the candidates
themselves."""

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

for name in sys.argv[1:] or ["base", "A", "B", "Bc", "C", "D", "AB", "ABc", "AC", "AD"]:
    env = dict(os.environ)
    env["CANDIDATE"] = name
    env["PYTHONPATH"] = f"{ROOT / 'model'}:{ROOT / 'tools'}:{HERE}"
    out = subprocess.run(
        [sys.executable, "-m", "pytest", str(ROOT / "tests" / "model"), "-q", "-p", "plugin", "-p", "no:cacheprovider", "--no-header",
         "--tb=no", "-rf", "--ignore", str(ROOT / "tests" / "model" / "test_can_candidates.py"),
         "--ignore", str(ROOT / "tests" / "model" / "test_repeat_candidates.py")],
        capture_output=True, text=True, env=env, cwd=ROOT,
    ).stdout
    tail = out.strip().splitlines()[-1] if out.strip() else "(no output)"
    failed = re.findall(r"^FAILED (\S+?)(?:\[.*?\])?(?: - .*)?$", out, re.M)
    print(f"{name}: {tail}", flush=True)
    for test in sorted(set(failed)):
        print(f"    {failed.count(test):4} {test}", flush=True)
