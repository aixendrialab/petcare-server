from sqlalchemy import Column, Integer, String, Text, ForeignKey, Numeric
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
from app.api.models import Base

class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="CASCADE"), unique=True, nullable=False)
    vet_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    location_id = Column(Integer, ForeignKey("vet_locations.id", ondelete="CASCADE"), nullable=False)
    invoice_no = Column(String, nullable=False, unique=True)
    invoice_date = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    bill_to_parent_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    clinic_legal_name = Column(Text, nullable=False)
    clinic_address = Column(Text, nullable=False)
    gstin = Column(String, nullable=True)
    subtotal = Column(Numeric(12,2), nullable=False, default=0)
    tax_cgst = Column(Numeric(12,2), nullable=False, default=0)
    tax_sgst = Column(Numeric(12,2), nullable=False, default=0)
    tax_igst = Column(Numeric(12,2), nullable=False, default=0)
    total = Column(Numeric(12,2), nullable=False, default=0)
    status = Column(String, nullable=False, default="unpaid")

class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    description = Column(Text, nullable=False)
    qty = Column(Numeric(10,2), nullable=False, default=1)
    unit_price = Column(Numeric(12,2), nullable=False, default=0)
    amount = Column(Numeric(12,2), nullable=False, default=0)
    tax_rate = Column(Numeric(5,2), nullable=False, default=0)
