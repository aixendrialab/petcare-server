import os

def _extract_test_otp(_: dict | None = None) -> str:
    """
    The app never returns OTPs in API responses. For tests, we use a fixed code,
    configurable via env. Keep this in sync with the server-side FIXED_OTP.
    """
    return os.getenv("TEST_OTP", "000000")
