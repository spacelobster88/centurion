"""Standalone entrypoint for running Centurion as a service.

Usage::

    python -m centurion --host 0.0.0.0 --port 8100
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI

from centurion.api.router import health_router, router
from centurion.api.websocket import websocket_endpoint
from centurion.config import CenturionConfig
from centurion.core.engine import Centurion


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = CenturionConfig()
    engine = Centurion(config=config)
    app.state.centurion = engine
    yield
    await engine.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Centurion AI Agent Orchestration Engine"
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()

    app = FastAPI(title="Centurion", version="0.1.0", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(router)
    app.add_api_websocket_route("/api/centurion/events", websocket_endpoint)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
