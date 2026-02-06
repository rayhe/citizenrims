#!/usr/bin/env python3
"""
CitizenRIMS crime data aggregator and JSON API server.

Fetches incidents and cases from multiple agencies on the CitizenRIMS platform
and serves them as a combined JSON feed over HTTP.

Usage:
    python3 citizenrims_feed.py [--port 8080] [--days 7] [--refresh 300]

Endpoints:
    GET /                Combined feed (incidents + cases) from all agencies
    GET /incidents       Incidents only
    GET /cases           Cases only
    GET /agencies        Agency configuration info
"""

import argparse
import json
import threading
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

API_BASE = "https://api.v1.citizenrims.com"

# Agency definitions: (url_prefix, name)
# Palo Alto PD (papd) has all data feeds disabled, so it's excluded.
# San Mateo County Sheriff (smcsheriff) only has cases, no incidents.
AGENCIES = [
    "menlopark",
    "atherton",
    "smcsheriff",
]


class TokenManager:
    def __init__(self):
        self._token = None
        self._expires_at = 0
        self._lock = threading.Lock()

    def get_token(self):
        with self._lock:
            if self._token and time.time() < self._expires_at - 60:
                return self._token
            self._token = self._refresh()
            # Tokens last 24h, but refresh well before expiry
            self._expires_at = time.time() + 3600
            return self._token

    def _refresh(self):
        req = Request(
            f"{API_BASE}/api/v1/auth/citizen",
            method="POST",
            headers={"Content-Length": "0"},
            data=b"",
        )
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())["token"]


class CitizenRIMSClient:
    def __init__(self, token_manager, days=7):
        self.token_manager = token_manager
        self.days = days
        self._agency_configs = {}

    def _api_get(self, path, params):
        url = f"{API_BASE}{path}?{urlencode(params)}"
        token = self.token_manager.get_token()
        req = Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        })
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def get_agency_config(self, prefix):
        if prefix in self._agency_configs:
            return self._agency_configs[prefix]
        config = self._api_get(
            "/api/v1/AgencyConfig/AgencyConfigGetByUrlPrefix",
            {"citizenRimsUrlPrefix": prefix},
        )
        self._agency_configs[prefix] = config
        return config

    def _date_str(self, dt):
        # The API expects JavaScript's toDateString() format: "Thu Jan 29 2026"
        return dt.strftime("%a %b %d %Y")

    def _get_type_list(self, marker_groups):
        return ",".join(g["groupFieldName"] for g in marker_groups)

    def fetch_incidents(self, prefix):
        config = self.get_agency_config(prefix)
        if not config.get("incidentsEnabled"):
            return []
        end = datetime.now()
        start = end - timedelta(days=self.days)
        groups = config.get("incidentMarkerGroups", [])
        if not groups:
            return []
        params = {
            "agencyId": config["agencyId"],
            "primaryAgencyId": config["primaryAgencyId"],
            "startDate": self._date_str(start),
            "endDate": self._date_str(end),
            "types": self._get_type_list(groups),
            "circleLatitude": config.get("defaultLatitude", 37.5),
            "circleLongitude": config.get("defaultLongitude", -122.2),
            "circleRadius": 50000,
        }
        try:
            items = self._api_get("/api/v1/Incident", params)
            for item in items:
                item["_source"] = "incident"
                item["_agency"] = config.get("agencySiteName", prefix)
                item["_prefix"] = prefix
            return items
        except HTTPError as e:
            print(f"[WARN] Failed to fetch incidents for {prefix}: {e}")
            return []

    def fetch_cases(self, prefix):
        config = self.get_agency_config(prefix)
        if not config.get("caseDataEnabled"):
            return []
        end = datetime.now()
        start = end - timedelta(days=self.days)
        groups = config.get("caseMarkerGroups", [])
        if not groups:
            return []
        params = {
            "agencyId": config["agencyId"],
            "primaryAgencyId": config["primaryAgencyId"],
            "startDate": self._date_str(start),
            "endDate": self._date_str(end),
            "types": self._get_type_list(groups),
            "circleLatitude": config.get("defaultLatitude", 37.5),
            "circleLongitude": config.get("defaultLongitude", -122.2),
            "circleRadius": 50000,
        }
        try:
            items = self._api_get("/api/v1/Case", params)
            for item in items:
                item["_source"] = "case"
                item["_agency"] = config.get("agencySiteName", prefix)
                item["_prefix"] = prefix
            return items
        except HTTPError as e:
            print(f"[WARN] Failed to fetch cases for {prefix}: {e}")
            return []

    def fetch_all(self):
        all_incidents = []
        all_cases = []
        for prefix in AGENCIES:
            print(f"  Fetching {prefix}...")
            all_incidents.extend(self.fetch_incidents(prefix))
            all_cases.extend(self.fetch_cases(prefix))
        return all_incidents, all_cases


