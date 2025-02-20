import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

# Connexion à MongoDB
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "ready"

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

async def check_collections():
    collections = await db.list_collection_names()
    if collections:
        print("✅ Collections existantes dans MongoDB:", collections)
    else:
        print("❌ Aucune collection trouvée dans la base de données.")

# Exécuter la vérification
if __name__ == "__main__":
    asyncio.run(check_collections())
