"""Run the existing model suite on every candidate's model and report.

    python experiments/repeat/suite.py [base A B C D]

Prints one line per candidate: passed, failed, and the failing tests by
function with how many of their cases failed.
The failures a candidate is allowed are the tests that pin the free opcode or
the spare bit it uses and the adversarial sweep's model of a word; any other
failure is a program it disturbed. The counts differ by candidate because the
sweep enumerates the ISA's words: more words, more cases."""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

for name in sys.argv[1:] or ["base", "A", "B", "C", "D"]:
    env = dict(os.environ) if (os := __import__("os")) else {}
    env["CANDIDATE"] = name
    env["PYTHONPATH"] = f"{ROOT / 'sim'}:{ROOT / 'tools'}:{HERE}"
    out = subprocess.run(
        [sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q", "-p", "plugin", "-p", "no:cacheprovider", "--no-header",
         "--tb=no", "-rf", "--ignore", str(ROOT / "tests" / "test_repeat_candidates.py"),
         # This one waits for the halt with no cycle cap, and stops on a JMP, because in the ISA as it is nothing
         # else goes backward. Under B a repeated PULL empties the FIFO and stalls forever; under C a DJNZ loop does.
         "--deselect", "tests/test_adversarial.py::test_shift_out_and_shift_in_never_see_each_others_register"],
        capture_output=True, text=True, env=env, cwd=ROOT,
    ).stdout
    tail = out.strip().splitlines()[-1] if out.strip() else "(no output)"
    failed = re.findall(r"^FAILED (\S+?)(?:\[.*?\])?(?: - .*)?$", out, re.M)
    print(f"{name}: {tail}", flush=True)
    for test in sorted(set(failed)):
        print(f"    {failed.count(test):4} {test}", flush=True)
