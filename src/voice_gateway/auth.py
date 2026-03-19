from __future__ import annotations

from fastapi import Request

from .config import Settings


def extract_api_key(request: Request) -> str:
    auth_header = str(request.headers.get("authorization", "") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()

    for header_name in ("x-api-key", "api-key", "xi-api-key"):
        value = str(request.headers.get(header_name, "") or "").strip()
        if value:
            return value

    token_query = str(request.query_params.get("token", "") or "").strip()
    return token_query


def is_authorized(request: Request, settings: Settings) -> bool:
    if not settings.api_key:
        return True
    return extract_api_key(request) == settings.api_key
