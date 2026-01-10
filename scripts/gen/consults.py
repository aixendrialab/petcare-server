# scripts/gen/consults.py
from __future__ import annotations

import random
from typing import List, Tuple


REASONS = ["Vaccination", "Skin itching", "Loss of appetite", "Limping", "Routine checkup"]
DX = ["Healthy", "Dermatitis", "Gastritis", "Tick infestation", "Minor sprain"]
ADVICE = ["Follow diet", "Give meds after food", "Keep hydrated", "Rest 3 days", "Revisit in 7 days"]


def _insert_consult_bundle(cur, *, appt_id: int, pet_id: int, vet_id: int, rng: random.Random) -> None:
    cur.execute(
        """
        INSERT INTO consult (appointment_id, pet_id, vet_id, reason, findings, diagnosis, advice)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
        """,
        (
            int(appt_id),
            int(pet_id),
            int(vet_id),
            rng.choice(REASONS),
            "Vitals stable. Exam done.",
            rng.choice(DX),
            rng.choice(ADVICE),
        ),
    )
    cid = int(cur.fetchone()[0])

    # vitals
    cur.execute(
        """
        INSERT INTO consult_vitals (consult_id, weight_kg, temp_c, heart_rate, resp_rate, notes)
        VALUES (%s,%s,%s,%s,%s,%s)
        """,
        (
            cid,
            round(rng.uniform(3.0, 32.0), 2),
            round(rng.uniform(37.8, 39.5), 1),
            rng.randint(80, 140),
            rng.randint(15, 35),
            None,
        ),
    )

    # meds
    for _ in range(rng.randint(1, 3)):
        cur.execute(
            """
            INSERT INTO consult_medication (consult_id, name, dose, frequency, days, notes)
            VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (
                cid,
                rng.choice(["Antibiotic", "Anti-itch", "Probiotic", "Pain relief"]),
                rng.choice(["1 tab", "2 ml", "5 ml"]),
                rng.choice(["OD", "BD", "TID"]),
                rng.randint(3, 10),
                None,
            ),
        )


def seed_consults(conn, cfg, limit: int | None = None) -> int:
    """
    ✅ Guarantees:
      - EVERY parent_id that has at least one COMPLETED appointment will have >= 1 consult
    Also:
      - Adds extra consults for additional completed appointments based on pct_consult_for_completed

    This is REQUIRED because parent endpoint queries:
      WHERE a.parent_id = :pid
    """
    rng = random.Random(cfg.rng_seed + 740)
    created = 0

    pct = float(getattr(cfg, "pct_consult_for_completed", 0.9))
    max_rows = int(limit or getattr(cfg, "max_consults", 20000))

    with conn.cursor() as cur:
        # ------------------------------------------------------------
        # PASS 1: Guarantee 1 consult per parent (if completed appt exists)
        # ------------------------------------------------------------
        # Pick latest COMPLETED appointment per parent that does NOT already have consult
        # Using DISTINCT ON (Postgres)
        cur.execute(
            """
            SELECT DISTINCT ON (a.parent_id)
                a.id, a.pet_id, a.vet_id, a.parent_id
            FROM appointments a
            LEFT JOIN consult c ON c.appointment_id = a.id
            WHERE a.calendar_state='COMPLETED'
              AND a.parent_id IS NOT NULL
              AND c.id IS NULL
            ORDER BY a.parent_id, a.start_ts DESC, a.id DESC
            """
        )
        per_parent = cur.fetchall()  # (appt_id, pet_id, vet_id, parent_id)

        for appt_id, pet_id, vet_id, _parent_id in per_parent:
            _insert_consult_bundle(cur, appt_id=int(appt_id), pet_id=int(pet_id), vet_id=int(vet_id), rng=rng)
            created += 1

        # ------------------------------------------------------------
        # PASS 2: Add extra consults for more completed appointments (optional)
        # ------------------------------------------------------------
        remaining_budget = max(0, max_rows - created)
        if remaining_budget <= 0:
            print(f"[seed] consults created={created} (guaranteed per-parent only)")
            return created

        cur.execute(
            """
            SELECT a.id, a.pet_id, a.vet_id
            FROM appointments a
            LEFT JOIN consult c ON c.appointment_id = a.id
            WHERE a.calendar_state='COMPLETED'
              AND a.parent_id IS NOT NULL
              AND c.id IS NULL
            ORDER BY a.id
            LIMIT %s
            """,
            (remaining_budget,),
        )
        rows = cur.fetchall()

        for appt_id, pet_id, vet_id in rows:
            if rng.random() > pct:
                continue
            _insert_consult_bundle(cur, appt_id=int(appt_id), pet_id=int(pet_id), vet_id=int(vet_id), rng=rng)
            created += 1

    print(f"[seed] consults created={created} (includes guaranteed per-parent)")
    return created
