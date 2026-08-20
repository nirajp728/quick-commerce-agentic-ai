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

@tool
def check_inventory(query: str, limit: int = 3) -> str:
    """
    Searches the Quick-Commerce database for a product based on a natural
    language query, using MongoDB Atlas Search's fuzzy text matching
    against name, tags, and category. Stock/availability filtering happens
    in a separate $match stage after $search, since in_stock/stock_qty
    aren't part of the search index mapping. Returns JSON string with
    product details, pricing, and stock availability.
    """
    logger.info(f"Executing check_inventory tool for query: '{query}'")
    collection = get_sync_products_collection()

    pipeline = [
        {
            "$search": {
                "index": settings.PRODUCTS_SEARCH_INDEX_NAME,
                "text": {
                    "query": query,
                    "path": ["name", "tags", "category"],
                    "fuzzy": {"maxEdits": 1, "prefixLength": 2}
                }
            }
        },
        {"$match": {"in_stock": True, "stock_qty": {"$gt": 0}}},
        {"$limit": limit},
        {
            "$project": {
                "_id": 0,
                "product_id": 1,
                "name": 1,
                "price": 1,
                "in_stock": 1,
                "stock_qty": 1,
                "score": {"$meta": "searchScore"}
            }
        }
    ]

    try:
        results = list(collection.aggregate(pipeline))
    except Exception as e:
        logger.error(f"Atlas Search query failed: {e}")
        return json.dumps({"status": "error", "message": "Product search is temporarily unavailable."})

    if not results:
        return json.dumps({"status": "no_matches_found", "query": query})

    formatted_results = [
        {
            "product_id": item["product_id"],
            "name": item["name"],
            "price": item["price"],
            "in_stock": item["in_stock"],
            "stock_qty": item["stock_qty"],
        }
        for item in results
    ]

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
def validate_refund_request(phone_number: str, order_id: str, item_name: str) -> str:
    """
    Validates a refund request against real order data before it's allowed
    to proceed. Checks, in order: (1) does this order exist for this user,
    (2) was this item actually part of that order, (3) has it already been
    refunded. Returns the real matched item name and its real unit price
    from the order if valid, or an explanation of which check failed.
    """
    logger.info(f"Validating refund: phone={phone_number}, order={order_id}, item={item_name}")
    orders_collection = get_sync_db()["orders"]
    order = orders_collection.find_one({"order_id": order_id, "phone_number": phone_number})

    if not order:
        return json.dumps({
            "valid": False,
            "reason": "order_not_found",
            "message": f"No order with ID {order_id} was found for this account."
        })

    order_items = order.get("items", [])
    order_item_names = [i["name"].lower() for i in order_items]
    item_name_lower = item_name.lower()
    item_match = next(
        (n for n in order_item_names if item_name_lower in n or n in item_name_lower),
        None
    )

    if not item_match:
        return json.dumps({
            "valid": False,
            "reason": "item_not_in_order",
            "message": f"\"{item_name}\" was not found in order {order_id}. "
                       f"That order contained: {', '.join(order_item_names)}."
        })

    refunds_collection = get_sync_refunds_collection()
    existing = refunds_collection.find_one({
        "order_id": order_id,
        "item_name": {"$regex": item_match, "$options": "i"}
    })
    if existing:
        return json.dumps({
            "valid": False,
            "reason": "already_refunded",
            "message": f"{item_match} from order {order_id} has already been refunded."
        })

    matched_item = next(i for i in order_items if i["name"].lower() == item_match)
    return json.dumps({
        "valid": True,
        "matched_item_name": matched_item["name"],
        "unit_price": matched_item["price"]
    })

@tool
def process_refund_credit(phone_number: str, amount: float, order_id: str = "", item_name: str = "") -> str:
    """
    Atomically credits the user's wallet balance in MongoDB and logs the
    refund to the refunds collection for history/dedup purposes.
    Call this ONLY after validate_refund_request has confirmed the refund
    is valid.
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