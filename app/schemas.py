from pydantic import BaseModel
from typing import Optional, List

class ParentCreate(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None

class ParentOut(BaseModel):
    id: int
    name: str
    class Config: from_attributes = True

class PetCreate(BaseModel):
    owner_id: int
    name: str
    breed: str
    dob: str | None = None
    gender: str | None = None

class PetOut(BaseModel):
    id: int
    owner_id: int
    name: str
    breed: str
    dob: str | None
    gender: str | None
    class Config: from_attributes = True

class ProviderOut(BaseModel):
    id: int
    role: str
    name: str
    class Config: from_attributes = True

class SlotResponse(BaseModel):
    provider_id: int
    date: str | None = None
    slots: List[str]

class AppointmentCreate(BaseModel):
    pet_id: int
    provider_id: int
    slot: str
    mode: str = "inperson"
    location_id: int | None = None

class AppointmentOut(BaseModel):
    id: int
    pet_id: int
    provider_id: int
    slot_ts: str
    mode: str
    status: str
    class Config: from_attributes = True

class PrescriptionCreate(BaseModel):
    pet_id: int
    provider_id: int
    items: list[dict]

class PrescriptionOut(BaseModel):
    id: int
    pet_id: int
    provider_id: int
    items: str
    class Config: from_attributes = True

class MedicationCreate(BaseModel):
    pet_id: int
    name: str
    schedule: str

class MedicationOut(BaseModel):
    id: int
    pet_id: int
    name: str
    schedule: str
    class Config: from_attributes = True

class VaccineCreate(BaseModel):
    pet_id: int
    name: str
    status: str
    due_on: str | None = None

class VaccineOut(BaseModel):
    id: int
    pet_id: int
    name: str
    status: str
    due_on: str | None
    class Config: from_attributes = True

class ReportCreate(BaseModel):
    pet_id: int
    title: str
    file_url: str

class ReportOut(BaseModel):
    id: int
    pet_id: int
    title: str
    file_url: str
    class Config: from_attributes = True

class ProductOut(BaseModel):
    id: int
    name: str
    description: str
    tags: str
    price: float
    rating: float
    class Config: from_attributes = True

class CartOut(BaseModel):
    id: int
    user_id: int

class CartItemOut(BaseModel):
    id: int
    cart_id: int
    product_id: int
    qty: int

class CartItemCreate(BaseModel):
    cart_id: int
    product_id: int
    qty: int

class OrderOut(BaseModel):
    id: int
    user_id: int
    status: str
    amount: float
    class Config: from_attributes = True

class DeliveryOut(BaseModel):
    id: int
    order_id: int
    status: str
    eta: str | None
    class Config: from_attributes = True

class CheckinCreate(BaseModel):
    appointment_id: int | None = None
    pet_id: int | None = None
    owner_name: str | None = None
    phone: str | None = None
    triage: str
    status: str = "Arrived"

class CheckinOut(BaseModel):
    id: int
    appointment_id: int | None
    pet_id: int | None
    owner_name: str | None
    phone: str | None
    triage: str
    status: str
    class Config: from_attributes = True

class ConsultCreate(BaseModel):
    appointment_id: int
    diagnosis: str
    notes: str

class ConsultOut(BaseModel):
    id: int
    appointment_id: int
    diagnosis: str
    notes: str
    class Config: from_attributes = True

class InvoiceCreate(BaseModel):
    owner_type: str
    owner_id: int
    amount: float

class InvoiceOut(BaseModel):
    id: int
    owner_type: str
    owner_id: int
    amount: float
    status: str
    pdf_url: str | None
    class Config: from_attributes = True

class RewardsSummary(BaseModel):
    points: int

class RewardsRedeem(BaseModel):
    reward_id: str

class NotifPrefs(BaseModel):
    sms: bool
    email: bool
    whatsapp: bool

class AdoptionOut(BaseModel):
    id: int
    org: str
    name: str
    breed: str
    age: str
    notes: str
    status: str
    class Config: from_attributes = True

class EventOut(BaseModel):
    id: int
    title: str
    city: str
    starts_at: str
    class Config: from_attributes = True
