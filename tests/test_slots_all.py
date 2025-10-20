# tests/integration/test_slots_all.py
from datetime import date, timedelta
import json
from fastapi.testclient import TestClient
from app.main import app
import os, uuid, random

import logging

from tests.conftest import FIXED_OTP

logger = logging.getLogger(__name__)

client_noauth = TestClient(app)
API = "/api/v1"

WEEK_KEYS = ["mon","tue","wed","thu","fri","sat","sun"]

def _wk_key(d: date) -> str:
    return WEEK_KEYS[d.weekday()]

def bearer(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}

def _register_new_vet_and_get_location(token: str):
    # This uses your vet registration endpoint that creates a user + vet_locations.
    payload = {
        "legal_name": "Dr. Isolated",
        "display_name": "Paws & Claws",
        "business_email": f"biz_{uuid.uuid4().hex[:6]}@paws.test",
        "billing_email": f"bill_{uuid.uuid4().hex[:6]}@paws.test",
        "billing_address": "123, Pet Street",
        "gstin": "GSTIN123",
        "pan": "PAN123",
        "qualifications": "BVSc & AH",
        "license_no": "LIC123",
        "experience_years": 5,
        "specialties": ["dermatology"],
        "visit_in_clinic": True,
        "visit_video": True,
        "fee_in_clinic": 500,
        "fee_video": 400,
        "slot_minutes": 30,
        "locations": [{
            "name": "Main Clinic",
            "line1": "12, MG Road",
            "city": "Chennai",
            "lat": 13.0827,
            "lng": 80.2707,
            "hours": "Mon–Sat 09:00–18:00",
            "is_primary": True
        }],
    }
    r = client_noauth.put(f"{API}/users/vet/register", headers=bearer(token), json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    user_id = body["profile"]["id"]
    location_id = body["locations"][0]["id"]
    return user_id, location_id

def _find_next_weekday_with_rules(start: date, rules: dict) -> date:
    d = start
    for _ in range(7):
        wd = WEEK_KEYS[d.weekday()] 
        if rules.get(wd) and len(rules[wd]) > 0:
            return d
        d += timedelta(days=1)
    return start

def test_inperson_requires_location_id_and_generates_slots_with_gaps_breaks(auth_token_new, client):
    #token = _otp_sign_in_new_phone()
    user_id, location_id = _register_new_vet_and_get_location(auth_token_new)
    assert user_id is not None, "user_id is None"
    assert location_id is not None, "location_id is None"
    print(f"user_id: {user_id!r}, location_id: {location_id!r}")
    rules = {
        "mon":[{"start":"09:00","end":"12:00","breaks":[{"start":"10:00","end":"10:30"}]}],
        "tue":[], "wed":[], "thu":[], "fri":[], "sat":[], "sun":[]
    }
    payload = {
        "user_id": user_id, "location_id": location_id, "consultation_type": "in_person",
        "slot_minutes": 30, "gap_minutes": 10, "per_slot_capacity": 1,
        "lead_time_minutes": 0, "booking_window_days": 30, "visible_to_parents": True,
        "week_rules": rules, "blackout_dates": []
    }
    r = client.post(f"{API}/slot-settings", json=payload)
    assert r.status_code == 200, r.text
    setting_id = r.json()["id"]
    print(f"setting_id: {setting_id}!r")

    # Pick a day that matches the rules
    d = _find_next_weekday_with_rules(date.today(), rules); 
    ds = d.strftime("%Y-%m-%d")
    r = client.get(f"{API}/slots", params={
        "user_id": user_id, "location_id": location_id, "consultation_type": "in_person", "date_str": ds})    
    assert r.status_code == 200
    slots = r.json()
    # Expect cadence with gaps and break respected
    starts = [s["start"] for s in slots if s["status"] != "blocked"]
    assert "09:00" in starts and "10:30" in starts and "11:10" in starts
    # 09:40–10:10 would cross the 10:00–10:30 break, so it must NOT be generated
    assert "09:40" not in starts
    assert all(not ("10:00" <= s["start"] < "10:30") for s in slots)

def test_week_rules_cannot_be_empty_when_visible_to_parents(auth_token_new, client):
    user_id, location_id = _register_new_vet_and_get_location(auth_token_new)
    r = client.post(f"{API}/slot-settings", json={
        "user_id": user_id, "location_id": location_id, "consultation_type": "in_person",
        "slot_minutes": 30, "gap_minutes": 10, "per_slot_capacity": 1,
        "lead_time_minutes": 0, "booking_window_days": 30, "visible_to_parents": True,
        "week_rules": {"mon":[], "tue":[], "wed":[], "thu":[], "fri":[], "sat":[], "sun":[]},
        "blackout_dates": []
    })
    assert r.status_code in (400, 422), r.text

def test_effective_date_switching_between_two_rules(auth_token_new, client):
    user_id, location_id = _register_new_vet_and_get_location(auth_token_new)
    # Rule A: until day+3 (09:00–10:00)
    today = date.today()
    day5  = today + timedelta(days=5)

    wk_today = WEEK_KEYS[today.weekday()]
    wk_day5  = WEEK_KEYS[day5.weekday()]

    # Rule A: until day+3 (09:00–10:00) on the SAME weekday as 'today'
    rulesA = {k: [] for k in ["mon","tue","wed","thu","fri","sat","sun"]}
    rulesA[wk_today] = [{"start":"09:00","end":"10:00"}]
    r = client.post(f"{API}/slot-settings", json={
        "user_id": user_id, "location_id": location_id, "consultation_type": "in_person",
        "slot_minutes": 30, "gap_minutes": 0, "per_slot_capacity": 1,
        "lead_time_minutes": 0, "booking_window_days": 30, "visible_to_parents": True,
        "week_rules": rulesA, "blackout_dates": [],
        "effective_from": None, "effective_to": (date.today()+timedelta(days=3)).isoformat()
    }); 
    assert r.status_code == 200
    
    # Rule B: from day+4 onward (11:00–12:00)
    rulesB = {k: [] for k in ["mon","tue","wed","thu","fri","sat","sun"]}
    rulesB[wk_day5] = [{"start":"11:00","end":"12:00"}]

    r = client.post(f"{API}/slot-settings", json={
        "user_id": user_id, "location_id": location_id, "consultation_type": "in_person",
        "slot_minutes": 30, "gap_minutes": 0, "per_slot_capacity": 1,
        "lead_time_minutes": 0, "booking_window_days": 30, "visible_to_parents": True,
        "week_rules": rulesB, "blackout_dates": [],
        "effective_from": (date.today()+timedelta(days=4)).isoformat(), "effective_to": None
    }); 
    assert r.status_code == 200

    # Today (use A)
    ds = date.today().strftime("%Y-%m-%d")
    r = client.get(f"{API}/slots", params={
        "user_id": user_id, "location_id": location_id, "consultation_type": "in_person", "date_str": ds
    })
    starts = [s["start"] for s in r.json()]
    assert "09:00" in starts
    assert "11:00" not in starts

    # Day+5 (use B)
    ds2 = (date.today()+timedelta(days=5)).strftime("%Y-%m-%d")
    r = client.get(f"{API}/slots", params={
        "user_id": user_id, "location_id": location_id, "consultation_type": "in_person", "date_str": ds2
    })
    starts2 = [s["start"] for s in r.json()]
    assert "11:00" in starts2
    assert "09:00" not in starts2

# 1) Breaks are subtracted BEFORE slicing: 09:40 should not exist if it crosses a 10:00–10:30 break
def test_break_subtraction_prevents_crossing_slot(auth_token_new, client, api):
    user_id, location_id = _register_new_vet_and_get_location(auth_token_new)
    today = date.today()
    wk = _wk_key(today)

    rules = {k: [] for k in WEEK_KEYS}
    rules[wk] = [{"start":"09:00","end":"12:00","breaks":[{"start":"10:00","end":"10:30"}]}]
    r = client.post(f"{api}/slot-settings", json={
        "user_id": user_id, "location_id": location_id, "consultation_type": "in_person",
        "slot_minutes": 30, "gap_minutes": 10, "per_slot_capacity": 1,
        "lead_time_minutes": 0, "booking_window_days": 30, "visible_to_parents": True,
        "week_rules": rules, "blackout_dates":[]
    }); assert r.status_code == 200

    ds = today.strftime("%Y-%m-%d")
    r = client.get(f"{api}/slots", params={
        "user_id": user_id, "location_id": location_id,
        "consultation_type":"in_person", "date_str": ds
    })
    starts = [s["start"] for s in r.json()]
    assert "09:40" not in starts  # because 09:40–10:10 would cross the 10:00–10:30 break


# 2) Gap is honored between slices
def test_gap_minutes_applied(auth_token_new, client, api):
    user_id, location_id = _register_new_vet_and_get_location(auth_token_new)
    d = date.today()
    wk = _wk_key(d)

    rules = {k: [] for k in WEEK_KEYS}
    rules[wk] = [{"start":"09:00","end":"10:30"}]  # 90 minutes
    r = client.post(f"{api}/slot-settings", json={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person",
        "slot_minutes": 20, "gap_minutes": 10, "per_slot_capacity": 1,
        "lead_time_minutes": 0, "booking_window_days": 30, "visible_to_parents": True,
        "week_rules": rules, "blackout_dates":[]
    }); assert r.status_code == 200

    ds = d.strftime("%Y-%m-%d")
    slots = client.get(f"{api}/slots", params={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person", "date_str": ds
    }).json()
    starts = [s["start"] for s in slots]
    # 20m slot + 10m gap → 30m step: 09:00, 09:30, 10:00 (10:30 end cut)
    assert starts[:3] == ["09:00","09:30","10:00"]


# 3) Block windows mark overlapping slots as 'blocked' (capacity=0), and parent view hides them
def test_block_windows_block_and_parent_hides(auth_token_new, client, api):
    user_id, location_id = _register_new_vet_and_get_location(auth_token_new)
    d = date.today()
    wk = _wk_key(d)

    rules = {k: [] for k in WEEK_KEYS}
    rules[wk] = [{"start":"10:30","end":"12:00"}]
    # live setting
    r = client.post(f"{api}/slot-settings", json={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person",
        "slot_minutes": 30, "gap_minutes": 0, "per_slot_capacity": 2,
        "lead_time_minutes": 0, "booking_window_days": 30, "visible_to_parents": True,
        "week_rules": rules, "blackout_dates":[]
    }); assert r.status_code == 200
    setting_id = r.json()["id"]

    ds = d.strftime("%Y-%m-%d")
    # add a block window via overrides (10:45–11:15)
    r = client.post(f"{api}/slot-settings/overrides", json={
        "slot_setting_id": setting_id, "date": ds,
        "payload": {"block_windows":[{"start":"10:45","end":"11:15"}]}
    }); assert r.status_code == 200  # upsert override

    # internal view: blocked slot visible with capacity=0
    internal_slots = client.get(f"{api}/slots", params={
        "user_id": user_id, "location_id": location_id,
        "consultation_type":"in_person", "date_str": ds
    }).json()
    assert any(s["status"]=="blocked" and s["capacity"]==0 for s in internal_slots)

    # parent view: blocked hidden
    public_slots = client.get(f"{api}/slots", params={
        "user_id": user_id, "location_id": location_id,
        "consultation_type":"in_person", "date_str": ds, "public":"true"
    }).json()
    assert all(s["status"]=="available" and s["capacity"]>0 for s in public_slots)



# 4) Extra slots are appended from overrides
def test_extra_slots_are_added(auth_token_new, client, api):
    user_id, location_id = _register_new_vet_and_get_location(auth_token_new)
    d = date.today(); wk = _wk_key(d)
    rules = {k: [] for k in WEEK_KEYS}
    rules[wk] = [{"start":"09:00","end":"09:30"}]  # one baseline slot

    r = client.post(f"{api}/slot-settings", json={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person",
        "slot_minutes": 30, "gap_minutes": 0, "per_slot_capacity": 1,
        "lead_time_minutes": 0, "booking_window_days": 30, "visible_to_parents": True,
        "week_rules": rules, "blackout_dates":[]
    }); assert r.status_code == 200
    setting_id = r.json()["id"]

    ds = d.strftime("%Y-%m-%d")
    r = client.post(f"{api}/slot-settings/overrides", json={
        "slot_setting_id": setting_id, "date": ds,
        "payload": {"extra_slots":[{"start":"10:00","end":"10:10","slot_minutes":10,"capacity":3}]}
    }); assert r.status_code == 200

    slots = client.get(f"{api}/slots", params={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person", "date_str": ds
    }).json()
    assert any(s["start"]=="10:00" and s["end"]=="10:10" and s["capacity"]==3 for s in slots)


# 5) Capacity overrides can change capacity of a baseline slot
def test_capacity_override_applies(auth_token_new, client, api):
    user_id, location_id = _register_new_vet_and_get_location(auth_token_new)
    d = date.today(); wk = _wk_key(d)
    rules = {k: [] for k in WEEK_KEYS}
    rules[wk] = [{"start":"11:00","end":"12:00"}]

    r = client.post(f"{api}/slot-settings", json={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person",
        "slot_minutes": 30, "gap_minutes": 0, "per_slot_capacity": 2,
        "lead_time_minutes": 0, "booking_window_days": 30, "visible_to_parents": True,
        "week_rules": rules, "blackout_dates":[]
    }); assert r.status_code == 200
    setting_id = r.json()["id"]; ds = d.strftime("%Y-%m-%d")

    r = client.post(f"{api}/slot-settings/overrides", json={
        "slot_setting_id": setting_id, "date": ds,
        "payload": {"capacity_overrides":[{"start":"11:00","capacity":5}]}
    }); assert r.status_code == 200

    slots = client.get(f"{api}/slots", params={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person", "date_str": ds
    }).json()
    assert any(s["start"]=="11:00" and s["capacity"]==5 for s in slots)


# 6) Lead-time cutoff hides earlier same-day slots
def test_lead_time_cutoff_same_day(auth_token_new, client, api):
    user_id, location_id = _register_new_vet_and_get_location(auth_token_new)
    d = date.today(); wk = _wk_key(d)
    rules = {k: [] for k in WEEK_KEYS}
    rules[wk] = [{"start":"09:00","end":"10:30"}]

    r = client.post(f"{api}/slot-settings", json={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person",
        "slot_minutes": 30, "gap_minutes": 0, "per_slot_capacity": 1,
        "lead_time_minutes": 60,  # 60m lead
        "booking_window_days": 30, "visible_to_parents": True,
        "week_rules": rules, "blackout_dates":[]
    }); assert r.status_code == 200

    ds = d.strftime("%Y-%m-%d")
    # Parent view: lead cutoff applies
    slots = client.get(f"{api}/slots", params={
        "user_id": user_id, "location_id": location_id,
        "consultation_type":"in_person", "date_str": ds, "public": "true"
    }).json()

    # With 60m lead and a 09:00–10:30 window, only slots starting >= 10:00 should remain,
    # or none if the cutoff has already passed the last slot when the test runs.
    assert all(s["start"] >= "10:00" for s in slots) or len(slots) == 0

# 7) Booking window days restricts far-future queries
def test_booking_window_limits_future(auth_token_new, client, api):
    user_id, location_id = _register_new_vet_and_get_location(auth_token_new)
    d = date.today(); wk = _wk_key(d)
    rules = {k: [] for k in WEEK_KEYS}
    rules[wk] = [{"start":"09:00","end":"11:00"}]

    r = client.post(f"{api}/slot-settings", json={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person",
        "slot_minutes": 30, "gap_minutes": 0, "per_slot_capacity": 1,
        "lead_time_minutes": 0, "booking_window_days": 2, "visible_to_parents": True,  # tight window
        "week_rules": rules, "blackout_dates":[]
    }); assert r.status_code == 200

    ds = (d + timedelta(days=5)).strftime("%Y-%m-%d")
    slots = client.get(f"{api}/slots", params={
        "user_id": user_id, "location_id": location_id,
        "consultation_type":"in_person", "date_str": ds
    }).json()
    assert slots == []  # beyond booking window → invisible


# 8) Blackout date returns no slots even if rules exist
def test_blackout_date_hides_slots(auth_token_new, client, api):
    user_id, location_id = _register_new_vet_and_get_location(auth_token_new)
    d = date.today(); wk = _wk_key(d)
    rules = {k: [] for k in WEEK_KEYS}
    rules[wk] = [{"start":"09:00","end":"10:00"}]

    # live + blackout today
    r = client.post(f"{api}/slot-settings", json={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person",
        "slot_minutes": 30, "gap_minutes": 0, "per_slot_capacity": 1,
        "lead_time_minutes": 0, "booking_window_days": 30, "visible_to_parents": True,
        "week_rules": rules, "blackout_dates":[d.strftime("%Y-%m-%d")]
    }); assert r.status_code == 200

    slots = client.get(f"{api}/slots", params={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person", "date_str": d.strftime("%Y-%m-%d")
    }).json()
    assert slots == []  # blackout wins


# 9) Overlapping effective ranges rejected with 409
def test_overlapping_effective_ranges_rejected(auth_token_new, client, api):
    user_id, location_id = _register_new_vet_and_get_location(auth_token_new)
    d = date.today(); wk = _wk_key(d)
    rules = {k: [] for k in WEEK_KEYS}; rules[wk] = [{"start":"09:00","end":"10:00"}]

    # A: [.. day+3]
    a = client.post(f"{api}/slot-settings", json={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person",
        "slot_minutes": 30, "gap_minutes": 0, "per_slot_capacity": 1,
        "lead_time_minutes": 0, "booking_window_days": 30, "visible_to_parents": True,
        "week_rules": rules, "blackout_dates":[],
        "effective_from": None, "effective_to": (d+timedelta(days=3)).isoformat()
    }); assert a.status_code == 200

    # B: overlaps with A (starts day+2)
    b = client.post(f"{api}/slot-settings", json={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person",
        "slot_minutes": 30, "gap_minutes": 0, "per_slot_capacity": 1,
        "lead_time_minutes": 0, "booking_window_days": 30, "visible_to_parents": True,
        "week_rules": rules, "blackout_dates":[],
        "effective_from": (d+timedelta(days=2)).isoformat(), "effective_to": None
    })
    assert b.status_code == 409


# 10) Per-day override open_windows replaces week_rules for that date
def test_override_open_windows_take_precedence(auth_token_new, client, api):
    user_id, location_id = _register_new_vet_and_get_location(auth_token_new)
    d = date.today(); wk = _wk_key(d)

    # weekly window at 09:00–09:30
    rules = {k: [] for k in WEEK_KEYS}; rules[wk] = [{"start":"09:00","end":"09:30"}]
    r = client.post(f"{api}/slot-settings", json={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person",
        "slot_minutes": 30, "gap_minutes": 0, "per_slot_capacity": 1,
        "lead_time_minutes": 0, "booking_window_days": 30, "visible_to_parents": True,
        "week_rules": rules, "blackout_dates":[]
    }); assert r.status_code == 200
    setting_id = r.json()["id"]
    ds = d.strftime("%Y-%m-%d")

    # override open_windows to 11:00–12:00
    r = client.post(f"{api}/slot-settings/overrides", json={
        "slot_setting_id": setting_id, "date": ds,
        "payload": {"open_windows":[{"start":"11:00","end":"12:00"}]}
    }); assert r.status_code == 200

    slots = client.get(f"{api}/slots", params={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person", "date_str": ds
    }).json()
    starts = [s["start"] for s in slots]
    assert "11:00" in starts and "09:00" not in starts  # override > weekly rules


# 11) away_until appends a block window until a time
def test_away_until_blocks_until_time(auth_token_new, client, api):
    user_id, location_id = _register_new_vet_and_get_location(auth_token_new)
    d = date.today(); wk = _wk_key(d)

    rules = {k: [] for k in WEEK_KEYS}; rules[wk] = [{"start":"10:00","end":"12:00"}]
    r = client.post(f"{api}/slot-settings", json={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person",
        "slot_minutes": 30, "gap_minutes": 0, "per_slot_capacity": 1,
        "lead_time_minutes": 0, "booking_window_days": 30, "visible_to_parents": True,
        "week_rules": rules, "blackout_dates":[]
    }); assert r.status_code == 200
    setting_id = r.json()["id"]; ds = d.strftime("%Y-%m-%d")

    r = client.post(f"{api}/slot-settings/away-until", json={
        "slot_setting_id": setting_id, "date": ds, "start":"10:30", "until":"11:10"
    }); assert r.status_code == 200

    slots = client.get(f"{api}/slots", params={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person", "date_str": ds
    }).json()
    assert any(s["status"]=="blocked" and s["start"] <= "11:00" <= s["end"] for s in slots)


# 12) Draft settings (not visible_to_parents) can have empty week_rules, but produce no parent slots
def test_draft_setting_no_parent_slots(auth_token_new, client, api):
    user_id, location_id = _register_new_vet_and_get_location(auth_token_new)
    d = date.today()

    r = client.post(f"{api}/slot-settings", json={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person",
        "slot_minutes": 30, "gap_minutes": 0, "per_slot_capacity": 1,
        "lead_time_minutes": 0, "booking_window_days": 30, "visible_to_parents": False,  # draft
        "week_rules": {k: [] for k in WEEK_KEYS}, "blackout_dates":[]
    }); assert r.status_code == 200

    # parent view should see nothing even if date aligns (since no weekly windows & not live)
    ds = d.strftime("%Y-%m-%d")
    slots = client.get(f"{api}/slots", params={
        "user_id": user_id, "location_id": location_id,
        "consultation_type":"in_person", "date_str": ds, "public":"true"
    }).json()
    assert slots == []    

def test_extra_slot_short_window_blocked(auth_token_new, client, api):
    user_id, location_id = _register_new_vet_and_get_location(auth_token_new)
    d = date.today(); wk = ["mon","tue","wed","thu","fri","sat","sun"][d.weekday()]
    rules = {k: [] for k in ["mon","tue","wed","thu","fri","sat","sun"]}
    rules[wk] = [{"start":"09:00","end":"09:30"}]
    r = client.post(f"{api}/slot-settings", json={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person",
        "slot_minutes": 30, "gap_minutes": 0, "per_slot_capacity": 1,
        "lead_time_minutes": 0, "booking_window_days": 30, "visible_to_parents": True,
        "week_rules": rules, "blackout_dates":[]
    }); assert r.status_code == 200
    setting_id = r.json()["id"]; ds = d.strftime("%Y-%m-%d")

    # extra slot 10:00–10:10, but block overlaps it
    r = client.post(f"{api}/slot-settings/overrides", json={
        "slot_setting_id": setting_id, "date": ds,
        "payload": {
            "block_windows":[{"start":"10:00","end":"10:10"}],
            "extra_slots":[{"start":"10:00","end":"10:10","capacity":3}]
        }
    }); assert r.status_code == 200

    slots = client.get(f"{api}/slots", params={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person", "date_str": ds
    }).json()
    assert any(s["start"]=="10:00" and s["end"]=="10:10" and s["status"]=="blocked" and s["capacity"]==0 for s in slots)

def test_extra_slot_respects_lead_cutoff(auth_token_new, client, api):
    user_id, location_id = _register_new_vet_and_get_location(auth_token_new)
    d = date.today(); wk = ["mon","tue","wed","thu","fri","sat","sun"][d.weekday()]
    rules = {k: [] for k in ["mon","tue","wed","thu","fri","sat","sun"]}
    rules[wk] = [{"start":"09:00","end":"09:30"}]
    r = client.post(f"{api}/slot-settings", json={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person",
        "slot_minutes": 30, "gap_minutes": 0, "per_slot_capacity": 1,
        "lead_time_minutes": 120,  # 2h lead
        "booking_window_days": 30, "visible_to_parents": True,
        "week_rules": rules, "blackout_dates":[]
    }); assert r.status_code == 200
    setting_id = r.json()["id"]; ds = d.strftime("%Y-%m-%d")

    # extra short window at 09:05–09:10 → gets generated optimistically, but filtered by lead cutoff
    r = client.post(f"{api}/slot-settings/overrides", json={
        "slot_setting_id": setting_id, "date": ds,
        "payload": {"extra_slots":[{"start":"09:05","end":"09:10","capacity":2}]}
    }); assert r.status_code == 200

    slots = client.get(f"{api}/slots", params={
        "user_id": user_id, "location_id": location_id, "consultation_type":"in_person",
        "date_str": ds, "public":"true"
    }).json()
    print(json.dumps(slots, indent=2))
    assert all(not (s["start"]=="09:05" and s["end"]=="09:10") for s in slots)
