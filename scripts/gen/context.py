# scripts/gen/context.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List

@dataclass
class SeedContext:
    cfg: any
    user_ids: List[int] = field(default_factory=list)
    owner_ids: List[int] = field(default_factory=list)
    store_ids: List[int] = field(default_factory=list)
    product_ids: List[int] = field(default_factory=list)
    sku_ids: List[int] = field(default_factory=list)
    offer_ids: List[int] = field(default_factory=list)

    def ensure_users(self, conn) -> List[int]:
        if self.user_ids:
            return self.user_ids
        from scripts.gen.users import seed_users
        self.user_ids = seed_users(conn, self.cfg)
        return self.user_ids

    def ensure_store_owners(self, conn) -> List[int]:
        if self.owner_ids:
            return self.owner_ids

        users = self.ensure_users(conn)

        # auto-adjust instead of failing
        if len(users) < int(self.cfg.num_store_owners):
            from scripts.gen.users import seed_more_users
            needed = int(self.cfg.num_store_owners) - len(users)
            seed_more_users(conn, self.cfg, needed)
            users = self._load_ids(conn, "users")

        if len(users) < int(self.cfg.num_stores):
            from scripts.gen.users import seed_more_users
            needed = int(self.cfg.num_stores) - len(users)
            seed_more_users(conn, self.cfg, needed)
            users = self._load_ids(conn, "users")

        # pick first N users as owners (stable, no randomness needed)
        self.owner_ids = users[: int(self.cfg.num_store_owners)]
        return self.owner_ids

    def ensure_stores(self, conn) -> List[int]:
        if self.store_ids:
            return self.store_ids
        owners = self.ensure_store_owners(conn)
        from scripts.gen.stores import seed_stores
        self.store_ids = seed_stores(conn, owners, self.cfg)
        return self.store_ids

    def ensure_products(self, conn) -> List[int]:
        if self.product_ids:
            return self.product_ids
        from scripts.gen.catalog import seed_products
        seed_products(conn, self.cfg)
        self.product_ids = self._load_ids(conn, "catalog_products")
        return self.product_ids

    def ensure_skus(self, conn) -> List[int]:
        if self.sku_ids:
            return self.sku_ids
        products = self.ensure_products(conn)
        from scripts.gen.catalog import seed_skus
        seed_skus(conn, products, self.cfg)
        self.sku_ids = self._load_ids(conn, "catalog_skus")
        return self.sku_ids

    @staticmethod
    def _load_ids(conn, table: str) -> List[int]:
        with conn.cursor() as cur:
            cur.execute(f"SELECT id FROM {table} ORDER BY id ASC;")
            return [int(r[0]) for r in cur.fetchall()]
