from fastapi import APIRouter, Query
from ..core.db import get_conn
from psycopg.rows import dict_row

router = APIRouter()

@router.get("/vets/nearby")
async def vets_nearby(
    lat: float = Query(..., description="Latitude of the search origin"),
    lng: float = Query(..., description="Longitude of the search origin"),
    radius_km: float = Query(default=10.0, description="Search radius in kilometres"),
    limit: int = Query(default=20, le=100),
):
    async with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""
            SELECT * FROM (
                SELECT
                    u.id        AS user_id,
                    u.name,
                    vp.display_name,
                    vp.specialties,
                    vp.visit_in_clinic,
                    vp.visit_video,
                    vp.fee_in_clinic,
                    vp.fee_video,
                    vl.id       AS location_id,
                    vl.name     AS location_name,
                    vl.line1,
                    vl.city,
                    vl.lat,
                    vl.lng,
                    vl.hours,
                    6371 * acos(
                        LEAST(1.0,
                            cos(radians(%s)) * cos(radians(vl.lat)) *
                            cos(radians(vl.lng) - radians(%s)) +
                            sin(radians(%s)) * sin(radians(vl.lat))
                        )
                    ) AS distance_km
                FROM vet_profiles vp
                JOIN users u ON u.id = vp.user_id
                JOIN vet_locations vl ON vl.user_id = vp.user_id
                WHERE vl.lat IS NOT NULL AND vl.lng IS NOT NULL
            ) t
            WHERE distance_km <= %s
            ORDER BY distance_km
            LIMIT %s
        """, (lat, lng, lat, radius_km, limit))
        rows = await cur.fetchall()

    return {"vets": rows, "count": len(rows)}
