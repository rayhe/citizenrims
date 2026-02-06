# CitizenRIMS Crime Data Feed

Aggregates public crime data from multiple Bay Area police agencies on the [CitizenRIMS](https://sunridgesystems.com/applications/records-management/citizenrims/) platform and serves it as a single JSON API.

## Agencies

| Agency | Prefix | Incidents | Cases | URL |
|--------|--------|-----------|-------|-----|
| Menlo Park PD | `menlopark` | Yes | Yes | https://menlopark.citizenrims.com/map |
| Atherton PD | `atherton` | Yes | Yes | https://atherton.citizenrims.com/map |
| San Mateo County Sheriff | `smcsheriff` | No | Yes | https://smcsheriff.citizenrims.com/map |
| Palo Alto PD | `papd` | Disabled | Disabled | - |

Palo Alto PD exists on CitizenRIMS but has all public data feeds turned off.

## Requirements

Python 3.7+ (no external dependencies, stdlib only).

## Usage

```bash
python3 citizenrims_feed.py
```

### Options

```
--port PORT       HTTP port (default: 8080)
--days DAYS       Number of days of data to fetch (default: 7)
--refresh SECS    Auto-refresh interval in seconds (default: 300)
```

### Example

```bash
python3 citizenrims_feed.py --port 8080 --days 14 --refresh 600
```

## API Endpoints

### `GET /`

Returns all incidents and cases from all agencies.

### `GET /incidents`

Returns incidents only (calls for service: alarms, traffic stops, medical, etc).

### `GET /cases`

Returns cases only (crime reports: burglary, assault, theft, etc).

### `GET /agencies`

Returns agency configuration info.

### Filtering

Add `?agency=` to filter by agency prefix:

```
GET /incidents?agency=menlopark
GET /?agency=menlopark,atherton
```

## Response Format

```json
{
  "meta": {
    "last_refresh": "2026-02-05T19:14:41.981875",
    "incident_count": 1087,
    "case_count": 55
  },
  "incidents": [
    {
      "incidentNumber": 202601290001,
      "agencyID": 797,
      "type": "INFO",
      "location": "",
      "street": "",
      "city": "Menlo Park",
      "status": "C",
      "incidentDate": "2026-01-29T00:00:00",
      "incidentTime": "01:30:52",
      "beat": "2",
      "xCoord": -122.175,
      "yCoord": 37.453,
      "callType": "Information",
      "callTypeDescription": "Other Calls for Service",
      "_source": "incident",
      "_agency": "Menlo Park Police Department",
      "_prefix": "menlopark"
    }
  ],
  "cases": [
    {
      "caseNumber": "26-206",
      "agencyId": 797,
      "reportDate": "2026-01-29T00:00:00",
      "offenseDescription1": "Possess unlawful paraphernalia (M)",
      "city": "Menlo Park",
      "street": "MERRILL ST/SANTA CRUZ AV",
      "xCoord": -122.143,
      "yCoord": 37.478,
      "crimeType": "Drugs or Alcohol",
      "crimeClassification": "Misdemeanor",
      "_source": "case",
      "_agency": "Menlo Park Police Department",
      "_prefix": "menlopark"
    }
  ]
}
```

## How It Works

The script reverse-engineers the CitizenRIMS API (built by Sun Ridge Systems):

1. **Auth** - `POST /api/v1/auth/citizen` with an empty body returns a JWT token (public citizen-level access, no credentials needed)
2. **Agency config** - Fetches each agency's configuration to discover agency IDs, enabled features, and incident/case type codes
3. **Incidents & Cases** - Queries the Incident and Case endpoints using the discovered parameters
4. **Serve** - Combines everything and serves over HTTP with CORS enabled

Tokens auto-refresh before expiry. Data auto-refreshes on the configured interval.
