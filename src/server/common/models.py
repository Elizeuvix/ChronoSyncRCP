from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from .db import Base

class Customer(Base):
    __tablename__ = 'customers'
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    api_keys = relationship('ApiKey', back_populates='owner', cascade='all, delete-orphan')

class ApiKey(Base):
    __tablename__ = 'api_keys'
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True, nullable=False)
    owner_id = Column(Integer, ForeignKey('customers.id'), nullable=False)
    max_players = Column(Integer, default=100)
    expires_at = Column(DateTime, nullable=True)
    is_revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    owner = relationship('Customer', back_populates='api_keys')
