from datetime import datetime

from pydantic import BaseModel


class NotificationItem(BaseModel):
    id: int
    type: str
    message: str
    payload: str | None
    read_at: datetime | None
    related_request_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationsMeta(BaseModel):
    unread_count: int


class NotificationListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[NotificationItem]
    meta: NotificationsMeta


class MarkReadResponse(BaseModel):
    id: int
    read_at: datetime


class MarkAllReadResponse(BaseModel):
    updated: int
