
import os


def seed_phone() -> str:
    """
    Prefer an env var so CI/dev can change the seed account easily.
    Falls back to the seeded phone you've been using in examples.
    """
    return os.getenv("SEED_EXISTING_PHONE", "+919999")