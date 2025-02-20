from fastapi import FastAPI, HTTPException
from database.database import users_collection, services_collection, intents_collection
from database.schemas import UserCreate, UserResponse, Service, IntentClassification
from bson import ObjectId
from datetime import datetime
from fastapi import FastAPI, HTTPException
from database.database import knowledge_base_collection, responses_collection
from database.schemas import KnowledgeBase, ResponseModel,Email
from bson import ObjectId
from datetime import datetime
from bson import ObjectId, errors
from fastapi import FastAPI, HTTPException
from database.database import email_messages_collection,email_collection
from database.schemas import EmailMessage
from bson import ObjectId, errors
from datetime import datetime

app = FastAPI()

# ========================================================
# ✅ CRUD : USERS
# ========================================================
@app.post("/users/", response_model=UserResponse)
async def create_user(user: UserCreate):
    new_user = {
        "email": user.email,
        "password_hash": user.password_hash,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "settings": user.settings
    }
    result = await users_collection.insert_one(new_user)
    return {**new_user, "user_id": str(result.inserted_id)}

@app.get("/users/", response_model=list[UserResponse])
async def get_users():
    users = await users_collection.find().to_list(100)
    return [{**user, "user_id": str(user["_id"])} for user in users]

@app.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: str):
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {**user, "user_id": str(user["_id"])}

@app.put("/users/{user_id}", response_model=UserResponse)
async def update_user(user_id: str, user: UserCreate):
    update_data = {
        "$set": {
            "email": user.email,
            "password_hash": user.password_hash,
            "updated_at": datetime.utcnow(),
            "settings": user.settings
        }
    }
    result = await users_collection.update_one({"_id": ObjectId(user_id)}, update_data)
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="User not found or no changes made")
    updated_user = await users_collection.find_one({"_id": ObjectId(user_id)})
    return {**updated_user, "user_id": str(updated_user["_id"])}

