import os

APRS_SERVER = os.getenv("APRS_SERVER", "rotate.aprs.net")
APRS_PORT = int(os.getenv("APRS_PORT", "14580"))
APRS_CALLSIGN = os.getenv("APRS_CALLSIGN", "N0CALL")
APRS_PASSCODE = os.getenv("APRS_PASSCODE", "-1")
APRS_FILTER = os.getenv("APRS_FILTER", "")

BUFFER_SIZE = int(os.getenv("BUFFER_SIZE", "500"))

# 0 = always connected; N = connect on first request, disconnect after N minutes of inactivity
SMART_CONNECT = int(os.getenv("SMART_CONNECT", "0"))

VALID_TOKENS: set[str] = {
    t.strip()
    for t in os.getenv("VALID_TOKENS", "").split(",")
    if t.strip()
}
