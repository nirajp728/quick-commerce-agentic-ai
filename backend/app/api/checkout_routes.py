import logging
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pymongo import ReturnDocument

from backend.app.config import settings
from backend.app.db.mongo_client import get_users_collection, get_orders_collection

logger = logging.getLogger(settings.APP_NAME)
router = APIRouter()

class CheckoutRequest(BaseModel):
    phone_number: str
    items: List[Dict[str, Any]]

class CheckoutResponse(BaseModel):
    order_id: str
    new_balance: float

@router.post("/checkout", response_model=CheckoutResponse)
async def checkout(request: CheckoutRequest):
    total = sum(item.get("price", 0) * item.get("qty", 1) for item in request.items)
    users = get_users_collection()

    # Atomic: only deduct if the balance is still sufficient at write time
    updated_user = await users.find_one_and_update(
        {"phone_number": request.phone_number, "wallet_balance": {"$gte": total}},
        {"$inc": {"wallet_balance": -total}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated_user:
        raise HTTPException(status_code=400, detail="User not found or insufficient wallet balance")

    order_id = f"ORD{uuid.uuid4().hex[:8].upper()}"
    await get_orders_collection().insert_one({
        "order_id": order_id,
        "phone_number": request.phone_number,
        "items": request.items,
        "total": total,
        "status": "Placed",
        "created_at": datetime.now(timezone.utc),
    })

    return CheckoutResponse(order_id=order_id, new_balance=updated_user["wallet_balance"])