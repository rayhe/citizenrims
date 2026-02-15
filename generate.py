#!/usr/bin/env python3
"""
Fetches crime data from CitizenRIMS and writes static JSON files to public/.
Designed to run in GitHub Actions on a cron schedule.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError

API_BASE = "https://api.v1.citizenrims.com"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")

AGENCIES = ["menlopark", "atherton", "smcsheriff"]

PA_BASE = "https://gis.cityofpaloalto.org/server/rest/services/PublicSafety/AgencyCommonEvent/MapServer/2/query"


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


def fetch_paloalto(days):
    """Fetch incidents from Palo Alto's ArcGIS REST endpoint."""
    cutoff = datetime.now() - timedelta(days=days)
    where = f"CALLTIME >= TIMESTAMP '{cutoff.strftime('%Y-%m-%d %H:%M:%S')}'"

    all_features = []
    offset = 0
    batch = 1000
    while True:
        params = urlencode({
            "where": where,
            "outFields": "*",
            "f": "json",
            "resultRecordCount": batch,
            "resultOffset": offset,
            "returnGeometry": "true",
            "outSR": "4326",
        })
        url = f"{PA_BASE}?{params}"
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        features = data.get("features", [])
        all_features.extend(features)
        if not data.get("exceededTransferLimit") or len(features) < batch:
            break
        offset += len(features)

    incidents = []
    for feat in all_features:
        attr = feat.get("attributes", {})
        geom = feat.get("geometry", {})

        # Compute centroid from polygon rings
        rings = geom.get("rings", [])
        if rings and rings[0]:
            xs = [p[0] for p in rings[0]]
            ys = [p[1] for p in rings[0]]
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)
        else:
            cx, cy = None, None

        call_time = attr.get("CALLTIME")
        if call_time:
            dt = datetime.fromtimestamp(call_time / 1000, tz=timezone.utc)
            inc_date = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            inc_time = dt.strftime("%H:%M:%S")
        else:
            inc_date, inc_time = None, None

        incidents.append({
            "incidentNumber": attr.get("INCIDENTNUMBER", ""),
            "street": attr.get("CROSSSTREET", ""),
            "city": "Palo Alto",
            "status": attr.get("INCIDENTSTATUS", ""),
            "incidentDate": inc_date,
            "incidentTime": inc_time,
            "xCoord": cx,
            "yCoord": cy,
            "callType": attr.get("CALLTYPE", ""),
            "callTypeDescription": attr.get("CALLTYPEDESCRIPTION", ""),
            "callSubtype": attr.get("CALLSUBTYPE", ""),
            "callSubtypeDescription": attr.get("CALLSUBTYPEDESCRIPTION", ""),
            "_source": "incident",
            "_agency": "Palo Alto Police Department",
            "_prefix": "paloalto",
        })

    return incidents


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

    print("  paloalto (ArcGIS)...")
    try:
        pa_incidents = fetch_paloalto(days)
        all_incidents.extend(pa_incidents)
        print(f"    {len(pa_incidents)} incidents")
    except Exception as e:
        print(f"  WARN: Palo Alto fetch failed: {e}")

    all_agencies = AGENCIES + ["paloalto"]

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "agencies": all_agencies,
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
