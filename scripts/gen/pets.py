# scripts/gen/pets.py
from __future__ import annotations

import random
from datetime import date, timedelta
from typing import List, Dict

DOG_BREEDS = ["Labrador","Golden Retriever","Beagle","Indie","German Shepherd"]
CAT_BREEDS = ["Persian","Indian Shorthair","Siamese","Maine Coon"]

DOG_PICS = [
    "https://picsum.photos/seed/dog1/200/200",
    "https://picsum.photos/seed/dog2/200/200",
    "https://picsum.photos/seed/dog3/200/200",
]
CAT_PICS = [
    "https://picsum.photos/seed/cat1/200/200",
    "https://picsum.photos/seed/cat2/200/200",
    "https://picsum.photos/seed/cat3/200/200",
]

def seed_parents(conn, parent_user_ids: List[int]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO user_roles (user_id, role) VALUES (%s,'parent') ON CONFLICT DO NOTHING",
            [(pid,) for pid in parent_user_ids],
        )

def seed_pets(conn, parent_ids: List[int], cfg) -> Dict[int, List[int]]:
    rng = random.Random(cfg.rng_seed + 720)
    pet_ids_by_parent: Dict[int, List[int]] = {}

    pets_per_parent = max(2, int(getattr(cfg, "pets_per_parent", 2)))

    with conn.cursor() as cur:
        for pid in parent_ids:
            for i in range(pets_per_parent):
                species = "dog" if (i == 0 or rng.random() < 0.60) else "cat"  # ensure at least one dog often
                breed = rng.choice(DOG_BREEDS) if species == "dog" else rng.choice(CAT_BREEDS)
                name = f"{('Buddy' if species=='dog' else 'Misty')}-{pid}-{i}"
                dob = date.today() - timedelta(days=rng.randint(120, 3650))
                gender = rng.choice(["male","female"])
                vaccine_status = rng.choice(["up_to_date","due","partial"])
                pic = rng.choice(DOG_PICS) if species == "dog" else rng.choice(CAT_PICS)

                cur.execute(
                    """
                    INSERT INTO pets (user_id, name, breed, dob, gender, vaccine_status, rewards, picture_uri, species)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id
                    """,
                    (pid, name, breed, dob, gender, vaccine_status, "", pic, species),
                )
                pet_id = int(cur.fetchone()[0])
                pet_ids_by_parent.setdefault(pid, []).append(pet_id)

    return pet_ids_by_parent
