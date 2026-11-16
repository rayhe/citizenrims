"""Writes the small, fixed data snapshot the integration tests load.

Run from the repo root:  python3 tests/fixtures/make_fixtures.py
The tests pin "now" to 2026-11-16 12:00 PST, so the dates below are relative to that.
Expected counts (asserted in tests/site.test.js):
  burglary, all time, Menlo Oaks 3mi : 6  (3 incidents + 3 cases)
  burglary, all time, no geo         : 7  (adds one case far from Menlo Oaks)
  everything, default 7 days         : 5  (4 incidents + 1 case), from the 2026-11 file only
"""
import json
import os

OUT = os.path.dirname(os.path.abspath(__file__))

INSIDE = (37.4660, -122.1680)   # inside the Menlo Oaks polygon
NEAR = (37.4700, -122.1550)     # ~0.6 mi east, inside the 3 mi radius
FAR = (37.5600, -122.3200)      # Redwood Shores area, well outside 3 mi

AGENCY = {
    "menlopark": "Menlo Park Police Department",
    "atherton": "Atherton Police Department",
    "paloalto": "Palo Alto Police Department",
    "smcsheriff": "San Mateo County Sheriff's Office",
    "redwoodcity": "Redwood City Police Department",
}


def incident(num, prefix, where, date, time, call_type, desc, street="MAIN ST"):
    return {
        "incidentNumber": num, "street": street, "city": "MENLO PARK",
        "incidentDate": date, "incidentTime": time,
        "yCoord": where[0], "xCoord": where[1],
        "callType": call_type, "callTypeDescription": desc,
        "_source": "incident", "_agency": AGENCY[prefix], "_prefix": prefix,
    }


def case(num, prefix, where, report, occ_date, occ_time, crime, offense):
    return {
        "caseNumber": num, "reportDate": report,
        "occurrence1Date": occ_date, "occurrence1Time": occ_time,
        "street": "OAK AV", "blockNumber": 100, "city": "Menlo Park",
        "yCoord": where[0], "xCoord": where[1],
        "crimeType": crime, "offenseDescription1": offense, "crimeClassification": "Felony",
        "_source": "case", "_agency": AGENCY[prefix], "_prefix": prefix,
    }


BURG = "459 PC Burglary:first degree"
months = {
    "2026-09": {
        "incidents": [
            incident("I1", "menlopark", INSIDE, "2026-09-10T00:00:00", "03:15:00", "459 PC - BURGLARY", "Burglary"),
        ],
        "cases": [
            # occurrence time 0000 is treated as "time unknown"
            case("C1", "smcsheriff", NEAR, "2026-09-20T00:00:00", "2026-09-19T00:00:00", 0, "Burglary", BURG),
        ],
    },
    "2026-10": {
        "incidents": [
            incident("I2", "atherton", NEAR, "2026-10-05T00:00:00", "14:20:00", "459 PC - BURGLARY", "Burglary"),
            incident("I3", "menlopark", NEAR, "2026-10-20T00:00:00", "08:00:00", "BURGLARY ALARM", "Alarm"),
        ],
        "cases": [
            case("C2", "menlopark", NEAR, "2026-10-12T00:00:00", "2026-10-11T00:00:00", 2230, "Burglary", BURG),
            case("C3", "redwoodcity", FAR, "2026-10-15T00:00:00", "2026-10-15T00:00:00", 1100, "Burglary", BURG),
        ],
    },
    "2026-11": {
        "incidents": [
            incident("I8", "menlopark", NEAR, "2026-11-01T00:00:00", "10:00:00", "WELFARE CHECK", "Welfare"),
            incident("I4", "menlopark", INSIDE, "2026-11-14T00:00:00", "21:45:00", "459 PC - BURGLARY", "Burglary"),
            # Palo Alto times are UTC: 19:30Z is 11:30 AM Pacific
            {**incident("I5", "paloalto", NEAR, "2026-11-15T19:30:00Z", "19:30:00", "PETTY THEFT", "Theft"), "city": "Palo Alto"},
            incident("I6", "menlopark", NEAR, "2026-11-15T00:00:00", "13:05:00", "TRAFFIC STOP", "Traffic"),
            incident("I7", "menlopark", INSIDE, "2026-11-15T00:00:00", "09:00:00", "SUSPICIOUS <b>PERSON</b>", "Suspicious",
                     street='<img src=x onerror="window.__xss=1">OAK AV'),
        ],
        "cases": [
            case("C4", "menlopark", NEAR, "2026-11-13T00:00:00", "2026-11-12T00:00:00", None, "Burglary", BURG),
        ],
    },
}

os.makedirs(os.path.join(OUT, "data"), exist_ok=True)
for month, data in months.items():
    with open(os.path.join(OUT, "data", f"{month}.json"), "w") as f:
        json.dump({"meta": {"month": month}, **data}, f, indent=1)

n_inc = sum(len(d["incidents"]) for d in months.values())
n_case = sum(len(d["cases"]) for d in months.values())
meta = {
    "generated_at": "2026-11-16T19:00:00+00:00", "days": 31,
    "agencies": list(AGENCY), "incident_count": n_inc, "case_count": n_case,
}
with open(os.path.join(OUT, "manifest.json"), "w") as f:
    json.dump({"meta": meta, "months": sorted(months)}, f, indent=1)
with open(os.path.join(OUT, "feed.json"), "w") as f:
    json.dump({"meta": {**meta, "split": "monthly", "manifest": "manifest.json"}, "incidents": [], "cases": []}, f, indent=1)
with open(os.path.join(OUT, "arrests.json"), "w") as f:
    json.dump({"meta": {"generated_at": meta["generated_at"]}, "arrests": [
        {"arrestDate": "2026-11-14T00:00:00", "fullName": "Doe, <i>Jane</i>", "age": 30, "sex": "Female",
         "street": "MAIN ST", "chargeDescription1": "Burglary", "caseNumber": "26-1",
         "_agency": AGENCY["menlopark"], "_prefix": "menlopark"},
    ]}, f, indent=1)
print("wrote fixtures to", OUT)
