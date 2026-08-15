import logging
from pymongo import MongoClient
from sentence_transformers import SentenceTransformer
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)


def seed_database():
    """
    Seeds MongoDB collections with initial mock data:
    1. Products (for inventory and recipe builder / discovery graph)
    2. Users (for customer profiles and loyalty wallets)
    3. Policies (vectorized chunks for QA Self-RAG semantic search)
    """
    logger.info("Starting database seeding process...")
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.MONGODB_DB_NAME]

    # 1. Seed Products Collection
    products_col = db["products"]
    products_col.drop()
    
    mock_products = [
        {"product_id": "P001", "name": "Poultry - Raw Chicken Breast (500g)", "category": "Meat", "price": 180, "stock_qty": 25, "in_stock": True, "tags": ["chicken", "meat", "protein", "butter chicken"]},
        {"product_id": "P002", "name": "Amul Butter (500g)", "category": "Dairy", "price": 275, "stock_qty": 50, "in_stock": True, "tags": ["butter", "dairy", "butter chicken"]},
        {"product_id": "P003", "name": "Amul Heavy Whipping Cream (250ml)", "category": "Dairy", "price": 130, "stock_qty": 30, "in_stock": True, "tags": ["cream", "dairy", "heavy cream", "butter chicken"]},
        {"product_id": "P004", "name": "Organic Red Tomato Puree (200g)", "category": "Pantry", "price": 65, "stock_qty": 100, "in_stock": True, "tags": ["tomatoes", "tomato puree", "pantry", "butter chicken"]},
        {"product_id": "P005", "name": "Everest Garam Masala (100g)", "category": "Spices", "price": 75, "stock_qty": 40, "in_stock": True, "tags": ["spices", "garam masala", "butter chicken"]},
        {"product_id": "P006", "name": "Ginger Garlic Paste (200g)", "category": "Pantry", "price": 55, "stock_qty": 60, "in_stock": True, "tags": ["ginger garlic", "pantry", "butter chicken"]},
        {"product_id": "P007", "name": "Lays Classic Salted Chips (50g)", "category": "Snacks", "price": 20, "stock_qty": 200, "in_stock": True, "tags": ["snacks", "chips", "under ₹100"]},
        {"product_id": "P008", "name": "Kurkure Masala Munch (90g)", "category": "Snacks", "price": 30, "stock_qty": 150, "in_stock": True, "tags": ["snacks", "chips", "under ₹100"]},
        {"product_id": "P009", "name": "Cadbury Dairy Milk Silk (150g)", "category": "Snacks", "price": 175, "stock_qty": 10, "in_stock": True, "tags": ["chocolate", "snacks"]}
    ]
    products_col.insert_many(mock_products)
    logger.info("Seeded %d products into collection.", len(mock_products))

    # 2. Seed Users Collection
    users_col = db["users"]
    users_col.drop()
    
    mock_users = [
        {
            "phone_number": "whatsapp:+919876543210",
            "name": "Aarav Sharma",
            "email": "aarav.sharma@example.com",
            "wallet_balance": 450.00,
            "addresses": ["Flat 402, Sunshine Apartments, Mumbai"],
            "preferences": {"dietary": "non-vegetarian", "allergies": ["peanuts"]}
        }
    ]
    users_col.insert_many(mock_users)
    logger.info("Seeded %d user profiles.", len(mock_users))

    # 3. Seed Policies Collection (With Vector Embeddings)
    policies_col = db["policies"]
    policies_col.drop()

    raw_policies = [
        {
            "policy_id": "POL_01",
            "title": "Refund & Return Policy",
            "content": "Customers can request an instant refund or replacement for damaged items, missing groceries, or expired products within 24 hours of delivery. A clear photo upload of the damaged item is mandatory for processing perishable items."
        },
        {
            "policy_id": "POL_02",
            "title": "Delivery Timelines & Delays",
            "content": "Standard quick-commerce delivery takes between 10 to 20 minutes from the time of order confirmation. If delivery exceeds 45 minutes due to unforeseen weather or traffic, customers are eligible for free delivery vouchers."
        },
        {
            "policy_id": "POL_03",
            "title": "Cancellation Policy",
            "content": "Orders can be cancelled free of charge within 60 seconds of placement. Once the delivery executive has picked up the order from the dark store, cancellations are no longer permitted."
        }
    ]

    # Load open-source embedding model matching our config
    logger.info("Loading sentence-transformers model for policy vectorization...")
    embedder = SentenceTransformer("all-MiniLM-L6-v2")

    vectorized_policies = []
    for pol in raw_policies:
        combined_text = f"{pol['title']}: {pol['content']}"
        embedding_vector = embedder.encode(combined_text).tolist()
        vectorized_policies.append({
            "policy_id": pol["policy_id"],
            "title": pol["title"],
            "content": pol["content"],
            "embedding": embedding_vector
        })

    policies_col.insert_many(vectorized_policies)
    logger.info("Seeded and vectorized %d policy documents.", len(vectorized_policies))

    client.close()
    logger.info("Database seeding completed successfully!")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_database()