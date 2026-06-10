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
import subprocess
import time
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from http.client import IncompleteRead

API_BASE = "https://api.v1.citizenrims.com"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "public")
ALERTED_PATH = os.path.join(BASE_DIR, "alerted.json")
ALERT_LOG_PATH = os.path.join(BASE_DIR, "alert_log.json")

AGENCIES = ["menlopark", "atherton", "smcsheriff", "redwoodcity"]

PA_BASE = "https://gis.cityofpaloalto.org/server/rest/services/PublicSafety/AgencyCommonEvent/MapServer/2/query"

MENLO_OAKS_POLY = [
    (37.4717, -122.1680),  # NW: Bay Rd & Ringwood Ave
    (37.4700, -122.1616),  # NE: Bay Rd & Perimeter Rd (VA campus)
    (37.4629, -122.1651),  # E:  Coleman Ave & Perimeter Rd
    (37.4636, -122.1673),  # SE: Coleman Ave & Berkeley Ave
    (37.4599, -122.1706),  # S:  South of Arlington Way
    (37.4611, -122.1732),  # SW: Ringwood Ave & Arlington Way
]
THREE_MILES_M = 4828
QUARTER_MILE_M = 402

ALERT_RE = re.compile(
    r"burglary|larceny|theft|fraud|stolen|shoplift|embezzle|forgery|identity|vandal|arson"
    r"|suspicious\s*person|prowler|trespass",
    re.IGNORECASE,
)
# Exclude noise from alerts
EXCLUDE_RE = re.compile(
    r"shoplift|petty.theft|484\s*theft|alarm.{0,5}burglary|burglary.{0,5}alarm",
    re.IGNORECASE,
)

def load_config():
    """Decrypt config.enc with CONFIG_PASSPHRASE env var. Returns dict or {}."""
    passphrase = os.environ.get("CONFIG_PASSPHRASE", "")
    if not passphrase:
        return {}
    enc_path = os.path.join(BASE_DIR, "config.enc")
    if not os.path.exists(enc_path):
        return {}
    try:
        result = subprocess.run(
            ["openssl", "enc", "-aes-256-cbc", "-d", "-pbkdf2",
             "-in", enc_path, "-pass", f"pass:{passphrase}"],
            capture_output=True, timeout=5,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass
    return {}


_config = load_config()

ALERT_RECIPIENTS = [
    r.strip() for r in
    (_config.get("ALERT_RECIPIENTS") or os.environ.get("ALERT_RECIPIENTS", "ray@rayhe.net")).split(",")
    if r.strip()
]

MAP_URL = "https://rayhe.github.io/citizenrims/public/"


def get_token():
    for attempt in range(3):
        try:
            req = Request(
                f"{API_BASE}/api/v1/auth/citizen",
                method="POST",
                headers={"Content-Length": "0"},
                data=b"",
            )
            with urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())["token"]
        except (HTTPError, URLError, ConnectionError, OSError, TimeoutError) as e:
            if attempt == 2:
                raise
            print(f"  Token retry {attempt + 1}/3 after {type(e).__name__}: {e}")
            time.sleep(2 * (attempt + 1))


def api_get(path, params, token):
    url = f"{API_BASE}{path}?{urlencode(params)}"
    req = Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def api_get_retry(path, params, token, retries=3, delay=2):
    """api_get with retry on transient network errors."""
    for attempt in range(retries):
        try:
            return api_get(path, params, token)
        except (HTTPError, URLError, ConnectionError, OSError, TimeoutError) as e:
            if attempt == retries - 1:
                raise
            print(f"    Retry {attempt + 1}/{retries} after {type(e).__name__}: {e}")
            time.sleep(delay * (attempt + 1))


def api_post(path, body, token):
    import requests as _req
    url = f"{API_BASE}{path}"
    resp = _req.post(url, json=body, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }, timeout=60)
    resp.raise_for_status()
    return resp.json()


