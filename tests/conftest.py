import re
from pathlib import Path

import pytest

from wavetrace import Wave

WAVE_DIR = Path(__file__).resolve().parent.parent / "build" / "waves"


@pytest.fixture
def wave(request):
    """A Wave for this test, saved to build/waves/<test name>.svg when the test ends (pass or fail)."""
    w = Wave(title=request.node.name)
    yield w
    if w.signals:
        name = re.sub(r"[^\w.-]+", "_", request.node.name).strip("_")
        w.save(WAVE_DIR / name)
