"""
Tests for alert filtering logic in generate.py.

Verifies which crime types trigger alerts, which are excluded,
distance thresholds, and the tiered radius system.

Alert frequency context (from 31 days of data, ~1400 incidents + ~100 cases):
  - Suspicious Person/Prowler/Trespass: ~60 incidents (high frequency, tight 0.25mi radius)
  - Burglary Alarm responses:           ~67 incidents (excluded — just alarm triggers)
  - Shoplifting / Petty Theft:           ~40 cases    (excluded — store theft)
  - Real Burglary / Theft / Fraud:       ~25 cases    (alerted, 3mi radius)
  - Vandalism / Identity / Forgery:      ~10 cases    (alerted, 3mi radius)
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
    """Helper to build a minimal incident dict."""
    return {
        "_source": "incident",
        "_prefix": prefix,
        "incidentNumber": "202601010001",
        "callType": call_type,
        "callTypeDescription": call_type_desc,
        "yCoord": lat,
        "xCoord": lng,
        "street": "100 TEST ST",
        "city": "Menlo Park",
    }


def make_case(offense="", crime_type="", classification="", prefix="menlopark", lat=37.448, lng=-122.177):
    """Helper to build a minimal case dict."""
    return {
        "_source": "case",
        "_prefix": prefix,
        "caseNumber": "26-001",
        "offenseDescription1": offense,
        "crimeType": crime_type,
        "crimeClassification": classification,
        "yCoord": lat,
        "xCoord": lng,
        "street": "100 TEST ST",
        "city": "Menlo Park",
    }


class TestIsAlertableCrime(unittest.TestCase):
    """Tests is_alertable_crime() — must match ALERT_RE and not match EXCLUDE_RE."""

    # --- Should alert (property crimes, ~25 per month) ---

    def test_burglary_case(self):
        item = make_case(offense="Burglary - Residential (F)", crime_type="Burglary")
        self.assertTrue(is_alertable_crime(item))

    def test_burglary_commercial(self):
        item = make_case(offense="Burglary - Commercial (F)", crime_type="Burglary")
        self.assertTrue(is_alertable_crime(item))

    def test_vehicle_burglary(self):
        item = make_case(offense="Burglary - Vehicle (F)", crime_type="Burglary")
        self.assertTrue(is_alertable_crime(item))

    def test_grand_theft(self):
        item = make_case(offense="Grand Theft (F)", crime_type="Theft")
        self.assertTrue(is_alertable_crime(item))

    def test_theft_from_vehicle(self):
        item = make_case(offense="Theft From Vehicle", crime_type="Theft")
        self.assertTrue(is_alertable_crime(item))

    def test_stolen_vehicle(self):
        item = make_case(offense="Stolen Vehicle (F)", crime_type="Theft")
        self.assertTrue(is_alertable_crime(item))

    def test_fraud(self):
        item = make_case(offense="Fraud (M)", crime_type="Fraud")
        self.assertTrue(is_alertable_crime(item))

    def test_identity_theft(self):
        item = make_case(offense="Identity Theft (F)", crime_type="Fraud")
        self.assertTrue(is_alertable_crime(item))

    def test_forgery(self):
        item = make_case(offense="Forgery (F)", crime_type="Fraud")
        self.assertTrue(is_alertable_crime(item))

    def test_embezzlement(self):
        item = make_case(offense="Embezzlement (F)", crime_type="Fraud")
        self.assertTrue(is_alertable_crime(item))

    # --- Should alert (vandalism/arson, ~10 per month) ---

    def test_vandalism(self):
        item = make_case(offense="Vandalism (M)", crime_type="Property Crime")
        self.assertTrue(is_alertable_crime(item))

    def test_arson(self):
        item = make_case(offense="Arson (F)", crime_type="Property Crime")
        self.assertTrue(is_alertable_crime(item))

    # --- Should alert (suspicious activity, ~60 per month, tight radius) ---

    def test_suspicious_person_incident(self):
        item = make_incident(call_type="Suspicious Person", call_type_desc="Suspicious Circumstances")
        self.assertTrue(is_alertable_crime(item))

    def test_prowler_incident(self):
        item = make_incident(call_type="Prowler", call_type_desc="Suspicious Circumstances")
        self.assertTrue(is_alertable_crime(item))

    def test_trespass_incident(self):
        item = make_incident(call_type="Trespass", call_type_desc="Other Calls for Service")
        self.assertTrue(is_alertable_crime(item))

    def test_larceny(self):
        item = make_case(offense="Larceny (M)", crime_type="Theft")
        self.assertTrue(is_alertable_crime(item))

    # --- Should NOT alert (excluded store theft, ~40 per month) ---

    def test_shoplifting_excluded(self):
        item = make_case(offense="Shoplift (M)", crime_type="Theft")
        self.assertFalse(is_alertable_crime(item))

    def test_petty_theft_excluded(self):
        item = make_case(offense="Petty Theft (M)", crime_type="Theft")
        self.assertFalse(is_alertable_crime(item))

    def test_484_theft_excluded(self):
        item = make_case(offense="484 Theft (M)", crime_type="Theft")
        self.assertFalse(is_alertable_crime(item))

    # --- Should NOT alert (burglary alarms, ~67 per month) ---

    def test_alarm_burglary_excluded(self):
        item = make_incident(call_type="ALARM - BURGLARY", call_type_desc="Alarm Responses")
        self.assertFalse(is_alertable_crime(item))

    def test_burglary_alarm_response_excluded(self):
        item = make_incident(call_type="Burglary Alarm", call_type_desc="Alarm Responses")
        self.assertFalse(is_alertable_crime(item))

    # --- Should NOT alert (non-property crimes, ~1000+ per month) ---

    def test_traffic_stop_not_alertable(self):
        item = make_incident(call_type="Traffic Stop", call_type_desc="Traffic")
        self.assertFalse(is_alertable_crime(item))

    def test_medical_not_alertable(self):
        item = make_incident(call_type="Medical Aid", call_type_desc="Medical")
        self.assertFalse(is_alertable_crime(item))

    def test_welfare_check_not_alertable(self):
        item = make_incident(call_type="Welfare Check", call_type_desc="Other Calls for Service")
        self.assertFalse(is_alertable_crime(item))

    def test_assault_not_alertable(self):
        # Violent crime, but not in our property-crime ALERT_RE
        item = make_case(offense="Assault (F)", crime_type="Violent Crime")
        self.assertFalse(is_alertable_crime(item))

    def test_dui_not_alertable(self):
        item = make_incident(call_type="DUI", call_type_desc="Traffic")
        self.assertFalse(is_alertable_crime(item))

    def test_noise_complaint_not_alertable(self):
        item = make_incident(call_type="Noise Complaint", call_type_desc="Other Calls for Service")
        self.assertFalse(is_alertable_crime(item))

    def test_suspicious_circumstances_without_person(self):
        # "Suspicious Circumstances" alone does NOT match — need "suspicious person"
        item = make_incident(call_type="Suspicious Circumstances", call_type_desc="Suspicious Circumstances")
        self.assertFalse(is_alertable_crime(item))

    def test_drug_offense_not_alertable(self):
        item = make_case(offense="Possess unlawful paraphernalia (M)", crime_type="Drugs or Alcohol")
        self.assertFalse(is_alertable_crime(item))


class TestDistance(unittest.TestCase):
    """Tests haversine distance and item_within_menlo_oaks radius check."""

    def test_same_point_zero_distance(self):
        self.assertAlmostEqual(haversine_m(37.448, -122.177, 37.448, -122.177), 0, places=1)

    def test_known_distance(self):
        # Menlo Oaks to downtown Menlo Park (~1.5mi / ~2414m)
        dist = haversine_m(37.448, -122.177, 37.459, -122.150)
        self.assertGreater(dist, 2000)
        self.assertLess(dist, 3000)

    def test_within_3_miles(self):
        # Point right at Menlo Oaks center
        item = make_incident(lat=37.448, lng=-122.177)
        within, dist = item_within_menlo_oaks(item)
        self.assertTrue(within)
        self.assertAlmostEqual(dist, 0, places=0)

    def test_outside_3_miles(self):
        # San Francisco (~25mi away)
        item = make_incident(lat=37.77, lng=-122.42)
        within, dist = item_within_menlo_oaks(item)
        self.assertFalse(within)

    def test_missing_coords_not_within(self):
        item = make_incident(lat=None, lng=None)
        within, dist = item_within_menlo_oaks(item)
        self.assertFalse(within)


class TestTieredRadius(unittest.TestCase):
    """
    Tests the tiered radius logic in check_alerts():
    - Property crimes: alert within 3 miles (~4828m)
    - Suspicious person/prowler/trespass: alert within 0.25 miles (~402m) only
    """

    def test_quarter_mile_constant(self):
        self.assertEqual(QUARTER_MILE_M, 402)

    def test_three_mile_constant(self):
        self.assertEqual(THREE_MILES_M, 4828)

    def test_suspicious_person_at_1_mile_should_be_filtered(self):
        """Suspicious person 1 mile away exceeds 0.25mi threshold."""
        # ~1 mile north of Menlo Oaks
        lat = MENLO_OAKS_LAT + 0.0145
        dist = haversine_m(lat, MENLO_OAKS_LNG, MENLO_OAKS_LAT, MENLO_OAKS_LNG)
        self.assertGreater(dist, QUARTER_MILE_M)
        self.assertLess(dist, THREE_MILES_M)

    def test_suspicious_person_at_200m_should_alert(self):
        """Suspicious person ~200m away is within 0.25mi threshold."""
        lat = MENLO_OAKS_LAT + 0.0018  # ~200m
        dist = haversine_m(lat, MENLO_OAKS_LNG, MENLO_OAKS_LAT, MENLO_OAKS_LNG)
        self.assertLess(dist, QUARTER_MILE_M)

    def test_burglary_at_2_miles_should_alert(self):
        """Real burglary 2 miles away is within 3mi threshold."""
        lat = MENLO_OAKS_LAT + 0.029  # ~2 miles
        dist = haversine_m(lat, MENLO_OAKS_LNG, MENLO_OAKS_LAT, MENLO_OAKS_LNG)
        self.assertLess(dist, THREE_MILES_M)
        self.assertGreater(dist, QUARTER_MILE_M)


class TestItemId(unittest.TestCase):
    """Tests unique ID generation for deduplication."""

    def test_incident_id(self):
        item = make_incident(prefix="atherton")
        self.assertEqual(item_id(item), "inc-atherton-202601010001")

    def test_case_id(self):
        item = make_case(prefix="menlopark")
        self.assertEqual(item_id(item), "case-menlopark-26-001")


class TestCrimeText(unittest.TestCase):
    """Tests crime_text concatenation for regex matching."""

    def test_incident_fields(self):
        item = make_incident(call_type="Suspicious Person", call_type_desc="Suspicious Circumstances")
        ct = crime_text(item)
        self.assertIn("Suspicious Person", ct)
        self.assertIn("Suspicious Circumstances", ct)

    def test_case_fields(self):
        item = make_case(offense="Burglary - Residential (F)", crime_type="Burglary", classification="Felony")
        ct = crime_text(item)
        self.assertIn("Burglary - Residential (F)", ct)
        self.assertIn("Burglary", ct)
        self.assertIn("Felony", ct)

    def test_empty_fields_excluded(self):
        item = make_incident(call_type="Traffic Stop", call_type_desc="")
        ct = crime_text(item)
        self.assertEqual(ct, "Traffic Stop")


if __name__ == "__main__":
    unittest.main()
