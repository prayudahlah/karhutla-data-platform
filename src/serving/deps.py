"""Dependency FastAPI yang dipakai semua router."""

from __future__ import annotations

from fastapi import Request

from serving.db import GoldStore
from serving.settings import Settings


def get_store(request: Request) -> GoldStore:
    return request.app.state.store


def get_settings(request: Request) -> Settings:
    return request.app.state.settings
