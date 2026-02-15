"""
Tests for the full alert pipeline in generate.py.

Tests would_alert() which combines: crime type matching, exclusion,
distance from Menlo Oaks, and tiered radius (3mi vs 0.25mi).

Frequency context (31 days, ~1400 incidents + ~100 cases):
  - Suspicious Person/Prowler/Trespass: ~60/mo  (0.25mi radius)
  - Burglary Alarm responses:           ~67/mo  (excluded)
  - Shoplifting / Petty Theft:           ~40/mo  (excluded)
  - Real Burglary / Theft / Fraud:       ~25/mo  (3mi radius)
  - Vandalism / Identity / Forgery:      ~10/mo  (3mi radius)
"""

import re
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from generate import (
    haversine_m,
    is_alertable_crime,
    item_within_menlo_oaks,
    crime_text,
    item_id,
    MENLO_OAKS_LAT,
    MENLO_OAKS_LNG,
    THREE_MILES_M,
    QUARTER_MILE_M,
)

# ── Distance presets (latitude offsets from Menlo Oaks center) ──────────
LNG = MENLO_OAKS_LNG
AT_0MI   = MENLO_OAKS_LAT                # 0mi   — right at center
AT_01MI  = MENLO_OAKS_LAT + 0.00145      # 0.1mi — inside 0.25mi
AT_05MI  = MENLO_OAKS_LAT + 0.00725      # 0.5mi — outside 0.25mi, inside 3mi
AT_2MI   = MENLO_OAKS_LAT + 0.029        # 2mi   — inside 3mi
AT_4MI   = MENLO_OAKS_LAT + 0.058        # 4mi   — outside 3mi
AT_25MI  = MENLO_OAKS_LAT + 0.36         # 25mi  — far away


def make_incident(call_type="", call_type_desc="", lat=AT_0MI, prefix="menlopark"):
    return {
        "_source": "incident", "_prefix": prefix,
        "incidentNumber": "202601010001",
        "callType": call_type, "callTypeDescription": call_type_desc,
        "yCoord": lat, "xCoord": LNG,
        "street": "100 TEST ST", "city": "Menlo Park",
    }


def make_case(offense="", crime_type="", classification="", lat=AT_0MI, prefix="menlopark"):
    return {
        "_source": "case", "_prefix": prefix,
        "caseNumber": "26-001",
        "offenseDescription1": offense, "crimeType": crime_type,
        "crimeClassification": classification,
        "yCoord": lat, "xCoord": LNG,
        "street": "100 TEST ST", "city": "Menlo Park",
    }


def would_alert(item):
    """Simulate check_alerts() logic for a single item (no email/dedup)."""
    if not is_alertable_crime(item):
        return False
    within, dist = item_within_menlo_oaks(item)
    if not within:
        return False
    ct = crime_text(item)
    if re.search(r"suspicious\s*person|prowler|trespass", ct, re.IGNORECASE):
        if dist > QUARTER_MILE_M:
            return False
    return True


