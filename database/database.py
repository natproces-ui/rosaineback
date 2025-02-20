from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "ready"

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

# Collection "users"

# Définition des collections
users_collection = db["users"]
services_collection = db["service"]
intents_collection = db["intents_classification"]
# Nouvelles collections
knowledge_base_collection = db["knowledge_base"]
responses_collection = db["responses"]
# Nouvelle collection
email_messages_collection = db["email_messages"]
# Nouvelle collection pour stocker les emails
email_collection = db["email"]
