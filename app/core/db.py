# app/core/db.py
import os
from contextlib import asynccontextmanager
from psycopg_pool import AsyncConnectionPool

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://user:pass@localhost:5432/petdb"
)

pool: AsyncConnectionPool | None = None

async def init_pool():
    global pool
    if pool is None:
        # Pass timezone at connection level (works for every conn in the pool)
        pool = AsyncConnectionPool(
            conninfo=DATABASE_URL,
            min_size=1,
            max_size=10,
            open=False,
            kwargs={
                "autocommit": True,
                # Force UTC on each connection from the moment it’s established
                "options": "-c timezone=UTC",
            },
        )
        await pool.open()

async def close_pool():
    if pool is not None:
        await pool.close()

@asynccontextmanager
async def get_conn():
    """
    Usage:
      async with get_conn() as conn:
          async with conn.cursor() as cur:
              await cur.execute("select 1")
              rows = await cur.fetchall()
    """
    if pool is None:
        await init_pool()

    async with pool.connection() as conn:
        # Double-safety: enforce UTC even if options were bypassed (e.g., in some envs)
        await conn.execute("SET TIME ZONE 'UTC'")
        yield conn
