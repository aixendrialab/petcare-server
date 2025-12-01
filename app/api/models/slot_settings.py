from sqlalchemy import (
    Column, Integer, String, ForeignKey, Date, JSON, Boolean,
    UniqueConstraint, Index, or_, text
)
from app.api.models.base import Base
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.dialects.postgresql import JSONB

class SlotSetting(Base):
    __tablename__ = "slot_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Context (required)
    user_id = Column(Integer, nullable=False, index=True)             # FK users(id)
    location_id = Column(Integer, nullable=True, index=True)          # FK vet_locations(id); required for in_person
    consultation_type = Column(String, nullable=False)                # 'in_person' | 'video'

    # Core knobs
    slot_minutes = Column(Integer, nullable=False, default=15)        # consult length
    gap_minutes = Column(Integer, nullable=False, default=0)          # buffer between slots
    per_slot_capacity = Column(Integer, nullable=False, default=1)
    lead_time_minutes = Column(Integer, nullable=False, default=0)    # rolling buffer (parent view, same day)
    booking_window_days = Column(Integer, nullable=False, default=30) # rolling horizon
    visible_to_parents = Column(Boolean, nullable=False, default=True)

    # Template & exceptions
    week_rules = Column(JSON, nullable=False, default={})             # validated via Pydantic on create/update
    blackout_dates = Column(JSON, nullable=False, default=[])

    # Optional versioning of rules
    effective_from = Column(Date, nullable=True)
    effective_to   = Column(Date, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "location_id", "consultation_type", name="uq_slot_settings_ctx"),
        Index("ix_slot_settings_effective", "effective_from", "effective_to"),
    )
