"""Owned desktop server lifecycle; shutdown is private stdin EOF, never an HTTP action."""

import sys
from threading import Thread
from typing import TextIO

import uvicorn
from fastapi import FastAPI


def watch_parent(server: uvicorn.Server, stream: TextIO) -> None:
    try:
        while stream.read(1):
            pass
    finally:
        server.should_exit = True


def serve_desktop(app: FastAPI, port: int) -> None:
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, timeout_graceful_shutdown=8)
    )
    Thread(target=watch_parent, args=(server, sys.stdin), daemon=True).start()
    server.run()
