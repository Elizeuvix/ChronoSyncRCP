import os
from fastapi import HTTPException, Request, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from common.db import SessionLocal, init_db
from common.models import ApiKey
from datetime import datetime

class PlayerRegister(BaseModel):
    username: str
    password: str

class PlayerLogin(BaseModel):
    username: str
    password: str

fake_db = {}
API_KEY = os.environ.get("API_KEY")  # legacy fallback disabled if DB has keys

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _validate_db_api_key(db: Session, key: str) -> bool:
    if not key:
        return False
    ak = db.query(ApiKey).filter(ApiKey.key == key).first()
    if not ak:
        return False
    if ak.is_revoked:
        return False
    if ak.expires_at and ak.expires_at < datetime.utcnow():
        return False
    if not ak.owner or not ak.owner.is_active:
        return False
    return True

def _require_api_key(request: Request, db: Session):
    init_db()
    key = request.headers.get("X-API-Key")
    if not key:
        raise HTTPException(status_code=401, detail="Missing API key")
    # Prefer DB validation; fallback to env key for dev only
    if not _validate_db_api_key(db, key):
        if not API_KEY or key != API_KEY:
            raise HTTPException(status_code=401, detail="Invalid API key")

def register_player(data: PlayerRegister, request: Request, db: Session = Depends(get_db)):
    _require_api_key(request, db)
    if data.username in fake_db:
        raise HTTPException(status_code=400, detail="Username already exists")
    fake_db[data.username] = data.password
    return {"message": "Player registered successfully"}

def login_player(data: PlayerLogin, request: Request, db: Session = Depends(get_db)):
    _require_api_key(request, db)
    if fake_db.get(data.username) != data.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"message": "Login successful"}
