from fastapi import APIRouter
from .routes import parents_pets, providers, appointments, clinical, shop, misc, vetops

api = APIRouter()
api.include_router(parents_pets.parents, prefix="/parents", tags=["parents"])
api.include_router(parents_pets.pets, prefix="/pets", tags=["pets"])
api.include_router(providers.router, prefix="/providers", tags=["providers"])
api.include_router(appointments.router, prefix="/appointments", tags=["appointments"])
api.include_router(clinical.router, tags=["prescriptions","medications","vaccines","reports","consults","invoices"])
api.include_router(shop.router, tags=["products","cart","orders","deliveries","subscriptions","rewards"])
api.include_router(vetops.router, tags=["vet-ops"])
api.include_router(misc.router, tags=["adoption","events","notifications","televisit"])
