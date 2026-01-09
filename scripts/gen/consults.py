# scripts/gen/consults.py
from __future__ import annotations
import random
from typing import List

REASONS = ["Vaccination", "Skin itching", "Loss of appetite", "Limping", "Routine checkup"]
DX = ["Healthy", "Dermatitis", "Gastritis", "Tick infestation", "Minor sprain"]
ADVICE = ["Follow diet", "Give meds after food", "Keep hydrated", "Rest 3 days", "Revisit in 7 days"]

def seed_consults(conn, cfg, limit: int | None = None) -> int:
    rng = random.Random(cfg.rng_seed + 740)
    created = 0
    pct = float(getattr(cfg, "pct_consult_for_completed", 0.9))
    max_rows = int(limit or getattr(cfg, "max_consults", 20000))

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.pet_id, a.vet_id
            FROM appointments a
            LEFT JOIN consult c ON c.appointment_id = a.id
            WHERE a.calendar_state='COMPLETED'
              AND c.id IS NULL
            ORDER BY a.id
            LIMIT %s
            """,
            (max_rows,),
        )
        rows = cur.fetchall()

        for appt_id, pet_id, vet_id in rows:
            if rng.random() > pct:
                continue

            cur.execute(
                """
                INSERT INTO consult (appointment_id, pet_id, vet_id, reason, findings, diagnosis, advice)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (int(appt_id), int(pet_id), int(vet_id),
                 rng.choice(REASONS),
                 "Vitals stable. Exam done.",
                 rng.choice(DX),
                 rng.choice(ADVICE)),
            )
            cid = int(cur.fetchone()[0])
            created += 1

            cur.execute(
                """
                INSERT INTO consult_vitals (consult_id, weight_kg, temp_c, heart_rate, resp_rate, notes)
                VALUES (%s,%s,%s,%s,%s,%s)
                """,
                (cid, round(rng.uniform(3.0, 32.0), 2), round(rng.uniform(37.8, 39.5), 1),
                 rng.randint(80, 140), rng.randint(15, 35), None),
            )

            for _ in range(rng.randint(1, 3)):
                cur.execute(
                    """
                    INSERT INTO consult_medication (consult_id, name, dose, frequency, days, notes)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    """,
                    (cid,
                     rng.choice(["Antibiotic", "Anti-itch", "Probiotic", "Pain relief"]),
                     rng.choice(["1 tab", "2 ml", "5 ml"]),
                     rng.choice(["OD", "BD", "TID"]),
                     rng.randint(3, 10),
                     None),
                )

    print(f"[seed] consults created={created}")
    return created
