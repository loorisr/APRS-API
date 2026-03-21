import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect

import app.aprs_client as client
from app.auth import verify_token

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(client.aprs_loop())
    yield
    task.cancel()


app = FastAPI(title="APRS API", version="1.0.0", lifespan=lifespan)


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "aprs_connected": client.connected,
        "packets_received": client.total_received,
        "packets_buffered": len(client.packets),
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
