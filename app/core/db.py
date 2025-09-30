# app/core/db.py
import os
from contextlib import asynccontextmanager
from psycopg_pool import AsyncConnectionPool

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://user:pass@localhost:5432/petdb"  # safe default for dev
)

pool: AsyncConnectionPool | None = None

async def init_pool():
    global pool
    if pool is None:
        # tune as needed
        pool = AsyncConnectionPool(
            conninfo=DATABASE_URL,
            min_size=1,
            max_size=10,
            open=False,
            kwargs={"autocommit": True},  # simple dev setup
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
        yield conn
