# scripts/gen/catalog.py
from __future__ import annotations
import random
from typing import List

CATEGORIES = ["FOOD","ACCESSORY","MEDICINE","SERVICE"]

TITLES = {
  "FOOD": ["Dry Food","Wet Food","Treats","Puppy Food","Kitten Food"],
  "ACCESSORY": ["Steel Bowl","Leash","Harness","Chew Toy","Bed","Carrier","Scratcher","Litter Box"],
  "MEDICINE": ["Tick Spray","Shampoo","Deworming Tabs","Supplement","Ear Drops"],
  "SERVICE": ["Grooming Basic","Grooming Premium","Nail Trim","Bath + Dry"],
}

TAGS = {
  "FOOD": ["dog food","cat food","treats","dry food","wet food"],
  "ACCESSORY": ["dog toy","cat toy","bowl","leash","bed","carrier"],
  "MEDICINE": ["tick control","flea control","hygiene","skin care"],
  "SERVICE": ["grooming","bath","nail trim"],
}

def seed_products(conn, cfg) -> None:
    rng = random.Random(cfg.rng_seed + 21)
    n = int(cfg.num_products)

    rows = []
    for i in range(n):
        cat = rng.choice(CATEGORIES)
        base = rng.choice(TITLES[cat])
        title = f"{cat} Product {i+1} {base}"
        short = f"{base} for dogs/cats"
        desc = f"{base} — generated item {i+1}. Suitable for dogs/cats."
        rx = (cat == "MEDICINE" and rng.random() < 0.25)
        variant_theme = rng.choice(["Color","Size","Pack","Flavour",None,None])
        rows.append((cat, None, "PetCare", title, short, desc, None, rx, None, None, variant_theme, True))

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO catalog_products
              (category, brand_id, brand_text, title, short_desc, description, about_brand,
               prescription_required, hsn_code, tax_class, variant_theme, is_active)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            rows,
        )

def seed_skus(conn, product_ids: List[int], cfg) -> None:
    rng = random.Random(cfg.rng_seed + 22)

    rows = []
    for pid in product_ids:
        # 1 or 2 skus mostly, controlled by avg_skus_per_product
        if rng.random() < max(0.0, min(0.9, cfg.avg_skus_per_product - 1.0)):
            sku_count = 2
        else:
            sku_count = 1

        for j in range(sku_count):
            # choose variant style
            variant_key = rng.choice([None, "Size", "Color", "Pack"])
            if variant_key == "Size":
                variant_value = rng.choice(["S","M","L","XL"])
                pack_label = rng.choice(["200 g","500 g","1 kg","2 kg","10 kg","900 ml"])
            elif variant_key == "Color":
                variant_value = rng.choice(["Red","Blue","Yellow","Green"])
                pack_label = rng.choice(["Classic","Dumbbell","Bone","Ball"])
            elif variant_key == "Pack":
                variant_value = rng.choice(["Pack of 3","Pack of 6","Pack of 12"])
                pack_label = variant_value
            else:
                variant_value = None
                pack_label = rng.choice(["Standard","900 ml","1 unit"])

            sku_code = f"SKU-{pid}-{j+1}"
            rows.append((pid, variant_key, variant_value, pack_label, sku_code, None, j+1, True))

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO catalog_skus
              (product_id, variant_key, variant_value, pack_label, sku_code, barcode, sort_order, is_active)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            rows,
        )

def seed_media(conn, product_ids: List[int], cfg) -> None:
    rng = random.Random(cfg.rng_seed + 23)
    rows = []
    for pid in product_ids:
        # 3 images per product
        for k in range(3):
            uri = f"https://picsum.photos/seed/p{pid}_{k}/900/900"
            label = ["Front","In use","Packaging"][k]
            rows.append((pid, "IMAGE", uri, label, k+1))

    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO product_media (product_id, media_type, uri, label, sort_order) VALUES (%s,%s,%s,%s,%s)",
            rows,
        )

def seed_specs(conn, product_ids: List[int], cfg) -> None:
    rng = random.Random(cfg.rng_seed + 24)
    rows = []
    for pid in product_ids:
        rows.append((pid, "Top highlights", "Pet type", rng.choice(["Dog","Cat","Dog/Cat"]), 1))
        rows.append((pid, "Top highlights", "Material", rng.choice(["Rubber","Stainless steel","Nylon","Fabric"]), 2))
        rows.append((pid, "Product details", "Care", rng.choice(["Washable; air dry","Wipe clean","Hand wash"]), 10))
        rows.append((pid, "Safety & care", "Note", "Supervise play. Replace if damaged.", 20))

    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO product_specs (product_id, spec_group, spec_key, spec_value, sort_order) VALUES (%s,%s,%s,%s,%s)",
            rows,
        )

def seed_tags(conn, product_ids: List[int], cfg) -> None:
    rng = random.Random(cfg.rng_seed + 25)
    rows = []
    # need category lookup for tags
    with conn.cursor() as cur:
        cur.execute("SELECT id, category FROM catalog_products ORDER BY id ASC")
        cat_by_id = {int(r[0]): r[1] for r in cur.fetchall()}

    for pid in product_ids:
        cat = cat_by_id.get(int(pid), "ACCESSORY")
        choices = TAGS.get(cat, ["pet"])
        # 2 tags per product
        t1 = rng.choice(choices)
        t2 = rng.choice(choices)
        rows.append((pid, t1))
        rows.append((pid, t2))

    with conn.cursor() as cur:
        cur.executemany("INSERT INTO product_tags (product_id, tag) VALUES (%s,%s) ON CONFLICT DO NOTHING", rows)
