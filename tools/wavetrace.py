"""Tiny WaveDrom helper for test benches.

Record signals cycle by cycle, or add whole traces at once, then save an SVG:

    w = Wave("uart tx")
    for _ in range(n):
        w.sample(pc=cpu.pc)           # one value per signal per cycle
        cpu.step()
    w.add("pin", cpu.trace)           # or a whole list at once
    w.add("bit", ["start"] * 8 + ...) # strings become labelled bus segments
    w.save("waves/uart.svg")          # also writes uart.json

In pytest, use the `wave` fixture from tests/conftest.py instead; it saves to
build/waves/<test bench>/<test name>.svg automatically, even when the test fails.

Values: 0/1 draw as a single wire, other ints and strings draw as a bus with
the value written in each segment, None draws as unknown (x).
"""

import json
from pathlib import Path


class Wave:
    def __init__(self, title="", clock=True):
        self.title = title
        self.clock = clock
        self.signals = {}  # name -> (values, group)

    def add(self, name, values, group=None):
        """Add a whole signal: one value per cycle."""
        self.signals[name] = (list(values), group)
        return self

    def sample(self, group=None, **values):
        """Append one cycle's value to each named signal."""
        for name, value in values.items():
            self.signals.setdefault(name, ([], group))[0].append(value)
        return self

    @property
    def cycles(self):
        return max((len(v) for v, _ in self.signals.values()), default=0)

    def to_wavejson(self):
        rows = []
        if self.clock:
            rows.append({"name": "clk", "wave": "p" + "." * (self.cycles - 1)})

        groups = {}
        for name, (values, group) in self.signals.items():
            row = _row(name, values)
            if group is None:
                rows.append(row)
            else:
                if group not in groups:
                    groups[group] = [group]
                    rows.append(groups[group])
                groups[group].append(row)

        return {
            "signal": rows,
            "head": {"text": self.title, "tick": 0},
            "config": {"hscale": 1},
        }

    def save(self, path):
        """Write <path>.json and render <path>.svg. Returns the SVG path, or None if wavedrom isn't installed."""
        path = Path(path).with_suffix(".svg")
        path.parent.mkdir(parents=True, exist_ok=True)
        source = json.dumps(self.to_wavejson())
        path.with_suffix(".json").write_text(source)
        try:
            import wavedrom
        except ImportError:
            return None
        drawing = wavedrom.render(source)
        drawing.elements.insert(0, drawing.rect(size=("100%", "100%"), fill="white"))
        drawing.saveas(str(path))
        return path


def _row(name, values):
    is_bit = all(v in (0, 1, None) and not isinstance(v, str) for v in values)
    wave, data = [], []
    prev = object()
    for v in values:
        if v == prev and type(v) is type(prev):
            wave.append(".")
        elif v is None:
            wave.append("x")
        elif is_bit:
            wave.append(str(v))
        else:
            wave.append("=")
            data.append(str(v))
        prev = v
    row = {"name": name, "wave": "".join(wave)}
    if data:
        row["data"] = data
    return row
