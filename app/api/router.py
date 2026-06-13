import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_app_id
from app.api.schemas import SmsSendRequest, SmsSendResponse, SmsStatusResponse
from app.db import queries
from app.lookup.operator import record_operator
from app.modem.manager import ModemManager

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/sms/send", response_model=SmsSendResponse)
async def send_sms(
    request: Request,
    body: SmsSendRequest,
    app_id: str = Depends(get_app_id),
) -> SmsSendResponse:
    if await queries.is_phone_blocked(body.phone):
        raise HTTPException(
            status_code=422,
            detail={"error": "number_blacklisted", "phone": body.phone},
        )
    await record_operator(body.phone)
    modem: ModemManager = request.app.state.modem
    message_id = await queries.create_message(app_id, body.phone, body.text)
    await modem.enqueue(message_id, body.phone, body.text)
    return SmsSendResponse(id=message_id, status="pending")


@router.get("/sms/{message_id}", response_model=SmsStatusResponse)
async def get_sms_status(
    message_id: int,
    app_id: str = Depends(get_app_id),
) -> SmsStatusResponse:
    row = await queries.get_message(message_id, app_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return SmsStatusResponse(**dict(row))
