from sqlalchemy import Column, Integer, Date, JSON, ForeignKey, UniqueConstraint
from app.api.models.base import Base
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.dialects.postgresql import JSONB

class SlotOverride(Base):
    __tablename__ = "slot_overrides"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slot_setting_id = Column(Integer, ForeignKey("slot_settings.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    payload = Column(MutableDict.as_mutable(JSONB), default=dict)              # validated on input

    __table_args__ = (
        UniqueConstraint("slot_setting_id", "date", name="uq_slot_overrides_day"),
    )