# ┌──────────────────────────────────────────────────────────────────────────┐
# │  FULL ALERT TABLE — crime type × distance → alert yes/no               │
# │                                                                          │
# │  Crime type               │ Distance │ Alert? │ Why                     │
# │  ─────────────────────────┼──────────┼────────┼──────────────────────── │
# │  Property crimes (3mi radius, ~25/mo)                                    │
# │  Burglary - Residential   │  0mi     │  YES   │ within 3mi             │
# │  Burglary - Commercial    │  2mi     │  YES   │ within 3mi             │
# │  Burglary - Vehicle       │  0.5mi   │  YES   │ within 3mi             │
# │  Grand Theft              │  2mi     │  YES   │ within 3mi             │
# │  Theft From Vehicle       │  0mi     │  YES   │ within 3mi             │
# │  Stolen Vehicle           │  2mi     │  YES   │ within 3mi             │
# │  Fraud                    │  0.5mi   │  YES   │ within 3mi             │
# │  Identity Theft           │  0mi     │  YES   │ within 3mi             │
# │  Forgery                  │  0mi     │  YES   │ within 3mi             │
# │  Embezzlement             │  0mi     │  YES   │ within 3mi             │
# │  Larceny                  │  0mi     │  YES   │ within 3mi             │
# │  Vandalism                │  0mi     │  YES   │ within 3mi             │
# │  Arson                    │  0mi     │  YES   │ within 3mi             │
# │  Burglary - Residential   │  4mi     │  NO    │ outside 3mi            │
# │  Grand Theft              │  4mi     │  NO    │ outside 3mi            │
# │  ─────────────────────────┼──────────┼────────┼──────────────────────── │
# │  Suspicious activity (0.25mi radius, ~60/mo)                             │
# │  Suspicious Person        │  0.1mi   │  YES   │ within 0.25mi          │
# │  Prowler                  │  0.1mi   │  YES   │ within 0.25mi          │
# │  Trespass                 │  0.1mi   │  YES   │ within 0.25mi          │
# │  Suspicious Person        │  0.5mi   │  NO    │ outside 0.25mi         │
# │  Prowler                  │  2mi     │  NO    │ outside 0.25mi         │
# │  Trespass                 │  4mi     │  NO    │ outside 3mi entirely   │
# │  ─────────────────────────┼──────────┼────────┼──────────────────────── │
# │  Excluded (any distance, ~107/mo)                                        │
# │  Shoplift                 │  0mi     │  NO    │ excluded by EXCLUDE_RE │
# │  Petty Theft              │  0mi     │  NO    │ excluded by EXCLUDE_RE │
# │  484 Theft                │  0mi     │  NO    │ excluded by EXCLUDE_RE │
# │  ALARM - BURGLARY         │  0mi     │  NO    │ excluded by EXCLUDE_RE │
# │  Burglary Alarm           │  0mi     │  NO    │ excluded by EXCLUDE_RE │
# │  ─────────────────────────┼──────────┼────────┼──────────────────────── │
# │  Non-property (any distance, ~1000+/mo)                                  │
# │  Traffic Stop             │  0mi     │  NO    │ not in ALERT_RE        │
# │  Medical Aid              │  0mi     │  NO    │ not in ALERT_RE        │
# │  Welfare Check            │  0mi     │  NO    │ not in ALERT_RE        │
# │  Assault                  │  0mi     │  NO    │ not in ALERT_RE        │
# │  DUI                      │  0mi     │  NO    │ not in ALERT_RE        │
# │  Noise Complaint          │  0mi     │  NO    │ not in ALERT_RE        │
# │  Suspicious Circumstances │  0mi     │  NO    │ not in ALERT_RE        │
# │  Drug paraphernalia       │  0mi     │  NO    │ not in ALERT_RE        │
# └──────────────────────────────────────────────────────────────────────────┘

