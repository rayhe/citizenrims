#!/usr/bin/env python3
"""
Fetches crime data from CitizenRIMS and writes static JSON files to public/.
Designed to run in GitHub Actions on a cron schedule.
"""

import json
import os
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError

API_BASE = "https://api.v1.citizenrims.com"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")

AGENCIES = ["menlopark", "atherton", "smcsheriff"]


def get_token():
    req = Request(
        f"{API_BASE}/api/v1/auth/citizen",
        method="POST",
        headers={"Content-Length": "0"},
        data=b"",
    )
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())["token"]


def api_get(path, params, token):
    url = f"{API_BASE}{path}?{urlencode(params)}"
    req = Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def date_str(dt):
    return dt.strftime("%a %b %d %Y")


def fetch_agency(prefix, token, days):
    config = api_get(
        "/api/v1/AgencyConfig/AgencyConfigGetByUrlPrefix",
        {"citizenRimsUrlPrefix": prefix},
        token,
    )
    end = datetime.now()
    start = end - timedelta(days=days)
    agency_name = config.get("agencySiteName", prefix)
    agency_id = config["agencyId"]
    primary_id = config["primaryAgencyId"]
    lat = config.get("defaultLatitude", 37.5)
    lng = config.get("defaultLongitude", -122.2)

    incidents = []
    if config.get("incidentsEnabled"):
        groups = config.get("incidentMarkerGroups", [])
        if groups:
            types = ",".join(g["groupFieldName"] for g in groups)
            try:
                items = api_get("/api/v1/Incident", {
                    "agencyId": agency_id,
                    "primaryAgencyId": primary_id,
                    "startDate": date_str(start),
                    "endDate": date_str(end),
                    "types": types,
                    "circleLatitude": lat,
                    "circleLongitude": lng,
                    "circleRadius": 50000,
                }, token)
                for item in items:
                    item["_source"] = "incident"
                    item["_agency"] = agency_name
                    item["_prefix"] = prefix
                incidents = items
            except HTTPError as e:
                print(f"  WARN: incidents failed for {prefix}: {e}")

    cases = []
    if config.get("caseDataEnabled"):
        groups = config.get("caseMarkerGroups", [])
        if groups:
            types = ",".join(g["groupFieldName"] for g in groups)
            try:
                items = api_get("/api/v1/Case", {
                    "agencyId": agency_id,
                    "primaryAgencyId": primary_id,
                    "startDate": date_str(start),
                    "endDate": date_str(end),
                    "types": types,
                    "circleLatitude": lat,
                    "circleLongitude": lng,
                    "circleRadius": 50000,
                }, token)
                for item in items:
                    item["_source"] = "case"
                    item["_agency"] = agency_name
                    item["_prefix"] = prefix
                cases = items
            except HTTPError as e:
                print(f"  WARN: cases failed for {prefix}: {e}")

    return incidents, cases


def main():
    days = int(os.environ.get("DAYS", "7"))
    print(f"Fetching {days} days of data...")

    token = get_token()

    all_incidents = []
    all_cases = []

    for prefix in AGENCIES:
        print(f"  {prefix}...")
        incidents, cases = fetch_agency(prefix, token, days)
        all_incidents.extend(incidents)
        all_cases.extend(cases)
        print(f"    {len(incidents)} incidents, {len(cases)} cases")

    meta = {
        "generated_at": datetime.now().isoformat(),
        "days": days,
        "agencies": AGENCIES,
        "incident_count": len(all_incidents),
        "case_count": len(all_cases),
    }

    os.makedirs(OUT_DIR, exist_ok=True)

    def write(name, data):
        path = os.path.join(OUT_DIR, name)
        with open(path, "w") as f:
            json.dump(data, f, separators=(",", ":"), default=str)
        print(f"  Wrote {path} ({os.path.getsize(path)} bytes)")

    write("feed.json", {"meta": meta, "incidents": all_incidents, "cases": all_cases})
    write("incidents.json", {"meta": meta, "incidents": all_incidents})
    write("cases.json", {"meta": meta, "cases": all_cases})

    print("Done.")


if __name__ == "__main__":
    main()
