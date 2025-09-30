from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Integer, ForeignKey, Text, Float
from .core.database import Base

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(255))

class Parent(Base):
    __tablename__ = "parents"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(255))

class Pet(Base):
    __tablename__ = "pets"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("parents.id"))
    name: Mapped[str] = mapped_column(String(120))
    breed: Mapped[str] = mapped_column(String(120))
    dob: Mapped[str | None] = mapped_column(String(20))
    gender: Mapped[str | None] = mapped_column(String(20))
    photo_url: Mapped[str | None] = mapped_column(String(512))

class Provider(Base):
    __tablename__ = "providers"
    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255))

class ProviderLocation(Base):
    __tablename__ = "provider_locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"))
    label: Mapped[str] = mapped_column(String(255))
    address: Mapped[str] = mapped_column(String(1024))
    lat: Mapped[float | None] = mapped_column()
    lng: Mapped[float | None] = mapped_column()

class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(primary_key=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pets.id"))
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("provider_locations.id"))
    slot_ts: Mapped[str] = mapped_column(String(40))
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))

class Prescription(Base):
    __tablename__ = "prescriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pets.id"))
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"))
    items: Mapped[str] = mapped_column(Text)  # json text

class Medication(Base):
    __tablename__ = "medications"
    id: Mapped[int] = mapped_column(primary_key=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pets.id"))
    name: Mapped[str] = mapped_column(String(255))
    schedule: Mapped[str] = mapped_column(String(255))

class Vaccine(Base):
    __tablename__ = "vaccines"
    id: Mapped[int] = mapped_column(primary_key=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pets.id"))
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(40))
    due_on: Mapped[str | None] = mapped_column(String(40))

class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pets.id"))
    title: Mapped[str] = mapped_column(String(255))
    file_url: Mapped[str] = mapped_column(String(512))

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("providers.id"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    tags: Mapped[str] = mapped_column(String(255))
    price: Mapped[float] = mapped_column()
    rating: Mapped[float] = mapped_column()

class Cart(Base):
    __tablename__ = "carts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

class CartItem(Base):
    __tablename__ = "cart_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[int] = mapped_column()

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(30))
    amount: Mapped[float] = mapped_column()

class Delivery(Base):
    __tablename__ = "deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    status: Mapped[str] = mapped_column(String(40))
    eta: Mapped[str | None] = mapped_column(String(40))

class Checkin(Base):
    __tablename__ = "checkins"
    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id"), nullable=True)
    pet_id: Mapped[int | None] = mapped_column(ForeignKey("pets.id"), nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32))
    triage: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))

class Consult(Base):
    __tablename__ = "consults"
    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"))
    diagnosis: Mapped[str] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text)

class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_type: Mapped[str] = mapped_column(String(20))
    owner_id: Mapped[int] = mapped_column()
    amount: Mapped[float] = mapped_column()
    status: Mapped[str] = mapped_column(String(20))
    pdf_url: Mapped[str | None] = mapped_column(String(512))

class RewardLedger(Base):
    __tablename__ = "rewards_ledger"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    delta: Mapped[int] = mapped_column()
    reason: Mapped[str] = mapped_column(String(255))

class NotificationPrefs(Base):
    __tablename__ = "notification_prefs"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    sms: Mapped[int] = mapped_column()
    email: Mapped[int] = mapped_column()
    whatsapp: Mapped[int] = mapped_column()

class Adoption(Base):
    __tablename__ = "adoptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    org: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    breed: Mapped[str] = mapped_column(String(120))
    age: Mapped[str] = mapped_column(String(40))
    notes: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))

class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(120))
    starts_at: Mapped[str] = mapped_column(String(40))
