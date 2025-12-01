from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, func
from app.api.models.base import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    phone = Column(Text, unique=True, nullable=False)
    email = Column(Text, unique=True)
    name = Column(Text)
    active_role = Column(Text)     # CHECK constraint handled by DB
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
