from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class InvoiceItemIn(BaseModel):
    description: str
    qty: float
    unit_price: float
    tax_rate: float = 0.0

class InvoiceCreate(BaseModel):
    appointment_id: int
    items: List[InvoiceItemIn]

class InvoiceOut(BaseModel):
    id: int
    appointment_id: int
    invoice_no: str
    invoice_date: datetime
    subtotal: float
    tax_cgst: float
    tax_sgst: float
    tax_igst: float
    total: float
    status: str