from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from life_ops_bot.webhook import app  # noqa: E402, F401
