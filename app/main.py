import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, WebSocket, WebSocketDisconnect

import app.aprs_client as client
from app.auth import verify_token
from app.config import APRS_FILTER, APRS_SERVER, APRS_PORT, BUFFER_SIZE, SMART_CONNECT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(client.aprs_loop())
    yield
    task.cancel()


app = FastAPI(title="APRS API", version="1.0.0", lifespan=lifespan)


# ── Smart-connect middleware ──────────────────────────────────────────────────

if SMART_CONNECT:
    @app.middleware("http")
    async def _activity_middleware(request: Request, call_next):
        client.notify_activity()
        return await call_next(request)


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "aprs_connected": client.connected,
        "packets_received": client.total_received,
        "packets_buffered": len(client.packets),
        "config": {
            "server": f"{APRS_SERVER}:{APRS_PORT}",
            "filter": APRS_FILTER or None,
            "buffer_size": BUFFER_SIZE,
            "smart_connect": SMART_CONNECT,
        },
    }


@app.get("/packets", dependencies=[Depends(verify_token)])
def get_packets(limit: int = 100, callsign: str | None = None):
    """Return recent packets from the buffer (newest last)."""
    result = list(client.packets)
    if callsign:
        result = [p for p in result if p["callsign"].upper() == callsign.upper()]
    return result[-limit:]


@app.get("/packets/{callsign}", dependencies=[Depends(verify_token)])
def get_packets_by_callsign(callsign: str, limit: int = 50):
    result = [
        p for p in client.packets
        if p["callsign"].upper() == callsign.upper()
    ]
    return result[-limit:]


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    # Token auth via query param or Authorization header
    token = ws.query_params.get("api_key") or ws.headers.get("authorization", "")
    token = token.removeprefix("Bearer ").strip()

    from app.config import VALID_TOKENS
    if VALID_TOKENS and token not in VALID_TOKENS:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()

    # In smart-connect mode, a WebSocket connection counts as activity
    if SMART_CONNECT:
        client.notify_activity()

    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    client.subscribers.append(queue)
    try:
        while True:
            packet = await queue.get()
            await ws.send_text(json.dumps(packet))
    except WebSocketDisconnect:
        pass
    finally:
        try:
            client.subscribers.remove(queue)
        except ValueError:
            pass
