from datetime import datetime
import os
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session
from common.db import SessionLocal, init_db
from common.models import Customer, ApiKey
import secrets

router = APIRouter(prefix="/admin/apikeys", tags=["apikeys"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def admin_guard(x_admin_token: str | None = Header(None)):
    expected = os.environ.get("ADMIN_TOKEN")
    if not expected or not x_admin_token or x_admin_token != expected:
        raise HTTPException(403, "admin token required")

@router.get("/_help")
def help_route(_: None = Depends(admin_guard)):
    return {
        "prefix": "/admin/apikeys",
        "requires": "X-Admin-Token header",
        "endpoints": [
            {"method": "POST", "path": "/customers", "body": {"email": "str", "name": "str?"}},
            {"method": "GET",  "path": "/customers"},
            {"method": "POST", "path": "/", "alt": "/", "body": {"customer_id": "int", "max_players": "int", "expires_at": "iso8601?"}},
            {"method": "GET",  "path": "/"},
            {"method": "PATCH","path": "/{api_key_id}", "body": {"max_players": "int?", "expires_at": "iso8601?", "is_revoked": "bool?"}},
            {"method": "POST", "path": "/{api_key_id}/revoke"},
            {"method": "POST", "path": "/{api_key_id}/activate"},
        ]
    }

# DB is initialized on app startup in main.py

class CustomerCreate(BaseModel):
    email: str
    name: str | None = None

class ApiKeyCreate(BaseModel):
    customer_id: int
    max_players: int = 100
    expires_at: datetime | None = None

class ApiKeyOut(BaseModel):
    id: int
    key: str
    customer_id: int
    max_players: int
    expires_at: datetime | None
    is_revoked: bool

    class Config:
        orm_mode = True

class ApiKeyUpdate(BaseModel):
    max_players: int | None = None
    expires_at: datetime | None = None
    is_revoked: bool | None = None

@router.post("/customers")
def create_customer(body: CustomerCreate, db: Session = Depends(get_db), _: None = Depends(admin_guard)):
    c = Customer(email=body.email.lower().strip(), name=body.name)
    db.add(c)
    db.commit(); db.refresh(c)
    return {"id": c.id, "email": c.email, "name": c.name}

@router.post("/")
@router.post("")
def create_apikey(body: ApiKeyCreate, db: Session = Depends(get_db), _: None = Depends(admin_guard)):
    cust = db.get(Customer, body.customer_id)
    if not cust:
        raise HTTPException(404, "customer not found")
    key = secrets.token_urlsafe(32)
    ak = ApiKey(key=key, owner=cust, max_players=max(2, min(500, body.max_players)), expires_at=body.expires_at)
    db.add(ak)
    db.commit(); db.refresh(ak)
    return ApiKeyOut.from_orm(ak)

@router.get("/customers")
def list_customers(db: Session = Depends(get_db), _: None = Depends(admin_guard)):
    rows = db.query(Customer).order_by(Customer.id.asc()).all()
    return [{"id": c.id, "email": c.email, "name": c.name, "is_active": c.is_active, "created_at": c.created_at.isoformat() if c.created_at else None} for c in rows]

@router.get("")
@router.get("/")
def list_apikeys(db: Session = Depends(get_db), _: None = Depends(admin_guard)):
    rows = db.query(ApiKey).order_by(ApiKey.id.asc()).all()
    out = []
    for ak in rows:
        out.append({
            "id": ak.id,
            "key": ak.key,
            "customer_id": ak.owner_id,
            "max_players": ak.max_players,
            "expires_at": ak.expires_at.isoformat() if ak.expires_at else None,
            "is_revoked": ak.is_revoked,
            "created_at": ak.created_at.isoformat() if ak.created_at else None,
        })
    return out

@router.patch("/{api_key_id}")
def update_apikey(api_key_id: int, body: ApiKeyUpdate, db: Session = Depends(get_db), _: None = Depends(admin_guard)):
    ak = db.get(ApiKey, api_key_id)
    if not ak:
        raise HTTPException(404, "api key not found")
    if body.max_players is not None:
        ak.max_players = max(2, min(500, int(body.max_players)))
    if body.expires_at is not None:
        ak.expires_at = body.expires_at
    if body.is_revoked is not None:
        ak.is_revoked = bool(body.is_revoked)
    db.add(ak); db.commit(); db.refresh(ak)
    return ApiKeyOut.from_orm(ak)

@router.post("/{api_key_id}/revoke")
def revoke_apikey(api_key_id: int, db: Session = Depends(get_db), _: None = Depends(admin_guard)):
    ak = db.get(ApiKey, api_key_id)
    if not ak:
        raise HTTPException(404, "api key not found")
    ak.is_revoked = True
    db.add(ak); db.commit(); db.refresh(ak)
    return {"status": "revoked", "id": ak.id}

@router.post("/{api_key_id}/activate")
def activate_apikey(api_key_id: int, db: Session = Depends(get_db), _: None = Depends(admin_guard)):
    ak = db.get(ApiKey, api_key_id)
    if not ak:
        raise HTTPException(404, "api key not found")
    ak.is_revoked = False
    db.add(ak); db.commit(); db.refresh(ak)
    return {"status": "active", "id": ak.id}

def validate_api_key(db: Session, api_key: str) -> ApiKey:
    if not api_key:
        raise HTTPException(401, "missing api key")
    ak = db.query(ApiKey).filter(ApiKey.key == api_key).first()
    if not ak:
        raise HTTPException(401, "invalid api key")
    if ak.is_revoked:
        raise HTTPException(403, "api key revoked")
    if ak.expires_at and ak.expires_at < datetime.utcnow():
        raise HTTPException(403, "api key expired")
    if not ak.owner or not ak.owner.is_active:
        raise HTTPException(403, "owner inactive")
    return ak

def require_api_key(x_api_key: str | None = Header(None), db: Session = Depends(get_db)) -> ApiKey:
    return validate_api_key(db, x_api_key)
