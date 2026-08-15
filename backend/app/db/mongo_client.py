import logging
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from pymongo.database import Database as SyncDatabase
from motor.core import AgnosticDatabase

from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

class MongoDBConnection:
    """
    Holds the database clients to maintain connection pooling
    across the FastAPI application lifecycle.
    """
    async_client: AsyncIOMotorClient = None
    sync_client: MongoClient = None

db_connection = MongoDBConnection()

def connect_to_mongo():
    """
    Initializes database connections.
    Call this on FastAPI startup lifecycle event.
    """
    logger.info("Initializing MongoDB connections...")

    db_connection.async_client = AsyncIOMotorClient(
        settings.MONGODB_URI,
        maxPoolSize=50,
        minPoolSize=10
    )

    db_connection.sync_client = MongoClient(
        settings.MONGODB_URI,
        maxPoolSize=50,
        minPoolSize=10
    )
    logger.info("Successfully connected to MongoDB.")

def close_mongo_connection():
    """
    Closes database connections.
    Call this on FastAPI shutdown lifecycle event.
    """
    logger.info("Closing MongoDB connections...")
    if db_connection.async_client:
        db_connection.async_client.close()
    if db_connection.sync_client:
        db_connection.sync_client.close()
    logger.info("MongoDB connections closed.")

# ------------------------------------------------------------------
# Async Database Access Helpers (For standard web operations)
# ------------------------------------------------------------------
def get_async_db() -> AgnosticDatabase:
    return db_connection.async_client[settings.MONGODB_DB_NAME]

def get_products_collection():
    return get_async_db()["products"]

def get_users_collection():
    return get_async_db()["users"]

def get_orders_collection():
    return get_async_db()["orders"]

def get_refunds_collection():
    return get_async_db()["refunds"]

def get_carts_collection():
    return get_async_db()["carts"]

# ------------------------------------------------------------------
# Sync Database Access Helpers (For AI/LangChain/LangGraph tools)
# ------------------------------------------------------------------
def get_sync_db() -> SyncDatabase:
    return db_connection.sync_client[settings.MONGODB_DB_NAME]

def get_sync_products_collection():
    return get_sync_db()["products"]

def get_sync_users_collection():
    """Returns the sync users collection for wallet credit tools."""
    return get_sync_db()["users"]

def get_sync_policies_collection():
    """Used specifically for LangChain MongoDB Atlas Vector Search."""
    return get_sync_db()["policies"]

def get_sync_refunds_collection():
    """Used for refund history logging and duplicate-refund checks."""
    return get_sync_db()["refunds"]