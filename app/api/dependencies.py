from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import queries

_bearer = HTTPBearer()


async def get_app_id(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> str:
    token = credentials.credentials
    row = await queries.get_app_by_token(token)

    if row is None or not row['is_active']:
        raise HTTPException(status_code=401, detail="Invalid or missing token")

    return row['id']
