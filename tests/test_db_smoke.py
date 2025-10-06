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
            # confirm we can see tables
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            )
            tables = {r[0] for r in cur.fetchall()}
            assert len(tables) > 0, "No tables found. Did you load schema.sql?"

            # Optional round-trip write/read to a guaranteed table
            if "users" in tables:
                # Check if our smoke row already exists
                cur.execute("SELECT id FROM users WHERE phone = %s LIMIT 1;", ("test-smoke",))
                row = cur.fetchone()

                if row is None:
                    # Insert only when absent
                    cur.execute(
                        "INSERT INTO users (phone) VALUES (%s) RETURNING id;",
                        ("test-smoke",),
                    )
                    row = cur.fetchone()
                    conn.commit()  # commit only when we actually wrote

                # If it already existed, no write happened; no commit needed
                new_id = row[0]
                assert new_id  # sanity: we have an id either way
