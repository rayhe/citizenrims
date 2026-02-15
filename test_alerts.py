"""
Tests for alert filtering logic in generate.py.

Alert frequency context (from 31 days of data, ~1400 incidents + ~100 cases):
  - Suspicious Person/Prowler/Trespass: ~60/mo (tight 0.25mi radius)
  - Burglary Alarm responses:           ~67/mo (excluded — just alarm triggers)
  - Shoplifting / Petty Theft:           ~40/mo (excluded — store theft)
  - Real Burglary / Theft / Fraud:       ~25/mo (alerted, 3mi radius)
  - Vandalism / Identity / Forgery:      ~10/mo (alerted, 3mi radius)
"""

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


def make_incident(call_type="", call_type_desc="", prefix="menlopark", lat=37.448, lng=-122.177):
    return {
        "_source": "incident", "_prefix": prefix,
        "incidentNumber": "202601010001",
        "callType": call_type, "callTypeDescription": call_type_desc,
        "yCoord": lat, "xCoord": lng,
        "street": "100 TEST ST", "city": "Menlo Park",
    }


def make_case(offense="", crime_type="", classification="", prefix="menlopark", lat=37.448, lng=-122.177):
    return {
        "_source": "case", "_prefix": prefix,
        "caseNumber": "26-001",
        "offenseDescription1": offense, "crimeType": crime_type,
        "crimeClassification": classification,
        "yCoord": lat, "xCoord": lng,
        "street": "100 TEST ST", "city": "Menlo Park",
    }


# ┌─────────────────────────────────────────────────────────────────────┐
# │  ALERT TABLE — what triggers an alert and what doesn't             │
# │                                                                     │
# │  Type / callType             │ Category       │ Alert? │ Freq/mo   │
# │  ────────────────────────────┼────────────────┼────────┼────────── │
# │  Burglary - Residential (F)  │ case           │ YES    │ ~25       │
# │  Burglary - Commercial (F)   │ case           │ YES    │           │
# │  Burglary - Vehicle (F)      │ case           │ YES    │           │
# │  Grand Theft (F)             │ case           │ YES    │           │
# │  Theft From Vehicle           │ case           │ YES    │           │
# │  Stolen Vehicle (F)          │ case           │ YES    │           │
# │  Fraud (M)                   │ case           │ YES    │           │
# │  Identity Theft (F)          │ case           │ YES    │           │
# │  Forgery (F)                 │ case           │ YES    │           │
# │  Embezzlement (F)            │ case           │ YES    │           │
# │  Larceny (M)                 │ case           │ YES    │           │
# │  Vandalism (M)               │ case           │ YES    │ ~10       │
# │  Arson (F)                   │ case           │ YES    │           │
# │  Suspicious Person           │ incident 0.25mi│ YES    │ ~60       │
# │  Prowler                     │ incident 0.25mi│ YES    │           │
# │  Trespass                    │ incident 0.25mi│ YES    │           │
# │  ────────────────────────────┼────────────────┼────────┼────────── │
# │  Shoplift (M)                │ excluded       │ NO     │ ~40       │
# │  Petty Theft (M)             │ excluded       │ NO     │           │
# │  484 Theft (M)               │ excluded       │ NO     │           │
# │  ALARM - BURGLARY            │ excluded       │ NO     │ ~67       │
# │  Burglary Alarm              │ excluded       │ NO     │           │
# │  ────────────────────────────┼────────────────┼────────┼────────── │
# │  Traffic Stop                │ non-property   │ NO     │ ~1000+    │
# │  Medical Aid                 │ non-property   │ NO     │           │
# │  Welfare Check               │ non-property   │ NO     │           │
# │  Assault (F)                 │ non-property   │ NO     │           │
# │  DUI                         │ non-property   │ NO     │           │
# │  Noise Complaint             │ non-property   │ NO     │           │
# │  Suspicious Circumstances    │ non-property   │ NO     │           │
# │  Drug paraphernalia          │ non-property   │ NO     │           │
# └─────────────────────────────────────────────────────────────────────┘

