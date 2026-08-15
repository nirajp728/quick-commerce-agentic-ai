import difflib
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
from langchain_core.tools import tool
from pymongo import ReturnDocument

from backend.app.config import settings
from backend.app.db.mongo_client import (
    get_sync_db,
    get_sync_products_collection,
    get_sync_users_collection,
    get_sync_refunds_collection,
)

logger = logging.getLogger(settings.APP_NAME)

def _correct_typo(query: str, collection) -> str:
    """
    Builds the real vocabulary (product name words + tags + categories)
    from the catalog and corrects the query against it if there's a close
    match. This only fixes typos against products that actually exist —
    it can't invent matches for products that aren't in the catalog at all.
    """
    vocabulary = set()
    for doc in collection.find({}, {"name": 1, "tags": 1, "category": 1}):
        vocabulary.update(w.lower() for w in doc.get("name", "").split())
        vocabulary.update(t.lower() for t in doc.get("tags", []))
        if doc.get("category"):
            vocabulary.add(doc["category"].lower())

    matches = difflib.get_close_matches(query.lower(), vocabulary, n=1, cutoff=0.6)
    return matches[0] if matches else query

@tool
def check_inventory(query: str, limit: int = 3) -> str:
    """
    Searches the Quick-Commerce database for a product based on a natural
    language query. Corrects likely typos against real catalog terms first,
    then builds an exact MongoDB query against name/tags/category.
    Returns JSON string with product details, pricing, and stock availability.
    """
    logger.info(f"Executing check_inventory tool for query: '{query}'")
    collection = get_sync_products_collection()

    corrected = _correct_typo(query, collection)
    if corrected != query.lower():
        logger.info(f"check_inventory: corrected '{query}' -> '{corrected}'")

    search_filter = {
        "in_stock": True,
        "stock_qty": {"$gt": 0},
        "$or": [
            {"name": {"$regex": corrected, "$options": "i"}},
            {"tags": {"$regex": corrected, "$options": "i"}},
            {"category": {"$regex": corrected, "$options": "i"}}
        ]
    }

    results = list(collection.find(search_filter).limit(limit))

    if not results:
        return json.dumps({"status": "no_matches_found", "query": query})

    formatted_results = []
    for item in results:
        formatted_results.append({
            "product_id": item["product_id"],
            "name": item["name"],
            "price": item["price"],
            "in_stock": item["in_stock"],
            "stock_qty": item["stock_qty"]
        })

    return json.dumps({"status": "success", "items": formatted_results})

@tool
def check_order_history(phone_number: str, order_id: str = "", status: str = "") -> str:
    """
    Queries the orders collection for a user's order history. Schema:
    order_id (str), phone_number (str), items (list of {name, qty, price}),
    total (float), status (str, e.g. 'Placed'), created_at (datetime).
    Filters by phone_number always; order_id and status are optional narrowers.
    Returns JSON string with the user's most recent orders.
    """
    logger.info(f"Executing check_order_history for {phone_number}")
    collection = get_sync_db()["orders"]

    query_filter = {"phone_number": phone_number}
    if order_id:
        query_filter["order_id"] = order_id
    if status:
        query_filter["status"] = {"$regex": status, "$options": "i"}

    results = list(
        collection.find(query_filter, {"_id": 0})
        .sort("created_at", -1)
        .limit(10)
    )

    if not results:
        return json.dumps({"status": "no_orders_found"})

    for r in results:
        if "created_at" in r:
            r["created_at"] = str(r["created_at"])

    return json.dumps({"status": "success", "orders": results})

@tool
def check_existing_refund(order_id: str, item_name: str) -> str:
    """
    Checks whether this order/item combination has already been refunded,
    to prevent crediting the same refund twice.
    """
    collection = get_sync_refunds_collection()
    existing = collection.find_one({"order_id": order_id, "item_name": item_name})
    return json.dumps({"already_refunded": existing is not None})

@tool
def process_refund_credit(phone_number: str, amount: float, order_id: str = "", item_name: str = "") -> str:
    """
    Atomically credits the user's wallet balance in MongoDB and logs the
    refund to the refunds collection for history/dedup purposes.
    Call this ONLY when all refund slots have been validated.
    """
    logger.info(f"Processing refund of ₹{amount} for user: {phone_number}")
    users_collection = get_sync_users_collection()

    updated_user = users_collection.find_one_and_update(
        {"phone_number": phone_number},
        {"$inc": {"wallet_balance": amount}},
        return_document=ReturnDocument.AFTER
    )

    if not updated_user:
        return json.dumps({"status": "error", "message": "User not found."})

    get_sync_refunds_collection().insert_one({
        "phone_number": phone_number,
        "order_id": order_id,
        "item_name": item_name,
        "amount": amount,
        "processed_at": datetime.now(timezone.utc),
    })

    return json.dumps({
        "status": "success",
        "new_balance": updated_user["wallet_balance"]
    })