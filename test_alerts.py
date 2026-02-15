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

# 1 degree latitude ≈ 111km ≈ 69mi
MILES_TO_DEG = 1.0 / 69.0


def lat_at(miles):
    """Latitude that is `miles` north of Menlo Oaks center."""
    return MENLO_OAKS_LAT + miles * MILES_TO_DEG


def make_incident(call_type="", call_type_desc="", miles=0, prefix="menlopark"):
    return {
        "_source": "incident", "_prefix": prefix,
        "incidentNumber": "202601010001",
        "callType": call_type, "callTypeDescription": call_type_desc,
        "yCoord": lat_at(miles), "xCoord": MENLO_OAKS_LNG,
        "street": "100 TEST ST", "city": "Menlo Park",
    }


def make_case(offense="", crime_type="", classification="", miles=0, prefix="menlopark"):
    return {
        "_source": "case", "_prefix": prefix,
        "caseNumber": "26-001",
        "offenseDescription1": offense, "crimeType": crime_type,
        "crimeClassification": classification,
        "yCoord": lat_at(miles), "xCoord": MENLO_OAKS_LNG,
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


# ┌──────────────────────────────────────────────────────────────────────────────┐
# │  FULL ALERT TABLE — crime type × distance → alert yes/no                    │
# │                                                                              │
# │  Crime type               │ Dist  │ Alert? │ Why                            │
# │  ─────────────────────────┼───────┼────────┼─────────────────────────────── │
# │  Property crimes (3mi radius, ~25/mo)                                        │
# │  Burglary - Residential   │ 0mi   │  YES   │ property crime within 3mi     │
# │  Burglary - Residential   │ 2mi   │  YES   │ property crime within 3mi     │
# │  Burglary - Residential   │ 4mi   │  NO    │ property crime outside 3mi    │
# │  Burglary - Commercial    │ 0mi   │  YES   │ property crime within 3mi     │
# │  Burglary - Commercial    │ 4mi   │  NO    │ property crime outside 3mi    │
# │  Burglary - Vehicle       │ 0.5mi │  YES   │ property crime within 3mi     │
# │  Burglary - Vehicle       │ 4mi   │  NO    │ property crime outside 3mi    │
# │  Grand Theft              │ 2mi   │  YES   │ property crime within 3mi     │
# │  Grand Theft              │ 4mi   │  NO    │ property crime outside 3mi    │
# │  Theft From Vehicle       │ 0mi   │  YES   │ property crime within 3mi     │
# │  Theft From Vehicle       │ 4mi   │  NO    │ property crime outside 3mi    │
# │  Stolen Vehicle           │ 2mi   │  YES   │ property crime within 3mi     │
# │  Stolen Vehicle           │ 4mi   │  NO    │ property crime outside 3mi    │
# │  Fraud                    │ 0.5mi │  YES   │ property crime within 3mi     │
# │  Fraud                    │ 4mi   │  NO    │ property crime outside 3mi    │
# │  Identity Theft           │ 0mi   │  YES   │ property crime within 3mi     │
# │  Identity Theft           │ 4mi   │  NO    │ property crime outside 3mi    │
# │  Forgery                  │ 0mi   │  YES   │ property crime within 3mi     │
# │  Forgery                  │ 4mi   │  NO    │ property crime outside 3mi    │
# │  Embezzlement             │ 0mi   │  YES   │ property crime within 3mi     │
# │  Embezzlement             │ 4mi   │  NO    │ property crime outside 3mi    │
# │  Larceny                  │ 0mi   │  YES   │ property crime within 3mi     │
# │  Larceny                  │ 4mi   │  NO    │ property crime outside 3mi    │
# │  Vandalism                │ 0mi   │  YES   │ property crime within 3mi     │
# │  Vandalism                │ 4mi   │  NO    │ property crime outside 3mi    │
# │  Arson                    │ 0mi   │  YES   │ property crime within 3mi     │
# │  Arson                    │ 4mi   │  NO    │ property crime outside 3mi    │
# │  ─────────────────────────┼───────┼────────┼─────────────────────────────── │
# │  Suspicious activity (0.25mi radius, ~60/mo)                                 │
# │  Suspicious Person        │ 0.1mi │  YES   │ suspicious within 0.25mi      │
# │  Suspicious Person        │ 0.5mi │  NO    │ suspicious outside 0.25mi     │
# │  Suspicious Person        │ 4mi   │  NO    │ suspicious outside 3mi        │
# │  Prowler                  │ 0.1mi │  YES   │ suspicious within 0.25mi      │
# │  Prowler                  │ 0.5mi │  NO    │ suspicious outside 0.25mi     │
# │  Prowler                  │ 4mi   │  NO    │ suspicious outside 3mi        │
# │  Trespass                 │ 0.1mi │  YES   │ suspicious within 0.25mi      │
# │  Trespass                 │ 0.5mi │  NO    │ suspicious outside 0.25mi     │
# │  Trespass                 │ 4mi   │  NO    │ suspicious outside 3mi        │
# │  ─────────────────────────┼───────┼────────┼─────────────────────────────── │
# │  Excluded (any distance, ~107/mo)                                            │
# │  Shoplift                 │ 0mi   │  NO    │ excluded by EXCLUDE_RE        │
# │  Petty Theft              │ 0mi   │  NO    │ excluded by EXCLUDE_RE        │
# │  484 Theft                │ 0mi   │  NO    │ excluded by EXCLUDE_RE        │
# │  ALARM - BURGLARY         │ 0mi   │  NO    │ excluded by EXCLUDE_RE        │
# │  Burglary Alarm           │ 0mi   │  NO    │ excluded by EXCLUDE_RE        │
# │  ─────────────────────────┼───────┼────────┼─────────────────────────────── │
# │  Non-property (any distance, ~1000+/mo)                                      │
# │  Traffic Stop             │ 0mi   │  NO    │ not in ALERT_RE               │
# │  Medical Aid              │ 0mi   │  NO    │ not in ALERT_RE               │
# │  Welfare Check            │ 0mi   │  NO    │ not in ALERT_RE               │
# │  Assault                  │ 0mi   │  NO    │ not in ALERT_RE               │
# │  DUI                      │ 0mi   │  NO    │ not in ALERT_RE               │
# │  Noise Complaint          │ 0mi   │  NO    │ not in ALERT_RE               │
# │  Suspicious Circumstances │ 0mi   │  NO    │ not in ALERT_RE               │
# │  Drug paraphernalia       │ 0mi   │  NO    │ not in ALERT_RE               │
# └──────────────────────────────────────────────────────────────────────────────┘

# --- (name, miles, alert?, builder(miles)) ---
# The miles field is passed to the builder to set coordinates.
ALERT_CASES = [
    # ── Property crimes: YES within 3mi, NO outside 3mi (~25/mo) ──
    ("Burglary-Residential",    0,   True,  lambda mi: make_case(offense="Burglary - Residential (F)", crime_type="Burglary", miles=mi)),
    ("Burglary-Residential",    2,   True,  lambda mi: make_case(offense="Burglary - Residential (F)", crime_type="Burglary", miles=mi)),
    ("Burglary-Residential",    4,   False, lambda mi: make_case(offense="Burglary - Residential (F)", crime_type="Burglary", miles=mi)),
    ("Burglary-Commercial",     0,   True,  lambda mi: make_case(offense="Burglary - Commercial (F)", crime_type="Burglary", miles=mi)),
    ("Burglary-Commercial",     4,   False, lambda mi: make_case(offense="Burglary - Commercial (F)", crime_type="Burglary", miles=mi)),
    ("Burglary-Vehicle",        0.5, True,  lambda mi: make_case(offense="Burglary - Vehicle (F)", crime_type="Burglary", miles=mi)),
    ("Burglary-Vehicle",        4,   False, lambda mi: make_case(offense="Burglary - Vehicle (F)", crime_type="Burglary", miles=mi)),
    ("Grand Theft",             2,   True,  lambda mi: make_case(offense="Grand Theft (F)", crime_type="Theft", miles=mi)),
    ("Grand Theft",             4,   False, lambda mi: make_case(offense="Grand Theft (F)", crime_type="Theft", miles=mi)),
    ("Theft From Vehicle",      0,   True,  lambda mi: make_case(offense="Theft From Vehicle", crime_type="Theft", miles=mi)),
    ("Theft From Vehicle",      4,   False, lambda mi: make_case(offense="Theft From Vehicle", crime_type="Theft", miles=mi)),
    ("Stolen Vehicle",          2,   True,  lambda mi: make_case(offense="Stolen Vehicle (F)", crime_type="Theft", miles=mi)),
    ("Stolen Vehicle",          4,   False, lambda mi: make_case(offense="Stolen Vehicle (F)", crime_type="Theft", miles=mi)),
    ("Fraud",                   0.5, True,  lambda mi: make_case(offense="Fraud (M)", crime_type="Fraud", miles=mi)),
    ("Fraud",                   4,   False, lambda mi: make_case(offense="Fraud (M)", crime_type="Fraud", miles=mi)),
    ("Identity Theft",          0,   True,  lambda mi: make_case(offense="Identity Theft (F)", crime_type="Fraud", miles=mi)),
    ("Identity Theft",          4,   False, lambda mi: make_case(offense="Identity Theft (F)", crime_type="Fraud", miles=mi)),
    ("Forgery",                 0,   True,  lambda mi: make_case(offense="Forgery (F)", crime_type="Fraud", miles=mi)),
    ("Forgery",                 4,   False, lambda mi: make_case(offense="Forgery (F)", crime_type="Fraud", miles=mi)),
    ("Embezzlement",            0,   True,  lambda mi: make_case(offense="Embezzlement (F)", crime_type="Fraud", miles=mi)),
    ("Embezzlement",            4,   False, lambda mi: make_case(offense="Embezzlement (F)", crime_type="Fraud", miles=mi)),
    ("Larceny",                 0,   True,  lambda mi: make_case(offense="Larceny (M)", crime_type="Theft", miles=mi)),
    ("Larceny",                 4,   False, lambda mi: make_case(offense="Larceny (M)", crime_type="Theft", miles=mi)),
    ("Vandalism",               0,   True,  lambda mi: make_case(offense="Vandalism (M)", crime_type="Property Crime", miles=mi)),
    ("Vandalism",               4,   False, lambda mi: make_case(offense="Vandalism (M)", crime_type="Property Crime", miles=mi)),
    ("Arson",                   0,   True,  lambda mi: make_case(offense="Arson (F)", crime_type="Property Crime", miles=mi)),
    ("Arson",                   4,   False, lambda mi: make_case(offense="Arson (F)", crime_type="Property Crime", miles=mi)),

    # ── Suspicious activity: YES within 0.25mi, NO outside (~60/mo) ──
    ("Suspicious Person",       0.1, True,  lambda mi: make_incident(call_type="Suspicious Person", call_type_desc="Suspicious Circumstances", miles=mi)),
    ("Suspicious Person",       0.5, False, lambda mi: make_incident(call_type="Suspicious Person", call_type_desc="Suspicious Circumstances", miles=mi)),
    ("Suspicious Person",       4,   False, lambda mi: make_incident(call_type="Suspicious Person", call_type_desc="Suspicious Circumstances", miles=mi)),
    ("Prowler",                 0.1, True,  lambda mi: make_incident(call_type="Prowler", call_type_desc="Suspicious Circumstances", miles=mi)),
    ("Prowler",                 0.5, False, lambda mi: make_incident(call_type="Prowler", call_type_desc="Suspicious Circumstances", miles=mi)),
    ("Prowler",                 4,   False, lambda mi: make_incident(call_type="Prowler", call_type_desc="Suspicious Circumstances", miles=mi)),
    ("Trespass",                0.1, True,  lambda mi: make_incident(call_type="Trespass", call_type_desc="Other Calls for Service", miles=mi)),
    ("Trespass",                0.5, False, lambda mi: make_incident(call_type="Trespass", call_type_desc="Other Calls for Service", miles=mi)),
    ("Trespass",                4,   False, lambda mi: make_incident(call_type="Trespass", call_type_desc="Other Calls for Service", miles=mi)),

    # ── Excluded: NO at any distance (~107/mo) ──
    ("Shoplift",                0,   False, lambda mi: make_case(offense="Shoplift (M)", crime_type="Theft", miles=mi)),
    ("Petty Theft",             0,   False, lambda mi: make_case(offense="Petty Theft (M)", crime_type="Theft", miles=mi)),
    ("484 Theft",               0,   False, lambda mi: make_case(offense="484 Theft (M)", crime_type="Theft", miles=mi)),
    ("ALARM-BURGLARY",          0,   False, lambda mi: make_incident(call_type="ALARM - BURGLARY", call_type_desc="Alarm Responses", miles=mi)),
    ("Burglary Alarm",          0,   False, lambda mi: make_incident(call_type="Burglary Alarm", call_type_desc="Alarm Responses", miles=mi)),

    # ── Non-property: NO at any distance (~1000+/mo) ──
    ("Traffic Stop",            0,   False, lambda mi: make_incident(call_type="Traffic Stop", call_type_desc="Traffic", miles=mi)),
    ("Medical Aid",             0,   False, lambda mi: make_incident(call_type="Medical Aid", call_type_desc="Medical", miles=mi)),
    ("Welfare Check",           0,   False, lambda mi: make_incident(call_type="Welfare Check", call_type_desc="Other Calls for Service", miles=mi)),
    ("Assault",                 0,   False, lambda mi: make_case(offense="Assault (F)", crime_type="Violent Crime", miles=mi)),
    ("DUI",                     0,   False, lambda mi: make_incident(call_type="DUI", call_type_desc="Traffic", miles=mi)),
    ("Noise Complaint",         0,   False, lambda mi: make_incident(call_type="Noise Complaint", call_type_desc="Other Calls for Service", miles=mi)),
    ("Suspicious Circumstances",0,   False, lambda mi: make_incident(call_type="Suspicious Circumstances", call_type_desc="Suspicious Circumstances", miles=mi)),
    ("Drug paraphernalia",      0,   False, lambda mi: make_case(offense="Possess unlawful paraphernalia (M)", crime_type="Drugs or Alcohol", miles=mi)),
]


class TestWouldAlert(unittest.TestCase):
    """Data-driven: each row in ALERT_CASES becomes a test."""
    pass


for _name, _miles, _expected, _builder in ALERT_CASES:
    def _make_test(name=_name, miles=_miles, builder=_builder, expected=_expected):
        def test(self):
            item = builder(miles)
            result = would_alert(item)
            self.assertEqual(result, expected, f"{name} @ {miles}mi: expected {expected}, got {result}")
        return test
    safe = f"{_name}_{_miles}mi".lower().replace(' ', '_').replace('-', '_').replace('.', '_')
    setattr(TestWouldAlert, f"test_{safe}", _make_test())


class TestDistancePresets(unittest.TestCase):
    """Verify lat_at() produces the expected distances."""

    def test_0mi(self):
        dist = haversine_m(lat_at(0), MENLO_OAKS_LNG, MENLO_OAKS_LAT, MENLO_OAKS_LNG)
        self.assertAlmostEqual(dist, 0, places=0)

    def test_01mi_within_quarter(self):
        dist = haversine_m(lat_at(0.1), MENLO_OAKS_LNG, MENLO_OAKS_LAT, MENLO_OAKS_LNG)
        self.assertLess(dist, QUARTER_MILE_M, f"{dist:.0f}m should be < {QUARTER_MILE_M}m (0.25mi)")

    def test_05mi_outside_quarter_inside_3mi(self):
        dist = haversine_m(lat_at(0.5), MENLO_OAKS_LNG, MENLO_OAKS_LAT, MENLO_OAKS_LNG)
        self.assertGreater(dist, QUARTER_MILE_M, f"{dist:.0f}m should be > {QUARTER_MILE_M}m (0.25mi)")
        self.assertLess(dist, THREE_MILES_M, f"{dist:.0f}m should be < {THREE_MILES_M}m (3mi)")

    def test_2mi_inside_3mi(self):
        dist = haversine_m(lat_at(2), MENLO_OAKS_LNG, MENLO_OAKS_LAT, MENLO_OAKS_LNG)
        self.assertLess(dist, THREE_MILES_M, f"{dist:.0f}m should be < {THREE_MILES_M}m (3mi)")

    def test_4mi_outside_3mi(self):
        dist = haversine_m(lat_at(4), MENLO_OAKS_LNG, MENLO_OAKS_LAT, MENLO_OAKS_LNG)
        self.assertGreater(dist, THREE_MILES_M, f"{dist:.0f}m should be > {THREE_MILES_M}m (3mi)")

    def test_missing_coords(self):
        item = {"_source": "incident", "yCoord": None, "xCoord": None}
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