# --- (name, alert?, builder) ---
ALERT_CASES = [
    # YES — property crimes (~25/mo)
    ("Burglary - Residential",   True,  lambda: make_case(offense="Burglary - Residential (F)", crime_type="Burglary")),
    ("Burglary - Commercial",    True,  lambda: make_case(offense="Burglary - Commercial (F)", crime_type="Burglary")),
    ("Burglary - Vehicle",       True,  lambda: make_case(offense="Burglary - Vehicle (F)", crime_type="Burglary")),
    ("Grand Theft",              True,  lambda: make_case(offense="Grand Theft (F)", crime_type="Theft")),
    ("Theft From Vehicle",       True,  lambda: make_case(offense="Theft From Vehicle", crime_type="Theft")),
    ("Stolen Vehicle",           True,  lambda: make_case(offense="Stolen Vehicle (F)", crime_type="Theft")),
    ("Fraud",                    True,  lambda: make_case(offense="Fraud (M)", crime_type="Fraud")),
    ("Identity Theft",           True,  lambda: make_case(offense="Identity Theft (F)", crime_type="Fraud")),
    ("Forgery",                  True,  lambda: make_case(offense="Forgery (F)", crime_type="Fraud")),
    ("Embezzlement",             True,  lambda: make_case(offense="Embezzlement (F)", crime_type="Fraud")),
    ("Larceny",                  True,  lambda: make_case(offense="Larceny (M)", crime_type="Theft")),
    # YES — vandalism/arson (~10/mo)
    ("Vandalism",                True,  lambda: make_case(offense="Vandalism (M)", crime_type="Property Crime")),
    ("Arson",                    True,  lambda: make_case(offense="Arson (F)", crime_type="Property Crime")),
    # YES — suspicious activity (~60/mo, tight 0.25mi radius)
    ("Suspicious Person",        True,  lambda: make_incident(call_type="Suspicious Person", call_type_desc="Suspicious Circumstances")),
    ("Prowler",                  True,  lambda: make_incident(call_type="Prowler", call_type_desc="Suspicious Circumstances")),
    ("Trespass",                 True,  lambda: make_incident(call_type="Trespass", call_type_desc="Other Calls for Service")),
    # NO — excluded store theft (~40/mo)
    ("Shoplift",                 False, lambda: make_case(offense="Shoplift (M)", crime_type="Theft")),
    ("Petty Theft",              False, lambda: make_case(offense="Petty Theft (M)", crime_type="Theft")),
    ("484 Theft",                False, lambda: make_case(offense="484 Theft (M)", crime_type="Theft")),
    # NO — excluded burglary alarms (~67/mo)
    ("ALARM - BURGLARY",         False, lambda: make_incident(call_type="ALARM - BURGLARY", call_type_desc="Alarm Responses")),
    ("Burglary Alarm",           False, lambda: make_incident(call_type="Burglary Alarm", call_type_desc="Alarm Responses")),
    # NO — non-property crimes (~1000+/mo)
    ("Traffic Stop",             False, lambda: make_incident(call_type="Traffic Stop", call_type_desc="Traffic")),
    ("Medical Aid",              False, lambda: make_incident(call_type="Medical Aid", call_type_desc="Medical")),
    ("Welfare Check",            False, lambda: make_incident(call_type="Welfare Check", call_type_desc="Other Calls for Service")),
    ("Assault",                  False, lambda: make_case(offense="Assault (F)", crime_type="Violent Crime")),
    ("DUI",                      False, lambda: make_incident(call_type="DUI", call_type_desc="Traffic")),
    ("Noise Complaint",          False, lambda: make_incident(call_type="Noise Complaint", call_type_desc="Other Calls for Service")),
    ("Suspicious Circumstances", False, lambda: make_incident(call_type="Suspicious Circumstances", call_type_desc="Suspicious Circumstances")),
    ("Drug paraphernalia",       False, lambda: make_case(offense="Possess unlawful paraphernalia (M)", crime_type="Drugs or Alcohol")),
]


