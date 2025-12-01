from sqlalchemy import Column, Integer, Text, Float, ForeignKey, Boolean
from app.api.models.base import Base

class VetLocation(Base):
    __tablename__ = "vet_locations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    name = Column(Text)
    line1 = Column(Text)
    line2 = Column(Text)
    city = Column(Text)

    lat = Column(Float)
    lng = Column(Float)

    hours = Column(Text)
    is_primary = Column(Boolean, default=False)
