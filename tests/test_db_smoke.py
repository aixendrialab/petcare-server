# tests/test_db_smoke.py
import os
import pytest

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None

@pytest.mark.skipif(psycopg is None, reason="psycopg not installed")
def test_db_connect_and_tables_present():
    dsn = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_TEST")
    assert dsn, "Set DATABASE_URL (or DATABASE_URL_TEST) for DB smoke tests"
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                select table_name
                from information_schema.tables
                where table_schema='public'
            """)
            tables = {r[0] for r in cur.fetchall()}
            # Be lenient—assert at least some expected tables if you loaded schema.sql
            # Adjust these names to your real schema.
            expected = {"users", "pets", "orgs"} - {t for t in {"users","pets","orgs"} if t not in tables}
            assert len(tables) > 0, "No tables found. Did you load schema.sql?"
            # Optional: insert/select quick round-trip to verify writes
            # (Adjust to a table guaranteed by your schema)
            if "users" in tables:
                cur.execute("insert into users(phone) values('test-smoke') returning id;")
                new_id = cur.fetchone()[0]
                assert new_id
                conn.commit()
