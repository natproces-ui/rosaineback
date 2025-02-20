from pydantic import BaseModel, EmailStr
from typing import Optional, Dict
from datetime import datetime



# 🔹 Modèle User
class UserCreate(BaseModel):
    email: EmailStr
    password_hash: str
    settings: Optional[Dict] = {"lang": "fr", "threshold": 0.8, "model": "default_model"}

class UserResponse(UserCreate):
    user_id: str

# 🔹 Modèle Service
class Service(BaseModel):
    service_name: str
    support: str

# 🔹 Modèle Intents Classification
class IntentClassification(BaseModel):
    email_id: str
    service_id: str
    description: str
    threshold: float
    knowledge_base_id: str



# 🔹 Modèle Knowledge Base
class KnowledgeBase(BaseModel):
    action: str
    title: str
    content: str
    created_at: datetime = datetime.utcnow()
    updated_at: datetime = datetime.utcnow()

# 🔹 Modèle Responses
class ResponseModel(BaseModel):
    email_id: str
    response_text: str
    send_status: bool
    sent_at: datetime = datetime.utcnow()
    response_quality: Optional[float] = None
    



# 🔹 Modèle Email Messages
class EmailMessage(BaseModel):
    user_id: str
    email_id: str
    subject: str
    content: str
    received_at: datetime = datetime.utcnow()
    processed: bool = False
    response_sent: bool = False
    response_time: Optional[int] = None

class Email(BaseModel):
    email_address: EmailStr
    created_at: datetime = datetime.utcnow()


