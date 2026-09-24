"""Render docs/*.mmd to SVG with mermaid-cli (mmdc).

Needs Node.js and `npm install -g @mermaid-js/mermaid-cli`. Uses your installed
Chrome instead of puppeteer's own download.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
NODE_DIRS = [r"C:\Program Files\nodejs", os.path.expandvars(r"%APPDATA%\npm")]
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def main():
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(NODE_DIRS + [env["PATH"]])  # in case the shell predates the install
    mmdc = shutil.which("mmdc", path=env["PATH"])
    if not mmdc:
        sys.exit("mmdc not found: npm install -g @mermaid-js/mermaid-cli")
    if "PUPPETEER_EXECUTABLE_PATH" not in env:
        browser = next((b for b in BROWSERS if Path(b).exists()), None)
        if browser:
            env["PUPPETEER_EXECUTABLE_PATH"] = browser

    for src in sorted(DOCS.glob("*.mmd")):
        out = src.with_suffix(".svg")
        subprocess.run([mmdc, "-i", str(src), "-o", str(out), "-b", "white"], env=env, check=True)
        print(f"{src.name} -> {out.name}")


if __name__ == "__main__":
    main()
