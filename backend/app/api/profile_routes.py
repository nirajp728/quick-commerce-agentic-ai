import logging
from fastapi import APIRouter, HTTPException
from backend.app.config import settings
from backend.app.db.mongo_client import get_users_collection, get_orders_collection, get_refunds_collection
from backend.app.graph.master_graph import get_compiled_graph_with_checkpointer

logger = logging.getLogger(settings.APP_NAME)
router = APIRouter()

@router.get("/profile/{phone_number:path}")
async def get_profile(phone_number: str):
    users = get_users_collection()
    user = await users.find_one({"phone_number": phone_number}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    orders = [doc async for doc in get_orders_collection().find({"phone_number": phone_number}, {"_id": 0}).sort("created_at", -1).limit(10)]
    refunds = [doc async for doc in get_refunds_collection().find({"phone_number": phone_number}, {"_id": 0}).sort("processed_at", -1).limit(10)]

    return {"user": user, "orders": orders, "refunds": refunds}

@router.get("/thread_state/{thread_id:path}")
async def get_thread_state(thread_id: str):
    """Lets the frontend poll a thread's current handoff status and recent
    messages — used so a paused web chat can pick up admin replies."""
    graph = get_compiled_graph_with_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}
    state = graph.get_state(config)
    if not state:
        return {"is_handed_off": False, "messages": []}

    messages = state.values.get("messages", [])
    return {
        "is_handed_off": state.values.get("is_handed_off", False),
        "messages": [{"role": m.type, "content": m.content} for m in messages[-10:]],
    }

@router.get("/active_handoffs")
async def get_active_handoffs():
    """
    Lists threads currently paused for human handoff, so a newly-connected
    admin dashboard can catch up on escalations that happened before it
    connected — live broadcast alone only reaches admins already watching.
    """
    from backend.app.graph.master_graph import get_compiled_graph_with_checkpointer
    graph = get_compiled_graph_with_checkpointer()

    active = []
    # MongoDBSaver checkpoints are stored per-thread; list distinct thread_ids
    # from the checkpoints collection and check each one's current state.
    checkpoints_collection = graph.checkpointer.checkpoints_collection
    thread_ids = checkpoints_collection.distinct("thread_id")

    for thread_id in thread_ids:
        config = {"configurable": {"thread_id": thread_id}}
        state = graph.get_state(config)
        if state and state.values.get("is_handed_off"):
            messages = state.values.get("messages", [])
            last_user_msg = next((m.content for m in reversed(messages) if m.type == "human"), "(no message)")
            active.append({
                "thread_id": thread_id,
                "issue": last_user_msg,
                "sentiment": state.values.get("sentiment_score", 0.0),
            })

    return {"active_handoffs": active}