def api_post_retry(path, body, token, retries=3, delay=2):
    """api_post with retry on transient network errors."""
    for attempt in range(retries):
        try:
            return api_post(path, body, token)
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"    Retry {attempt + 1}/{retries} after {type(e).__name__}: {e}")
            time.sleep(delay * (attempt + 1))


def date_str(dt):
    return dt.strftime("%a %b %d %Y")


def fetch_agency(prefix, token, days):
    try:
        config = api_get_retry(
            "/api/v1/AgencyConfig/AgencyConfigGetByUrlPrefix",
            {"citizenRimsUrlPrefix": prefix},
            token,
        )
    except (HTTPError, URLError, ConnectionError, OSError, TimeoutError) as e:
        print(f"  WARN: config fetch failed for {prefix}: {e}")
        return [], []
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
                items = api_get_retry("/api/v1/Incident", {
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
            except (HTTPError, URLError, ConnectionError, OSError, TimeoutError) as e:
                print(f"  WARN: incidents failed for {prefix}: {e}")

    cases = []
    if config.get("caseDataEnabled"):
        groups = config.get("caseMarkerGroups", [])
        if groups:
            types = ",".join(g["groupFieldName"] for g in groups)
            try:
                items = api_get_retry("/api/v1/Case", {
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
            except (HTTPError, URLError, ConnectionError, OSError, TimeoutError) as e:
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


def fetch_arrests(token):
    """Fetch SMC Sheriff arrests via POST API. Returns list of arrest records."""
    try:
        arrests = api_post_retry("/api/v1/Arrest/GetArrests", {"agencyId": 349}, token)
        for item in arrests:
            item["_source"] = "arrest"
            item["_agency"] = "San Mateo County Sheriff's Office"
            item["_prefix"] = "smcsheriff"
        return arrests
    except (HTTPError, URLError, ConnectionError, OSError, TimeoutError) as e:
        print(f"  WARN: arrests fetch failed: {e}")
        return []


def haversine_m(lat1, lon1, lat2, lon2):
    """Distance in meters between two lat/lng points."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def point_in_polygon(lat, lng, poly):
    """Ray casting: True if (lat, lng) is inside the polygon."""
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        yi, xi = poly[i]
        yj, xj = poly[j]
        if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _point_to_segment_m(lat, lng, lat1, lng1, lat2, lng2):
    """Minimum distance in meters from point to a line segment."""
    dx = lat2 - lat1
    dy = lng2 - lng1
    if dx == 0 and dy == 0:
        return haversine_m(lat, lng, lat1, lng1)
    t = ((lat - lat1) * dx + (lng - lng1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    proj_lat = lat1 + t * dx
    proj_lng = lng1 + t * dy
    return haversine_m(lat, lng, proj_lat, proj_lng)


def distance_to_polygon_m(lat, lng, poly):
    """Distance in meters from point to polygon. 0 if inside."""
    if point_in_polygon(lat, lng, poly):
        return 0
    n = len(poly)
    min_dist = float('inf')
    for i in range(n):
        j = (i + 1) % n
        d = _point_to_segment_m(lat, lng, poly[i][0], poly[i][1], poly[j][0], poly[j][1])
        if d < min_dist:
            min_dist = d
    return min_dist


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


def is_alertable_crime(item):
    ct = crime_text(item)
    if not ALERT_RE.search(ct):
        return False
    # Exclude burglary alarms, shoplifting, petty theft
    if EXCLUDE_RE.search(ct):
        return False
    return True


def item_within_menlo_oaks(item):
    lat = item.get("yCoord")
    lng = item.get("xCoord")
    if lat is None or lng is None:
        return False, 0
    dist = distance_to_polygon_m(lat, lng, MENLO_OAKS_POLY)
    return dist <= THREE_MILES_M, dist


def load_alerted():
    if os.path.exists(ALERTED_PATH):
        with open(ALERTED_PATH) as f:
            return set(json.load(f))
    return set()


def save_alerted(ids):
    with open(ALERTED_PATH, "w") as f:
        json.dump(sorted(ids), f)


def log_alert(item, dist_m, subject, status, error=None):
    """Append an entry to alert_log.json."""
    log = []
    if os.path.exists(ALERT_LOG_PATH):
        with open(ALERT_LOG_PATH) as f:
            try:
                log = json.load(f)
            except json.JSONDecodeError:
                log = []
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "id": item_id(item),
        "subject": subject,
        "street": item.get("street", ""),
        "city": item.get("city", ""),
        "agency": item.get("_agency", ""),
        "distance_mi": round(dist_m / 1609.34, 2),
        "status": status,
    }
    if error:
        entry["error"] = str(error)
    log.append(entry)
    with open(ALERT_LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)


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
        crime = item.get("callType") or item.get("callTypeDescription") or "Crime"
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
    subject = f"[MOSI] {crime} near {short_loc} — {dist_mi:.1f}mi from Menlo Oaks ({severity})"

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
  <p style="text-align:center;color:#aaa;font-size:11px;margin-top:12px">Crime Feed — Menlo Park, Atherton, Palo Alto, Redwood City &amp; SMC Sheriff</p>
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
        log_alert(item, dist_m, subject, "sent")
    except Exception as e:
        print(f"    WARN: email failed: {e}")
        log_alert(item, dist_m, subject, "failed", error=e)


def check_alerts(all_incidents, all_cases):
    alerted = load_alerted()
    all_items = all_incidents + all_cases
    new_alerts = 0

    for item in all_items:
        iid = item_id(item)
        if iid in alerted:
            continue
        if not is_alertable_crime(item):
            continue
        within, dist = item_within_menlo_oaks(item)
        if not within:
            continue
        # Suspicious person/prowler/trespass: tighter radius (0.25mi)
        ct = crime_text(item)
        if re.search(r"suspicious\s*person|prowler|trespass", ct, re.IGNORECASE):
            if dist > QUARTER_MILE_M:
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

    print("  smcsheriff arrests...")
    try:
        arrests = fetch_arrests(token)
        print(f"    {len(arrests)} arrests")
    except Exception as e:
        arrests = []
        print(f"  WARN: arrest fetch failed: {e}")

    all_agencies = AGENCIES + ["paloalto"]

    # Merge with existing archive (indefinite retention)
    os.makedirs(OUT_DIR, exist_ok=True)
    data_dir = os.path.join(OUT_DIR, "data")
    seen = {}
    archived = 0

    # Load from monthly split files first (new format)
    if os.path.isdir(data_dir):
        import glob
        for month_file in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
            try:
                with open(month_file) as f:
                    month_data = json.load(f)
                for item in month_data.get("incidents", []):
                    seen[item_id(item)] = item
                for item in month_data.get("cases", []):
                    seen[item_id(item)] = item
            except (json.JSONDecodeError, KeyError) as e:
                print(f"  WARN: could not load {month_file}: {e}")
        archived = len(seen)
        print(f"  Loaded {archived} items from monthly archive files")

    # Fallback: load from legacy monolithic feed.json (migration path)
    if not seen:
        archive_path = os.path.join(OUT_DIR, "feed.json")
        if os.path.exists(archive_path):
            try:
                with open(archive_path) as f:
                    archive = json.load(f)
                for item in archive.get("incidents", []):
                    seen[item_id(item)] = item
                for item in archive.get("cases", []):
                    seen[item_id(item)] = item
                archived = len(seen)
                print(f"  Loaded {archived} items from legacy feed.json")
            except (json.JSONDecodeError, KeyError) as e:
                print(f"  WARN: could not load archive: {e}")

    if seen:
        # Fresh data wins (overwrites stale copies)
        for item in all_incidents:
            seen[item_id(item)] = item
        for item in all_cases:
            seen[item_id(item)] = item
        all_incidents = [v for v in seen.values() if v.get("_source") == "incident"]
        all_cases = [v for v in seen.values() if v.get("_source") == "case"]
        print(f"  Archive: {archived} existing + {len(seen) - archived} new = {len(seen)} total")

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "agencies": all_agencies,
        "incident_count": len(all_incidents),
        "case_count": len(all_cases),
    }

    def write(name, data):
        path = os.path.join(OUT_DIR, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, separators=(",", ":"), default=str)
        size = os.path.getsize(path)
        print(f"  Wrote {path} ({size} bytes, {size/1048576:.1f} MiB)")

    # --- Monthly split ---
    def item_month(item):
        """Extract YYYY-MM from an item's date fields."""
        dt = item.get("incidentDate") or item.get("reportDate") or item.get("occurrence1Date") or ""
        if len(dt) >= 7:
            return dt[:7]
        return "unknown"

    # Bucket items by month
    from collections import defaultdict
    month_incidents = defaultdict(list)
    month_cases = defaultdict(list)
    for item in all_incidents:
        month_incidents[item_month(item)].append(item)
    for item in all_cases:
        month_cases[item_month(item)].append(item)

    all_months = sorted(set(list(month_incidents.keys()) + list(month_cases.keys())))
    # Drop "unknown" month bucket if present
    all_months = [m for m in all_months if m != "unknown"]

    data_dir = os.path.join(OUT_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)

    # Clean up old month files that are no longer needed
    import glob
    existing_month_files = set(os.path.basename(p) for p in glob.glob(os.path.join(data_dir, "*.json")))
    expected_month_files = set(f"{m}.json" for m in all_months)
    for stale in existing_month_files - expected_month_files:
        stale_path = os.path.join(data_dir, stale)
        os.remove(stale_path)
        print(f"  Removed stale {stale_path}")

    for month in all_months:
        mi = month_incidents.get(month, [])
        mc = month_cases.get(month, [])
        month_meta = {
            "generated_at": meta["generated_at"],
            "month": month,
            "agencies": all_agencies,
            "incident_count": len(mi),
            "case_count": len(mc),
        }
        write(f"data/{month}.json", {"meta": month_meta, "incidents": mi, "cases": mc})

    # Write manifest (small file listing available months)
    manifest = {
        "meta": meta,
        "months": all_months,
    }
    write("manifest.json", manifest)

    # Write legacy feed.json, incidents.json, cases.json pointing to new structure
    # Keep them small — just meta + pointer to monthly files
    legacy_meta = dict(meta)
    legacy_meta["split"] = "monthly"
    legacy_meta["manifest"] = "manifest.json"
    write("feed.json", {"meta": legacy_meta, "months": all_months, "incidents": [], "cases": []})
    write("incidents.json", {"meta": legacy_meta, "months": all_months, "incidents": []})
    write("cases.json", {"meta": legacy_meta, "months": all_months, "cases": []})

    # --- Arrest archive (cumulative, since API only shows last 30 days) ---
    ARRESTS_PATH = os.path.join(OUT_DIR, "arrests.json")
    arrest_archive = {}
    if os.path.exists(ARRESTS_PATH):
        try:
            with open(ARRESTS_PATH) as f:
                existing = json.load(f)
            for a in existing.get("arrests", []):
                arrest_archive[a["casePersonId"]] = a
            print(f"  Loaded {len(arrest_archive)} existing arrests from archive")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  WARN: could not load arrest archive: {e}")

    # Merge fresh data (fresh wins for updates)
    for a in arrests:
        arrest_archive[a["casePersonId"]] = a

    all_arrests = sorted(
        arrest_archive.values(),
        key=lambda a: (a.get("arrestDate", ""), a.get("arrestTime", 0)),
        reverse=True,
    )

    arrest_meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_arrests": len(all_arrests),
        "oldest_arrest": min((a.get("arrestDate", "")[:10] for a in all_arrests), default=""),
        "newest_arrest": max((a.get("arrestDate", "")[:10] for a in all_arrests), default=""),
    }
    write("arrests.json", {"meta": arrest_meta, "arrests": all_arrests})

    print("Checking alerts...")
    check_alerts(all_incidents, all_cases)

    print("Done.")


if __name__ == "__main__":
    main()