class TestIsAlertableCrime(unittest.TestCase):
    """Data-driven: each row in ALERT_CASES becomes a test."""
    pass


# Generate a test method for each row
for _name, _expected, _builder in ALERT_CASES:
    def _make_test(builder=_builder, expected=_expected):
        def test(self):
            item = builder()
            if expected:
                self.assertTrue(is_alertable_crime(item), f"should alert")
            else:
                self.assertFalse(is_alertable_crime(item), f"should NOT alert")
        return test
    setattr(TestIsAlertableCrime, f"test_{_name.lower().replace(' ', '_').replace('-', '_')}", _make_test())


class TestDistance(unittest.TestCase):
    def test_same_point(self):
        self.assertAlmostEqual(haversine_m(37.448, -122.177, 37.448, -122.177), 0, places=1)

    def test_menlo_oaks_to_downtown(self):
        dist = haversine_m(37.448, -122.177, 37.459, -122.150)
        self.assertGreater(dist, 2000)
        self.assertLess(dist, 3000)

    def test_within_3mi(self):
        item = make_incident(lat=37.448, lng=-122.177)
        within, dist = item_within_menlo_oaks(item)
        self.assertTrue(within)

    def test_outside_3mi(self):
        item = make_incident(lat=37.77, lng=-122.42)
        within, _ = item_within_menlo_oaks(item)
        self.assertFalse(within)

    def test_missing_coords(self):
        item = make_incident(lat=None, lng=None)
        within, _ = item_within_menlo_oaks(item)
        self.assertFalse(within)


class TestTieredRadius(unittest.TestCase):
    """Property crimes: 3mi. Suspicious/prowler/trespass: 0.25mi."""

    def test_constants(self):
        self.assertEqual(THREE_MILES_M, 4828)
        self.assertEqual(QUARTER_MILE_M, 402)

    def test_suspicious_at_1mi_filtered(self):
        dist = haversine_m(MENLO_OAKS_LAT + 0.0145, MENLO_OAKS_LNG, MENLO_OAKS_LAT, MENLO_OAKS_LNG)
        self.assertGreater(dist, QUARTER_MILE_M)
        self.assertLess(dist, THREE_MILES_M)

    def test_suspicious_at_200m_alerts(self):
        dist = haversine_m(MENLO_OAKS_LAT + 0.0018, MENLO_OAKS_LNG, MENLO_OAKS_LAT, MENLO_OAKS_LNG)
        self.assertLess(dist, QUARTER_MILE_M)

    def test_burglary_at_2mi_alerts(self):
        dist = haversine_m(MENLO_OAKS_LAT + 0.029, MENLO_OAKS_LNG, MENLO_OAKS_LAT, MENLO_OAKS_LNG)
        self.assertLess(dist, THREE_MILES_M)


class TestItemId(unittest.TestCase):
    def test_incident_id(self):
        self.assertEqual(item_id(make_incident(prefix="atherton")), "inc-atherton-202601010001")

    def test_case_id(self):
        self.assertEqual(item_id(make_case(prefix="menlopark")), "case-menlopark-26-001")


class TestCrimeText(unittest.TestCase):
    def test_incident_fields(self):
        ct = crime_text(make_incident(call_type="Suspicious Person", call_type_desc="Suspicious Circumstances"))
        self.assertIn("Suspicious Person", ct)
        self.assertIn("Suspicious Circumstances", ct)

    def test_case_fields(self):
        ct = crime_text(make_case(offense="Burglary - Residential (F)", crime_type="Burglary", classification="Felony"))
        self.assertIn("Burglary", ct)
        self.assertIn("Felony", ct)

    def test_empty_fields(self):
        self.assertEqual(crime_text(make_incident(call_type="Traffic Stop", call_type_desc="")), "Traffic Stop")


if __name__ == "__main__":
    unittest.main()
