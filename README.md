# APRS API

A lightweight Dockerized REST + WebSocket API that connects to the [APRS-IS](https://www.aprs-is.net/) network and exposes APRS packet data to web applications.

Built with **Python / FastAPI** on an Alpine base image (~87 MB image).

![Docker Build](https://github.com/loris/APRS-API/actions/workflows/docker-build.yml/badge.svg)

---

## Features

- Persistent TCP connection to APRS-IS with automatic reconnect and exponential backoff
- Server-side spatial filter configured via environment variable (no client-side filtering)
- In-memory circular buffer of recent packets
- REST endpoints to query buffered packets
- WebSocket endpoint for real-time packet streaming
- Optional token-based authentication (Bearer token or query parameter)

---

## Quick Start

```bash
# 1. Edit docker-compose.yml with your callsign and filter
# 2. Build and start
docker compose up --build
```

The API is available at `http://localhost:8000`.

---

## Configuration

All settings are environment variables defined in `docker-compose.yml`.

| Variable | Default | Description |
|---|---|---|
| `APRS_CALLSIGN` | `N0CALL` | Your amateur radio callsign |
| `APRS_PASSCODE` | `-1` | APRS-IS passcode (`-1` = receive-only) |
| `APRS_SERVER` | `rotate.aprs.net` | APRS-IS server hostname |
| `APRS_PORT` | `14580` | APRS-IS server port |
| `APRS_FILTER` | _(empty)_ | Server-side filter, e.g. `r/48.85/2.35/200` |
| `BUFFER_SIZE` | `500` | Number of packets kept in memory |
| `VALID_TOKENS` | _(empty)_ | Comma-separated API tokens. Empty = auth disabled |

### APRS-IS Filter Format

The filter is applied **server-side** by APRS-IS — only matching packets are sent to the API.

```
r/<lat>/<lon>/<range_km>    # range filter around a point
p/F4,TK                     # prefix filter (callsign prefixes)
```

See the full filter reference at: https://www.aprs-is.net/javAPRSFilter.aspx

---

## API Reference

### `GET /health`

Returns connection status, packet counters, and active configuration. No authentication required.

```json
{
  "status": "ok",
  "aprs_connected": true,
  "packets_received": 1042,
  "packets_buffered": 500,
  "config": {
    "server": "rotate.aprs.net:14580",
    "filter": "r/48.85/2.35/200",
    "buffer_size": 500
  }
}
```

---

### `GET /packets`

Returns recent packets from the buffer.

**Query parameters:**

| Parameter | Default | Description |
|---|---|---|
| `limit` | `100` | Maximum number of packets to return |
| `callsign` | _(none)_ | Filter by callsign (case-insensitive) |

**Example:**
```
GET /packets?limit=50&callsign=F4ABC
Authorization: Bearer yourtoken
```

**Response:**
```json
[
  {
    "callsign": "F4ABC",
    "path": "WIDE1-1,WIDE2-1",
    "payload": "!4830.00N/00215.00E>",
    "raw": "F4ABC>APRS,WIDE1-1,WIDE2-1:!4830.00N/00215.00E>",
    "timestamp": "2026-03-21T10:00:00+00:00"
  }
]
```

---

### `GET /packets/{callsign}`

Returns packets for a specific callsign.

**Query parameters:**

| Parameter | Default | Description |
|---|---|---|
| `limit` | `50` | Maximum number of packets to return |

**Example:**
```
GET /packets/F4ABC?limit=10
Authorization: Bearer yourtoken
```

---

### `WS /ws`

WebSocket endpoint for real-time packet streaming. Each message is a JSON-encoded packet (same format as REST responses).

**Authentication:** pass the token as a query parameter.

```
ws://localhost:8000/ws?api_key=yourtoken
```

**JavaScript example:**
```javascript
const ws = new WebSocket("ws://localhost:8000/ws?api_key=yourtoken");
ws.onmessage = (event) => {
  const packet = JSON.parse(event.data);
  console.log(packet.callsign, packet.payload);
};
```

---

## Authentication

When `VALID_TOKENS` is set, all endpoints (except `/health`) require a valid token.

**Via header:**
```
Authorization: Bearer yourtoken
```

**Via query parameter:**
```
GET /packets?api_key=yourtoken
WS  /ws?api_key=yourtoken
```

To add or rotate tokens, update `VALID_TOKENS` in `docker-compose.yml` and restart the container.
To disable authentication entirely, leave `VALID_TOKENS` empty.

---

## Project Structure

```
aprs_api/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── app/
    ├── config.py       # environment variable settings
    ├── auth.py         # token authentication dependency
    ├── aprs_client.py  # async TCP connection to APRS-IS
    └── main.py         # FastAPI application and endpoints
```