@app.delete("/users/{user_id}")
async def delete_user(user_id: str):
    result = await users_collection.delete_one({"_id": ObjectId(user_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "User deleted successfully"}

# ========================================================
# ✅ CRUD : SERVICES
# ========================================================
@app.post("/services/")
async def create_service(service: Service):
    new_service = await services_collection.insert_one(service.model_dump())
    return {"id": str(new_service.inserted_id)}

@app.get("/services/")
async def get_services():
    services = await services_collection.find().to_list(100)
    return [{"id": str(service["_id"]), "service_name": service["service_name"], "support": service["support"]} for service in services]

@app.get("/services/{service_id}")
async def get_service(service_id: str):
    service = await services_collection.find_one({"_id": ObjectId(service_id)})
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    return {"id": str(service["_id"]), "service_name": service["service_name"], "support": service["support"]}

@app.put("/services/{service_id}")
async def update_service(service_id: str, service: Service):
    result = await services_collection.update_one(
        {"_id": ObjectId(service_id)},
        {"$set": service.model_dump()}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Service not found or no changes made")
    return {"message": "Service updated successfully"}

@app.delete("/services/{service_id}")
async def delete_service(service_id: str):
    result = await services_collection.delete_one({"_id": ObjectId(service_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Service not found")
    return {"message": "Service deleted successfully"}

# ========================================================
# ✅ CRUD : INTENTS CLASSIFICATION
# ========================================================


@app.post("/intents/")
async def create_intent(intent: IntentClassification):
    try:
        intent_data = {
            "email_id": ObjectId(intent.email_id),
            "service_id": ObjectId(intent.service_id),
            "description": intent.description,
            "threshold": intent.threshold,
            "knowledge_base_id": ObjectId(intent.knowledge_base_id)
        }
    except errors.InvalidId:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format for email_id, service_id, or knowledge_base_id")

    new_intent = await intents_collection.insert_one(intent_data)
    return {"id": str(new_intent.inserted_id)}


@app.get("/intents/")
async def get_intents():
    intents = await intents_collection.find().to_list(100)
    return [
        {
            "id": str(intent["_id"]),
            "email_id": str(intent["email_id"]),
            "service_id": str(intent["service_id"]),
            "description": intent["description"],
            "threshold": intent["threshold"],
            "knowledge_base_id": str(intent["knowledge_base_id"])
        }
        for intent in intents
    ]

@app.get("/intents/{intent_id}")
async def get_intent(intent_id: str):
    intent = await intents_collection.find_one({"_id": ObjectId(intent_id)})
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")
    return {
        "id": str(intent["_id"]),
        "email_id": str(intent["email_id"]),
        "service_id": str(intent["service_id"]),
        "description": intent["description"],
        "threshold": intent["threshold"],
        "knowledge_base_id": str(intent["knowledge_base_id"])
    }

@app.delete("/intents/{intent_id}")
async def delete_intent(intent_id: str):
    result = await intents_collection.delete_one({"_id": ObjectId(intent_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Intent not found")
    return {"message": "Intent deleted successfully"}


# ========================================================
# ✅ CRUD : KNOWLEDGE BASE
# ========================================================
@app.post("/knowledge_base/")
async def create_knowledge(knowledge: KnowledgeBase):
    new_knowledge = knowledge.model_dump()
    result = await knowledge_base_collection.insert_one(new_knowledge)
    return {"id": str(result.inserted_id)}

@app.get("/knowledge_base/")
async def get_knowledge_base():
    knowledge = await knowledge_base_collection.find().to_list(100)
    return [{"id": str(k["_id"]), **k} for k in knowledge]

@app.get("/knowledge_base/{knowledge_id}")
async def get_knowledge(knowledge_id: str):
    knowledge = await knowledge_base_collection.find_one({"_id": ObjectId(knowledge_id)})
    if not knowledge:
        raise HTTPException(status_code=404, detail="Knowledge not found")
    return {"id": str(knowledge["_id"]), **knowledge}

@app.put("/knowledge_base/{knowledge_id}")
async def update_knowledge(knowledge_id: str, knowledge: KnowledgeBase):
    update_data = {
        "$set": knowledge.model_dump(exclude={"created_at"}),  # On ne change pas created_at
        "$currentDate": {"updated_at": True}
    }
    result = await knowledge_base_collection.update_one({"_id": ObjectId(knowledge_id)}, update_data)
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Knowledge not found or no changes made")
    return {"message": "Knowledge updated successfully"}

@app.delete("/knowledge_base/{knowledge_id}")
async def delete_knowledge(knowledge_id: str):
    result = await knowledge_base_collection.delete_one({"_id": ObjectId(knowledge_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Knowledge not found")
    return {"message": "Knowledge deleted successfully"}

# ========================================================
# ✅ CRUD : RESPONSES
# ========================================================
@app.post("/responses/")
async def create_response(response: ResponseModel):
    response_data = response.model_dump()
    result = await responses_collection.insert_one(response_data)
    return {"id": str(result.inserted_id)}

@app.get("/responses/")
async def get_responses():
    responses = await responses_collection.find().to_list(100)
    return [{"id": str(r["_id"]), **r} for r in responses]

@app.get("/responses/{response_id}")
async def get_response(response_id: str):
    response = await responses_collection.find_one({"_id": ObjectId(response_id)})
    if not response:
        raise HTTPException(status_code=404, detail="Response not found")
    return {"id": str(response["_id"]), **response}

@app.put("/responses/{response_id}")
async def update_response(response_id: str, response: ResponseModel):
    update_data = {
        "$set": response.model_dump(exclude={"sent_at"})  # On ne change pas sent_at
    }
    result = await responses_collection.update_one({"_id": ObjectId(response_id)}, update_data)
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Response not found or no changes made")
    return {"message": "Response updated successfully"}

@app.delete("/responses/{response_id}")
async def delete_response(response_id: str):
    result = await responses_collection.delete_one({"_id": ObjectId(response_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Response not found")
    return {"message": "Response deleted successfully"}









# ========================================================
# ✅ CRUD : EMAIL MESSAGES
# ========================================================
@app.post("/email_messages/")
async def create_email_message(email: EmailMessage):
    # Vérifier que `user_id` et `email_id` sont des ObjectId valides
    try:
        email_data = {
            "user_id": ObjectId(email.user_id),
            "email_id": email.email_id,
            "subject": email.subject,
            "content": email.content,
            "received_at": email.received_at,
            "processed": email.processed,
            "response_sent": email.response_sent,
            "response_time": email.response_time
        }
    except errors.InvalidId:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format for user_id")

    new_email = await email_messages_collection.insert_one(email_data)
    return {"id": str(new_email.inserted_id)}

@app.get("/email_messages/")
async def get_email_messages():
    emails = await email_messages_collection.find().to_list(100)
    return [
        {
            "id": str(email["_id"]),
            "user_id": str(email["user_id"]),
            "email_id": email["email_id"],
            "subject": email["subject"],
            "content": email["content"],
            "received_at": email["received_at"],
            "processed": email["processed"],
            "response_sent": email["response_sent"],
            "response_time": email["response_time"]
        }
        for email in emails
    ]

@app.get("/email_messages/{email_id}")
async def get_email_message(email_id: str):
    try:
        email = await email_messages_collection.find_one({"_id": ObjectId(email_id)})
        if not email:
            raise HTTPException(status_code=404, detail="Email not found")
        return {
            "id": str(email["_id"]),
            "user_id": str(email["user_id"]),
            "email_id": email["email_id"],
            "subject": email["subject"],
            "content": email["content"],
            "received_at": email["received_at"],
            "processed": email["processed"],
            "response_sent": email["response_sent"],
            "response_time": email["response_time"]
        }
    except errors.InvalidId:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")

@app.put("/email_messages/{email_id}")
async def update_email_message(email_id: str, email: EmailMessage):
    try:
        update_data = {
            "$set": {
                "user_id": ObjectId(email.user_id),
                "email_id": email.email_id,
                "subject": email.subject,
                "content": email.content,
                "processed": email.processed,
                "response_sent": email.response_sent,
                "response_time": email.response_time,
                "received_at": email.received_at
            }
        }
        result = await email_messages_collection.update_one({"_id": ObjectId(email_id)}, update_data)
        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="Email not found or no changes made")
        return {"message": "Email updated successfully"}
    except errors.InvalidId:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")

@app.delete("/email_messages/{email_id}")
async def delete_email_message(email_id: str):
    try:
        result = await email_messages_collection.delete_one({"_id": ObjectId(email_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Email not found")
        return {"message": "Email deleted successfully"}
    except errors.InvalidId:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")





@app.post("/email/")
async def create_email(email: Email):
    email_data = email.model_dump()
    result = await email_collection.insert_one(email_data)
    return {"id": str(result.inserted_id)}

@app.get("/email/")
async def get_emails():
    emails = await email_collection.find().to_list(100)
    return [{"id": str(e["_id"]), "email_address": e["email_address"]} for e in emails]

@app.get("/email/{email_id}")
async def get_email(email_id: str):
    try:
        email = await email_collection.find_one({"_id": ObjectId(email_id)})
        if not email:
            raise HTTPException(status_code=404, detail="Email not found")
        return {"id": str(email["_id"]), "email_address": email["email_address"]}
    except errors.InvalidId:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")