class DataStore:
    def __init__(self, client, refresh_interval):
        self.client = client
        self.refresh_interval = refresh_interval
        self._incidents = []
        self._cases = []
        self._last_refresh = None
        self._lock = threading.Lock()

    def start_background_refresh(self):
        self._refresh()
        t = threading.Thread(target=self._refresh_loop, daemon=True)
        t.start()

    def _refresh_loop(self):
        while True:
            time.sleep(self.refresh_interval)
            self._refresh()

    def _refresh(self):
        print(f"[{datetime.now().isoformat()}] Refreshing data...")
        try:
            incidents, cases = self.client.fetch_all()
            with self._lock:
                self._incidents = incidents
                self._cases = cases
                self._last_refresh = datetime.now().isoformat()
            print(f"  Got {len(incidents)} incidents, {len(cases)} cases")
        except Exception as e:
            print(f"[ERROR] Refresh failed: {e}")

    def get_incidents(self):
        with self._lock:
            return list(self._incidents)

    def get_cases(self):
        with self._lock:
            return list(self._cases)

    def get_meta(self):
        with self._lock:
            return {
                "last_refresh": self._last_refresh,
                "incident_count": len(self._incidents),
                "case_count": len(self._cases),
            }


class FeedHandler(BaseHTTPRequestHandler):
    store = None  # set before serving

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        if path == "/":
            data = {
                "meta": self.store.get_meta(),
                "incidents": self.store.get_incidents(),
                "cases": self.store.get_cases(),
            }
        elif path == "/incidents":
            data = {
                "meta": self.store.get_meta(),
                "incidents": self.store.get_incidents(),
            }
        elif path == "/cases":
            data = {
                "meta": self.store.get_meta(),
                "cases": self.store.get_cases(),
            }
        elif path == "/agencies":
            data = {
                "agencies": [
                    {
                        "prefix": p,
                        "name": self.store.client.get_agency_config(p).get("agencySiteName"),
                        "incidents_enabled": self.store.client.get_agency_config(p).get("incidentsEnabled"),
                        "cases_enabled": self.store.client.get_agency_config(p).get("caseDataEnabled"),
                    }
                    for p in AGENCIES
                ],
                "note": "Palo Alto PD (papd) exists on CitizenRIMS but has all data feeds disabled.",
            }
        else:
            self.send_error(404)
            return

        # Optional agency filter: ?agency=menlopark,atherton
        agency_filter = params.get("agency")
        if agency_filter:
            prefixes = agency_filter[0].split(",")
            if "incidents" in data:
                data["incidents"] = [i for i in data["incidents"] if i.get("_prefix") in prefixes]
            if "cases" in data:
                data["cases"] = [c for c in data["cases"] if c.get("_prefix") in prefixes]

        body = json.dumps(data, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[HTTP] {args[0]}")


def main():
    parser = argparse.ArgumentParser(description="CitizenRIMS crime data feed server")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port (default: 8080)")
    parser.add_argument("--days", type=int, default=7, help="Days of data to fetch (default: 7)")
    parser.add_argument("--refresh", type=int, default=300, help="Refresh interval in seconds (default: 300)")
    args = parser.parse_args()

    token_mgr = TokenManager()
    client = CitizenRIMSClient(token_mgr, days=args.days)
    store = DataStore(client, args.refresh)

    print(f"Starting CitizenRIMS feed server on port {args.port}")
    print(f"  Agencies: {', '.join(AGENCIES)}")
    print(f"  Date range: last {args.days} days")
    print(f"  Refresh interval: {args.refresh}s")
    print()

    store.start_background_refresh()

    FeedHandler.store = store
    server = HTTPServer(("0.0.0.0", args.port), FeedHandler)
    print(f"\nServing at http://localhost:{args.port}")
    print("  GET /           - All data (incidents + cases)")
    print("  GET /incidents  - Incidents only")
    print("  GET /cases      - Cases only")
    print("  GET /agencies   - Agency info")
    print("  ?agency=menlopark,atherton  - Filter by agency")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
