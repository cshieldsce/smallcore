import re
from pathlib import Path

import pytest

from wavetrace import Wave

WAVE_DIR = Path(__file__).resolve().parent.parent / "build" / "waves"


@pytest.fixture
def wave(request):
    """A Wave for this test, saved to build/waves/<test bench>/<test name>.svg
    when the test ends (pass or fail). The test bench is the test module,
    e.g. tests/test_uart.py -> build/waves/uart/."""
    w = Wave(title=request.node.name)
    yield w
    if w.signals:
        bench = request.node.module.__name__.removeprefix("test_")
        name = re.sub(r"[^\w.-]+", "_", request.node.name).strip("_")
        w.save(WAVE_DIR / bench / name)
