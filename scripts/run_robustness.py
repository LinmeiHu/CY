from __future__ import annotations

import sys

from cyq_game.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["robustness", *sys.argv[1:]]))
