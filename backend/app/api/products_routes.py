import logging
from typing import Optional
from fastapi import APIRouter
from backend.app.config import settings
from backend.app.db.mongo_client import get_products_collection

logger = logging.getLogger(settings.APP_NAME)
router = APIRouter()

@router.get("/products")
async def list_products(category: Optional[str] = None, limit: int = 20):
    query = {"in_stock": True, "stock_qty": {"$gt": 0}}
    if category:
        query["category"] = {"$regex": category, "$options": "i"}

    cursor = get_products_collection().find(query, {"_id": 0}).limit(limit)
    products = [doc async for doc in cursor]
    return {"products": products}