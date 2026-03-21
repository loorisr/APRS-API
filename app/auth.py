from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, APIKeyQuery

from app.config import VALID_TOKENS

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)
api_key_query = APIKeyQuery(name="api_key", auto_error=False)


def verify_token(
    header: str | None = Security(api_key_header),
    query: str | None = Security(api_key_query),
) -> str:
    if not VALID_TOKENS:
        # No tokens configured → auth disabled
        return "anonymous"

    token = query
    if header:
        # Strip "Bearer " prefix if present
        token = header.removeprefix("Bearer ").strip()

    if token and token in VALID_TOKENS:
        return token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API token",
    )
