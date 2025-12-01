from sqlalchemy import Column, Integer, Text, Date, ForeignKey
from app.api.models.base import Base

class Pet(Base):
    __tablename__ = "pets"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    name = Column(Text, nullable=False)
    breed = Column(Text)
    dob = Column(Date)
    gender = Column(Text)
    vaccine_status = Column(Text)
    rewards = Column(Text)
    picture_uri = Column(Text)