# --- (name, distance, alert?, builder) ---
ALERT_CASES = [
    # ── Property crimes: alert within 3mi (~25/mo) ──
    ("Burglary-Residential @0mi",   True,  lambda: make_case(offense="Burglary - Residential (F)", crime_type="Burglary", lat=AT_0MI)),
    ("Burglary-Commercial @2mi",    True,  lambda: make_case(offense="Burglary - Commercial (F)", crime_type="Burglary", lat=AT_2MI)),
    ("Burglary-Vehicle @0.5mi",     True,  lambda: make_case(offense="Burglary - Vehicle (F)", crime_type="Burglary", lat=AT_05MI)),
    ("Grand Theft @2mi",            True,  lambda: make_case(offense="Grand Theft (F)", crime_type="Theft", lat=AT_2MI)),
    ("Theft From Vehicle @0mi",     True,  lambda: make_case(offense="Theft From Vehicle", crime_type="Theft", lat=AT_0MI)),
    ("Stolen Vehicle @2mi",         True,  lambda: make_case(offense="Stolen Vehicle (F)", crime_type="Theft", lat=AT_2MI)),
    ("Fraud @0.5mi",                True,  lambda: make_case(offense="Fraud (M)", crime_type="Fraud", lat=AT_05MI)),
    ("Identity Theft @0mi",         True,  lambda: make_case(offense="Identity Theft (F)", crime_type="Fraud", lat=AT_0MI)),
    ("Forgery @0mi",                True,  lambda: make_case(offense="Forgery (F)", crime_type="Fraud", lat=AT_0MI)),
    ("Embezzlement @0mi",           True,  lambda: make_case(offense="Embezzlement (F)", crime_type="Fraud", lat=AT_0MI)),
    ("Larceny @0mi",                True,  lambda: make_case(offense="Larceny (M)", crime_type="Theft", lat=AT_0MI)),
    ("Vandalism @0mi",              True,  lambda: make_case(offense="Vandalism (M)", crime_type="Property Crime", lat=AT_0MI)),
    ("Arson @0mi",                  True,  lambda: make_case(offense="Arson (F)", crime_type="Property Crime", lat=AT_0MI)),
    # ── Property crimes: NO outside 3mi ──
    ("Burglary-Residential @4mi",   False, lambda: make_case(offense="Burglary - Residential (F)", crime_type="Burglary", lat=AT_4MI)),
    ("Grand Theft @4mi",            False, lambda: make_case(offense="Grand Theft (F)", crime_type="Theft", lat=AT_4MI)),

    # ── Suspicious activity: alert within 0.25mi only (~60/mo) ──
    ("Suspicious Person @0.1mi",    True,  lambda: make_incident(call_type="Suspicious Person", call_type_desc="Suspicious Circumstances", lat=AT_01MI)),
    ("Prowler @0.1mi",              True,  lambda: make_incident(call_type="Prowler", call_type_desc="Suspicious Circumstances", lat=AT_01MI)),
    ("Trespass @0.1mi",             True,  lambda: make_incident(call_type="Trespass", call_type_desc="Other Calls for Service", lat=AT_01MI)),
    # ── Suspicious activity: NO outside 0.25mi ──
    ("Suspicious Person @0.5mi",    False, lambda: make_incident(call_type="Suspicious Person", call_type_desc="Suspicious Circumstances", lat=AT_05MI)),
    ("Prowler @2mi",                False, lambda: make_incident(call_type="Prowler", call_type_desc="Suspicious Circumstances", lat=AT_2MI)),
    ("Trespass @4mi",               False, lambda: make_incident(call_type="Trespass", call_type_desc="Other Calls for Service", lat=AT_4MI)),

    # ── Excluded: NO at any distance (~107/mo) ──
    ("Shoplift @0mi",               False, lambda: make_case(offense="Shoplift (M)", crime_type="Theft", lat=AT_0MI)),
    ("Petty Theft @0mi",            False, lambda: make_case(offense="Petty Theft (M)", crime_type="Theft", lat=AT_0MI)),
    ("484 Theft @0mi",              False, lambda: make_case(offense="484 Theft (M)", crime_type="Theft", lat=AT_0MI)),
    ("ALARM-BURGLARY @0mi",         False, lambda: make_incident(call_type="ALARM - BURGLARY", call_type_desc="Alarm Responses", lat=AT_0MI)),
    ("Burglary Alarm @0mi",         False, lambda: make_incident(call_type="Burglary Alarm", call_type_desc="Alarm Responses", lat=AT_0MI)),

    # ── Non-property: NO at any distance (~1000+/mo) ──
    ("Traffic Stop @0mi",            False, lambda: make_incident(call_type="Traffic Stop", call_type_desc="Traffic", lat=AT_0MI)),
    ("Medical Aid @0mi",             False, lambda: make_incident(call_type="Medical Aid", call_type_desc="Medical", lat=AT_0MI)),
    ("Welfare Check @0mi",           False, lambda: make_incident(call_type="Welfare Check", call_type_desc="Other Calls for Service", lat=AT_0MI)),
    ("Assault @0mi",                 False, lambda: make_case(offense="Assault (F)", crime_type="Violent Crime", lat=AT_0MI)),
    ("DUI @0mi",                     False, lambda: make_incident(call_type="DUI", call_type_desc="Traffic", lat=AT_0MI)),
    ("Noise Complaint @0mi",         False, lambda: make_incident(call_type="Noise Complaint", call_type_desc="Other Calls for Service", lat=AT_0MI)),
    ("Suspicious Circumstances @0mi",False, lambda: make_incident(call_type="Suspicious Circumstances", call_type_desc="Suspicious Circumstances", lat=AT_0MI)),
    ("Drug paraphernalia @0mi",      False, lambda: make_case(offense="Possess unlawful paraphernalia (M)", crime_type="Drugs or Alcohol", lat=AT_0MI)),
]


