"""pytest plugin: run the existing suite on a candidate's model.

    CANDIDATE=AC python -m pytest tests -q -p plugin   (experiments/can on PYTHONPATH)

Puts the candidate's CPU, ISA and decode in cpu.CPU, cpu.load_isa and
cpu.decode before the test modules import them, so every test that builds a
CPU, assembles a program or decodes a word does so on the candidate.
CANDIDATE=base runs `Candidate` itself, the copy of the step with nothing
added, which must pass everything. A candidate that gives rejected words a
meaning fails the tests that pin them rejected, and nothing else: that is
the check that it disturbs no program."""

import os

import cpu
from candidates import CANDIDATES, Candidate


def pytest_configure(config):
    name = os.environ.get("CANDIDATE", "base")
    cls = Candidate if name == "base" else CANDIDATES[name]
    cpu.CPU = cls
    cpu.load_isa = lambda path=None: cls.isa()
    cpu.decode = lambda word, isa=None: cls.decode(word)
