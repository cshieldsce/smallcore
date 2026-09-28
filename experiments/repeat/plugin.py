"""pytest plugin: run the existing suite on a candidate's model.

    CANDIDATE=A python -m pytest tests -q -p plugin   (experiments/repeat on PYTHONPATH)

Puts the candidate's CPU and ISA in cpu.CPU and cpu.load_isa before the test
modules import them, so every test that builds a CPU or assembles a program
does so on the candidate. CANDIDATE=base runs `Candidate` itself, the copy of
the step with nothing added, which must pass everything. A candidate that
gives the free opcode or a spare bit a meaning fails the tests that pin them
free, and nothing else: that is the check that it disturbs no program."""

import os

import cpu
from candidates import CANDIDATES, Candidate


def pytest_configure(config):
    name = os.environ.get("CANDIDATE", "base")
    cls = Candidate if name == "base" else CANDIDATES[name]
    cpu.CPU = cls
    cpu.load_isa = lambda path=None: cls.isa()
