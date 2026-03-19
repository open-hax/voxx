from __future__ import annotations

import uvicorn

from .app import app
from .config import get_settings


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port)
