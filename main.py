from __future__ import annotations

import sys
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from life_ops_bot.webhook import app as webhook_app  # noqa: E402

app = Starlette(routes=[Mount("/", app=webhook_app)])
