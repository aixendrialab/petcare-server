from fastapi import APIRouter, Depends, Query
from typing import Literal
from app.routers.security import current_user_id
from app.core.db import get_conn

router = APIRouter()
ProviderRole = Literal["vendor","pharmacist","nutritionist","hostel"]

@router.get("/vendor/dashboard")
async def vendor_dashboard(role: ProviderRole = Query(...), user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM provider_stores WHERE owner_user_id=%s AND role=%s", (user_id, role))
        r = await cur.fetchone()
        if not r:
            return {"role": role, "as_of": "now", "kpis": [], "actions": []}
        store_id = int(r[0])

        # KPIs
        await cur.execute(
            "SELECT COUNT(*)::int FROM orders WHERE store_id=%s AND status IN ('CREATED','CONFIRMED','PACKED')",
            (store_id,),
        )
        pending = int((await cur.fetchone())[0] or 0)

        await cur.execute(
            "SELECT COUNT(*)::int FROM store_offers WHERE store_id=%s AND is_active=TRUE",
            (store_id,),
        )
        active_offers = int((await cur.fetchone())[0] or 0)

        await cur.execute(
            "SELECT COUNT(*)::int FROM store_offers WHERE store_id=%s AND stock_qty <= reorder_level",
            (store_id,),
        )
        low_stock = int((await cur.fetchone())[0] or 0)

    return {
        "role": role,
        "as_of": "now",
        "kpis": [
            {"title": "Pending orders", "value": str(pending), "hint": "Need action"},
            {"title": "Low stock", "value": str(low_stock), "hint": "Reorder soon"},
            {"title": "Active offers", "value": str(active_offers)},
        ],
        "actions": [
            {"title": "Manage offers", "caption": "Update price & stock", "route": "/provider/catalog"},
            {"title": "View orders", "caption": "Process pending orders", "route": "/provider/orders", "badge": str(pending) if pending else None},
        ],
    }
