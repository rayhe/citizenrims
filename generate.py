#!/usr/bin/env python3
"""
Fetches crime data from CitizenRIMS and writes static JSON files to public/.
Designed to run in GitHub Actions on a cron schedule.
"""

import json
import math
import os
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError

API_BASE = "https://api.v1.citizenrims.com"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "public")
ALERTED_PATH = os.path.join(BASE_DIR, "alerted.json")

AGENCIES = ["menlopark", "atherton", "smcsheriff"]

PA_BASE = "https://gis.cityofpaloalto.org/server/rest/services/PublicSafety/AgencyCommonEvent/MapServer/2/query"

MENLO_OAKS_LAT = 37.448
MENLO_OAKS_LNG = -122.177
THREE_MILES_M = 4828

PROPERTY_RE = re.compile(
    r"burglary|larceny|theft|fraud|stolen|shoplift|embezzle|forgery|identity|vandal|arson",
    re.IGNORECASE,
)

ALERT_RECIPIENTS = [
    r.strip() for r in os.environ.get("ALERT_RECIPIENTS", "").split(",") if r.strip()
]

MAP_URL = "https://rayhe.github.io/citizenrims/public/"


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


def haversine_m(lat1, lon1, lat2, lon2):
    """Distance in meters between two lat/lng points."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def item_id(item):
    """Unique key for an incident/case."""
    src = item.get("_source", "")
    if src == "incident":
        return f"inc-{item.get('_prefix', '')}-{item.get('incidentNumber', '')}"
    return f"case-{item.get('_prefix', '')}-{item.get('caseNumber', '')}"


def crime_text(item):
    return " ".join(filter(None, [
        item.get("callType"), item.get("callTypeDescription"),
        item.get("crimeType"), item.get("crimeClassification"),
        item.get("offenseDescription1"),
    ]))


def is_property_crime(item):
    return bool(PROPERTY_RE.search(crime_text(item)))


def item_within_menlo_oaks(item):
    lat = item.get("yCoord")
    lng = item.get("xCoord")
    if lat is None or lng is None:
        return False, 0
    dist = haversine_m(lat, lng, MENLO_OAKS_LAT, MENLO_OAKS_LNG)
    return dist <= THREE_MILES_M, dist


def load_alerted():
    if os.path.exists(ALERTED_PATH):
        with open(ALERTED_PATH) as f:
            return set(json.load(f))
    return set()


def save_alerted(ids):
    with open(ALERTED_PATH, "w") as f:
        json.dump(sorted(ids), f)


def send_alert(item, dist_m):
    smtp_user = os.environ.get("ALERT_EMAIL_USER", "")
    smtp_pass = os.environ.get("ALERT_EMAIL_PASSWORD", "")
    if not smtp_user or not smtp_pass:
        print("    SKIP email: ALERT_EMAIL_USER / ALERT_EMAIL_PASSWORD not set")
        return
    if not ALERT_RECIPIENTS:
        print("    SKIP email: ALERT_RECIPIENTS not set")
        return

    src = item.get("_source", "")
    agency = item.get("_agency", "Unknown")
    street = item.get("street", "Unknown location")
    city = item.get("city", "")
    location = f"{street}, {city}" if city else street
    dist_mi = dist_m / 1609.34

    if src == "incident":
        crime = item.get("callTypeDescription") or item.get("callType") or "Property Crime"
        date_raw = item.get("incidentDate", "")
        time_raw = item.get("incidentTime", "")
    else:
        crime = item.get("offenseDescription1") or item.get("crimeType") or "Property Crime"
        date_raw = item.get("reportDate") or item.get("occurrence1Date", "")
        time_raw = ""

    ct = crime_text(item)
    severity = "High"
    if re.search(r"burglary|stolen vehicle|arson", ct, re.IGNORECASE):
        severity = "High"
    elif re.search(r"theft|shoplift|fraud|larceny", ct, re.IGNORECASE):
        severity = "Medium"
    elif re.search(r"vandal|forgery|identity|embezzle", ct, re.IGNORECASE):
        severity = "Medium"

    # Short location for subject line
    short_loc = street or city or "Unknown"
    subject = f"{crime} near {short_loc} — {dist_mi:.1f}mi from Menlo Oaks ({severity})"

    # Format date nicely
    date_display = date_raw
    if date_raw:
        try:
            dt = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
            date_display = dt.strftime("%b %d, %Y %I:%M %p UTC")
        except Exception:
            pass

    html = f"""\
