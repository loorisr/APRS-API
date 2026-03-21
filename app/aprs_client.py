import asyncio
import logging
from collections import deque
from datetime import datetime, timezone

from app.config import (
    APRS_CALLSIGN,
    APRS_FILTER,
    APRS_PASSCODE,
    APRS_PORT,
    APRS_SERVER,
    BUFFER_SIZE,
)

log = logging.getLogger(__name__)

# Shared state
packets: deque[dict] = deque(maxlen=BUFFER_SIZE)
subscribers: list[asyncio.Queue] = []
connected = False
total_received = 0


def parse_packet(raw: str) -> dict | None:
    """Parse a raw APRS-IS line into a dict."""
    try:
        # Format: CALLSIGN>PATH:payload  (PATH may contain multiple fields)
        if ":" not in raw:
            return None
        header, payload = raw.split(":", 1)
        if ">" not in header:
            return None
        callsign, path = header.split(">", 1)
        return {
            "callsign": callsign.strip(),
            "path": path.strip(),
            "payload": payload.strip(),
            "raw": raw,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return None


async def broadcast(packet: dict) -> None:
    dead = []
    for q in subscribers:
        try:
            q.put_nowait(packet)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        subscribers.remove(q)


async def aprs_loop() -> None:
    global connected, total_received
    retry_delay = 5

    login = f"user {APRS_CALLSIGN} pass {APRS_PASSCODE} vers aprs-api 1.0"
    if APRS_FILTER:
        login += f" filter {APRS_FILTER}"
    login += "\r\n"

    while True:
        try:
            log.info("Connecting to %s:%d …", APRS_SERVER, APRS_PORT)
            reader, writer = await asyncio.open_connection(APRS_SERVER, APRS_PORT)
            writer.write(login.encode())
            await writer.drain()
            connected = True
            log.info("Connected to APRS-IS")
            retry_delay = 5  # reset backoff on success

            while True:
                line = await reader.readline()
                if not line:
                    break
                raw = line.decode("utf-8", errors="replace").rstrip("\r\n")
                if raw.startswith("#"):
                    continue  # server comment / heartbeat
                packet = parse_packet(raw)
                if packet:
                    packets.append(packet)
                    total_received += 1
                    await broadcast(packet)

        except Exception as e:
            log.warning("APRS-IS connection error: %s", e)
        finally:
            connected = False
            log.info("Reconnecting in %ds …", retry_delay)
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)
