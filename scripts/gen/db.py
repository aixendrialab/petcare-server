from __future__ import annotations

import psycopg
from psycopg.rows import tuple_row
from typing import Any, List, Sequence, Tuple

def get_conn(dsn: str):
    return psycopg.connect(dsn, autocommit=False, row_factory=tuple_row)

def exec_sql(conn, sql: str, params: Tuple[Any, ...] | None = None):
    with conn.cursor() as cur:
        cur.execute(sql, params or ())

def exec_many(conn, sql: str, rows: Sequence[Sequence[Any]], batch_size: int):
    if not rows:
        return
    with conn.cursor() as cur:
        for i in range(0, len(rows), batch_size):
            cur.executemany(sql, rows[i:i+batch_size])

def insert_many_returning_ids(conn, table: str, cols: List[str], rows: Sequence[Sequence[Any]], batch_size: int) -> List[int]:
    """
    psycopg3: use executemany(..., returning=True) for RETURNING to work in bulk.
    """
    if not rows:
        return []

    placeholders = ",".join(["%s"] * len(cols))
    col_list = ",".join(cols)
    sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) RETURNING id"

    ids: List[int] = []
    with conn.cursor() as cur:
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i+batch_size]
            cur.executemany(sql, batch, returning=True)
            ids.extend([int(r[0]) for r in cur.fetchall()])
    return ids
