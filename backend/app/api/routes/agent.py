from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from app.core import security
from app.services import agent_service

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
router = APIRouter(prefix="/api/collections", tags=["collections"])


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class ReminderBody(BaseModel):
    customer_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,20}$")
    force: bool = False


class ReplyBody(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    confirm: bool = False


@auth_router.post("/login")
def login(body: LoginBody, request: Request):
    return security.login(body.username, body.password, request.client.host if request.client else "unknown")


@router.post("/reminders")
def send_reminders(body: ReminderBody = ReminderBody()):
    return agent_service.send_reminders(body.customer_id, body.force)


@router.post("/inbox/check")
def check_inbox():
    return agent_service.check_inbox()


@router.get("/conversations")
def list_conversations():
    return agent_service.list_conversations()


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str):
    return agent_service.get_conversation(conversation_id)


@router.get("/attention")
def list_attention():
    return agent_service.list_attention()


@router.post("/attention/{item_id}/send")
def send_attention_reply(item_id: str, body: ReplyBody):
    return agent_service.send_attention_reply(item_id, body.body, body.confirm)


@router.post("/attention/{item_id}/dismiss")
def dismiss_attention(item_id: str):
    return agent_service.dismiss_attention(item_id)