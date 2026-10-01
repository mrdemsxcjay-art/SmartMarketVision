"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request, WebSocket

from app.container import Container, container as default_container


def _from_state(app) -> Container | None:
    return getattr(app.state, "container", None)


def get_container(request: Request) -> Container:
    """Container for HTTP routes."""
    return _from_state(request.app) or default_container


def get_container_ws(websocket: WebSocket) -> Container:
    """Container for WebSocket routes."""
    return _from_state(websocket.app) or default_container
