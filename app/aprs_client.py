import asyncio
import logging
import re
from collections import deque
from datetime import datetime, timezone

from aprspy import APRS

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


def _packet_to_dict(p) -> dict:
    """Extract known fields from an aprspy packet object into a flat dict."""
    d: dict = {}
    for attr in (
        "latitude", "longitude", "altitude", "speed", "course",
        "comment", "symbol", "symbol_table",
        "addressee", "message", "message_id",
        "weather",
    ):
        val = getattr(p, attr, None)
        if val is not None:
            d[attr] = val
    return d


def _parse_object_payload(payload: str) -> dict:
    """Parse APRS object packet payload (starts with ';') into enriched fields."""
    # Format: ;NNNNNNNNN*DDHHMMzDDMM.mmNSYDDDMM.mmEWsycomment
    if len(payload) < 19:
        return {}
    obj_name = payload[1:10].strip()
    # payload[10] is '*' (live) or '_' (killed)
    pos = payload[18:]  # skip ';' + 9-char name + status char + 7-char timestamp
    lat_m = re.match(r"(\d{2})(\d{2}\.\d+)([NS])", pos)
    if not lat_m:
        return {"object_name": obj_name}
    lat = int(lat_m.group(1)) + float(lat_m.group(2)) / 60.0
    if lat_m.group(3) == "S":
        lat = -lat
    pos = pos[lat_m.end():]
    sym_table = pos[0] if pos else "/"
    pos = pos[1:]
    lon_m = re.match(r"(\d{3})(\d{2}\.\d+)([EW])", pos)
    if not lon_m:
        return {"object_name": obj_name, "latitude": round(lat, 6)}
    lon = int(lon_m.group(1)) + float(lon_m.group(2)) / 60.0
    if lon_m.group(3) == "W":
        lon = -lon
    pos = pos[lon_m.end():]
    result = {
        "object_name": obj_name,
        "latitude": round(lat, 6),
        "longitude": round(lon, 6),
        "symbol_table": sym_table,
        "symbol": pos[0] if pos else "",
        "comment": pos[1:] if len(pos) > 1 else "",
    }
    if payload[10] == "_":
        result["object_killed"] = True
    return result


def parse_packet(raw: str) -> dict | None:
    """Parse a raw APRS-IS line into a dict, enriched via aprspy."""
    try:
        p = APRS.parse(raw)
    except Exception:
        p = None

    # Fall back to basic header splitting if aprspy fails
    if p is None:
        try:
            if ":" not in raw or ">" not in raw:
                return None
            header, payload = raw.split(":", 1)
            callsign, path = header.split(">", 1)
            packet = {
                "callsign": callsign.strip(),
                "path": path.strip(),
                "payload": payload.strip(),
                "raw": raw,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if payload.startswith(";"):
                parsed = _parse_object_payload(payload)
                if parsed:
                    packet["type"] = "object"
                    packet.update(parsed)
            return packet
        except Exception:
            return None

    packet = {
        "callsign": str(p.source),
        "destination": str(p.destination),
        "path": str(p.path),
        "type": type(p).__name__.replace("Packet", "").lower(),
        "raw": raw,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    packet.update(_packet_to_dict(p))
    # aprspy may parse the header but miss position on object packets
    if "latitude" not in packet and ":" in raw:
        payload = raw.split(":", 1)[1]
        if payload.startswith(";"):
            parsed = _parse_object_payload(payload)
            if parsed:
                packet.setdefault("type", "object")
                for k, v in parsed.items():
                    packet.setdefault(k, v)
    return packet


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
