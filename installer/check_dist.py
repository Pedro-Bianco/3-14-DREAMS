"""The packaged app must not carry the build machine's user folder (it names the person who built
it). A copied __pycache__ did, unnoticed for several versions. Exit code 1 lists the files."""

import mmap
import os
import sys
from pathlib import Path


def main(folder: str) -> int:
    home = os.path.expanduser("~")
    probes = {v.encode(enc) for v in (home, home.replace("\\", "/")) for enc in ("utf-8", "utf-16-le")}
    found = []
    for path in Path(folder).rglob("*"):
        if not path.is_file() or path.stat().st_size == 0:
            continue
        with open(path, "rb") as file, mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as data:
            if any(data.find(probe) != -1 for probe in probes):
                found.append(path)
    for path in found:
        print(f"build machine path inside: {path}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