<div style="font-family:system-ui,-apple-system,sans-serif;max-width:520px;margin:0 auto">
  <div style="background:linear-gradient(135deg,#1a1a2e,#2d2d50);color:#fff;padding:16px 20px;border-radius:10px 10px 0 0">
    <h2 style="margin:0;font-size:18px">Property Crime Alert</h2>
    <p style="margin:4px 0 0;color:#9a9ab0;font-size:13px">{dist_mi:.1f} miles from Menlo Oaks</p>
  </div>
  <div style="background:#fff;padding:20px;border:1px solid #e0e0e0;border-top:none;border-radius:0 0 10px 10px">
    <table style="width:100%;border-collapse:collapse;font-size:14px;color:#333">
      <tr>
        <td style="padding:8px 0;color:#888;width:100px;vertical-align:top">Type</td>
        <td style="padding:8px 0;font-weight:600">{crime}</td>
      </tr>
      <tr>
        <td style="padding:8px 0;color:#888;vertical-align:top">Severity</td>
        <td style="padding:8px 0"><span style="background:{'#d32f2f' if severity == 'High' else '#e65100'};color:#fff;padding:2px 10px;border-radius:10px;font-size:12px;font-weight:600">{severity}</span></td>
      </tr>
      <tr>
        <td style="padding:8px 0;color:#888;vertical-align:top">Location</td>
        <td style="padding:8px 0">{location}</td>
      </tr>
      <tr>
        <td style="padding:8px 0;color:#888;vertical-align:top">Distance</td>
        <td style="padding:8px 0">{dist_mi:.1f} miles from Menlo Oaks</td>
      </tr>
      <tr>
        <td style="padding:8px 0;color:#888;vertical-align:top">Agency</td>
        <td style="padding:8px 0">{agency}</td>
      </tr>
      <tr>
        <td style="padding:8px 0;color:#888;vertical-align:top">Date</td>
        <td style="padding:8px 0">{date_display}{(' ' + time_raw) if time_raw else ''}</td>
      </tr>
    </table>
    <div style="margin-top:16px;text-align:center">
      <a href="{MAP_URL}" style="display:inline-block;background:#1a1a2e;color:#fff;padding:10px 28px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px">View on Map</a>
    </div>
  </div>
  <p style="text-align:center;color:#aaa;font-size:11px;margin-top:12px">Crime Feed — Menlo Park, Atherton, Palo Alto &amp; SMC Sheriff</p>
</div>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = ", ".join(ALERT_RECIPIENTS)

    plain = f"{crime}\n{location}\n{agency}\nDistance: {dist_mi:.1f}mi from Menlo Oaks\nDate: {date_display}\nSeverity: {severity}\n\nView map: {MAP_URL}"
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(smtp_user, smtp_pass)
            s.sendmail(smtp_user, ALERT_RECIPIENTS, msg.as_string())
        print(f"    Sent alert: {subject}")
    except Exception as e:
        print(f"    WARN: email failed: {e}")


def check_alerts(all_incidents, all_cases):
    alerted = load_alerted()
    all_items = all_incidents + all_cases
    new_alerts = 0

    for item in all_items:
        iid = item_id(item)
        if iid in alerted:
            continue
        if not is_property_crime(item):
            continue
        within, dist = item_within_menlo_oaks(item)
        if not within:
            continue

        print(f"  NEW ALERT: {crime_text(item)} at {item.get('street', '?')} ({dist/1609.34:.1f}mi)")
        send_alert(item, dist)
        alerted.add(iid)
        new_alerts += 1

    save_alerted(alerted)
    print(f"  Alerts: {new_alerts} new, {len(alerted)} total tracked")


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

    print("Checking alerts...")
    check_alerts(all_incidents, all_cases)

    print("Done.")


if __name__ == "__main__":
    main()