class TestWouldAlert(unittest.TestCase):
    """Data-driven: each row in ALERT_CASES becomes a test."""
    pass


for _name, _expected, _builder in ALERT_CASES:
    def _make_test(name=_name, builder=_builder, expected=_expected):
        def test(self):
            item = builder()
            result = would_alert(item)
            self.assertEqual(result, expected, f"{name}: expected {expected}, got {result}")
        return test
    safe = _name.lower().replace(' ', '_').replace('-', '_').replace('@', '_at_').replace('.', '_')
    setattr(TestWouldAlert, f"test_{safe}", _make_test())


class TestDistancePresets(unittest.TestCase):
    """Verify our lat offsets produce the expected distances."""

    def test_0mi(self):
        self.assertAlmostEqual(haversine_m(AT_0MI, LNG, MENLO_OAKS_LAT, MENLO_OAKS_LNG), 0, places=0)

    def test_01mi_within_quarter(self):
        dist = haversine_m(AT_01MI, LNG, MENLO_OAKS_LAT, MENLO_OAKS_LNG)
        self.assertLess(dist, QUARTER_MILE_M, f"{dist:.0f}m should be < {QUARTER_MILE_M}m (0.25mi)")

    def test_05mi_outside_quarter_inside_3mi(self):
        dist = haversine_m(AT_05MI, LNG, MENLO_OAKS_LAT, MENLO_OAKS_LNG)
        self.assertGreater(dist, QUARTER_MILE_M, f"{dist:.0f}m should be > {QUARTER_MILE_M}m (0.25mi)")
        self.assertLess(dist, THREE_MILES_M, f"{dist:.0f}m should be < {THREE_MILES_M}m (3mi)")

    def test_2mi_inside_3mi(self):
        dist = haversine_m(AT_2MI, LNG, MENLO_OAKS_LAT, MENLO_OAKS_LNG)
        self.assertLess(dist, THREE_MILES_M, f"{dist:.0f}m should be < {THREE_MILES_M}m (3mi)")

    def test_4mi_outside_3mi(self):
        dist = haversine_m(AT_4MI, LNG, MENLO_OAKS_LAT, MENLO_OAKS_LNG)
        self.assertGreater(dist, THREE_MILES_M, f"{dist:.0f}m should be > {THREE_MILES_M}m (3mi)")

    def test_missing_coords(self):
        item = make_incident(lat=None)
        item["xCoord"] = None
        within, _ = item_within_menlo_oaks(item)
        self.assertFalse(within)


class TestItemId(unittest.TestCase):
    def test_incident_id(self):
        self.assertEqual(item_id(make_incident(prefix="atherton")), "inc-atherton-202601010001")

    def test_case_id(self):
        self.assertEqual(item_id(make_case(prefix="menlopark")), "case-menlopark-26-001")


class TestCrimeText(unittest.TestCase):
    def test_joins_all_fields(self):
        ct = crime_text(make_incident(call_type="Suspicious Person", call_type_desc="Suspicious Circumstances"))
        self.assertIn("Suspicious Person", ct)
        self.assertIn("Suspicious Circumstances", ct)

    def test_skips_empty(self):
        self.assertEqual(crime_text(make_incident(call_type="Traffic Stop", call_type_desc="")), "Traffic Stop")


if __name__ == "__main__":
    unittest.main()
