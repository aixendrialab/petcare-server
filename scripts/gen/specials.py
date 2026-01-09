# scripts/gen/specials.py
from __future__ import annotations
from typing import List, Tuple

SPECIAL_USERS: List[Tuple[str, str, str, List[str]]] = [
    # phone, name, email, roles
    ("+919900000001", "Asha Rao",      "asha@example.com",      ["parent", "vet", "vendor"]),
    ("+919900000002", "Vikram Singh",  "vikram@example.com",    ["parent"]),
    ("+919900000003", "Dr Meera Shah", "meera@pawsclinic.com",  ["vet"]),
    ("+919900000004", "Ravi Vendor",   "ravi@vendor.com",       ["vendor"]),
    ("+919900000005", "Sita Pharma",   "sita@pharma.com",       ["pharmacist"]),
    ("+919900000006", "Kiran Groom",   "kiran@groom.com",       ["vendor"]),
]
