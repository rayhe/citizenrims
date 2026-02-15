# Crime Data Feed

Aggregates public crime data from multiple Bay Area police agencies into a static JSON feed with an interactive map, email alerts, and analytics.

Deployed via GitHub Pages. GitHub Actions runs `generate.py` every 5 minutes to refresh data.

## Agencies

| Agency | Prefix | Source | Incidents | Cases |
|--------|--------|--------|-----------|-------|
| Menlo Park PD | `menlopark` | CitizenRIMS | Yes | Yes |
| Atherton PD | `atherton` | CitizenRIMS | Yes | Yes |
| Palo Alto PD | `paloalto` | ArcGIS REST | Yes | No |
| San Mateo County Sheriff | `smcsheriff` | CitizenRIMS | No | Yes |

Palo Alto PD has CitizenRIMS data feeds disabled, so we pull from their [public ArcGIS endpoint](https://gis.cityofpaloalto.org/server/rest/services/PublicSafety/AgencyCommonEvent/MapServer/2) instead.

## Requirements

Python 3.7+ (stdlib only, no external dependencies).

## Files

```
generate.py          # Data fetcher, alert engine, static JSON writer
test_alerts.py       # 65 unit tests for alerting logic and geometry
public/index.html    # Interactive map + analytics (single-file, no build step)
public/*.json        # Generated data files (feed.json, incidents.json, cases.json)
alerted.json         # Persistent set of already-alerted incident IDs
.github/workflows/   # Cron job: runs generate.py every 5 minutes
```

## How it works

### Data pipeline (`generate.py`)

**CitizenRIMS agencies** (Menlo Park, Atherton, SMC Sheriff):
1. `POST /api/v1/auth/citizen` with empty body returns a JWT (public citizen-level, no credentials)
2. Fetches agency config to discover IDs, features, and type codes
3. Queries Incident and Case endpoints

**Palo Alto PD** (ArcGIS):
- Queries the city's public ArcGIS REST endpoint with `CALLTIME >= <cutoff_ms>`
- Paginates results, computes polygon centroids for lat/lng, normalizes to CitizenRIMS schema

**Output**: Writes `feed.json`, `incidents.json`, `cases.json` to `public/`.

### Email alerts

Alerts trigger for property/suspicious crimes near Menlo Oaks:

- **Alertable crimes**: burglary, larceny, theft, fraud, stolen vehicle, shoplifting, embezzlement, forgery, identity theft, vandalism, arson, suspicious person, prowler, trespass
- **Excluded**: shoplifting, petty theft, alarm-only burglary (low signal)
- **Distance tiers** from Menlo Oaks polygon boundary:
  - Within 0.25 mi: suspicious person, prowler, trespass also alert
  - Within 3 mi: all other alertable types
- **Deduplication**: `alerted.json` tracks sent IDs to avoid repeats

Configure via environment variables:
```
ALERT_EMAIL_USER      # Gmail SMTP username
ALERT_EMAIL_PASSWORD  # Gmail app password
ALERT_RECIPIENTS      # Comma-separated email addresses
```

### Menlo Oaks polygon boundary

Distance is measured from the neighborhood boundary polygon, not a center point. Incidents inside the polygon have distance = 0. The boundary is a 6-vertex polygon:

| Vertex | Location | Coordinates |
|--------|----------|-------------|
| NW | Bay Rd & Ringwood Ave | 37.4717, -122.1680 |
| NE | Bay Rd & Perimeter Rd (VA campus) | 37.4700, -122.1616 |
| E | Coleman Ave & Perimeter Rd | 37.4629, -122.1651 |
| SE | Coleman Ave & Berkeley Ave | 37.4636, -122.1673 |
| S | South of Arlington Way | 37.4599, -122.1706 |
| SW | Ringwood Ave & Arlington Way | 37.4611, -122.1732 |

Geometry functions: ray-casting point-in-polygon, point-to-segment projection for edge distance, haversine for meters.

## Interactive map (`public/index.html`)

Single HTML file, no build step. Uses Leaflet for mapping, Chart.js for analytics.

### Markers

**Crime-type icons** classified by regex matching against callType, crimeType, offenseDescription fields:

| Icon | Color | Category | Examples |
|------|-------|----------|----------|
| `!` | Red | Violent | Assault, Homicide, Robbery, Weapons |
| `$` | Orange | Property | Burglary, Larceny, Theft, Fraud, Stolen Vehicle |
| car | Blue | Traffic | Traffic, Collisions, Parking, DUI |
| pill | Purple | Drugs | Drug Offenses, Narcotics, Alcohol |
| eye | Yellow | Suspicious | Suspicious Circumstances, Trespass, Prowler |
| fire | Dark red | Fire/Hazard | Fire, Arson, Hazmat |
| `+` | Green | Medical | Medical, Welfare Check, Mental Health |
| dot | Gray | Other | Everything else |

**Severity-based sizing** (marker diameter):

| Severity | Size | Examples |
|----------|------|----------|
| Critical | 24px | Homicide, Assault, Robbery, Weapons |
| High | 20px | Burglary, Stolen Vehicle, Drugs, Missing Persons |
| Medium | 16px | Traffic, Suspicious, Fire |
| Low | 12px | Medical, Welfare Check, Alarms |

**Agency border ring** — border color indicates source agency.

### Filters

**Type filters**: All, Incidents, Cases, Violent, Property, Alerts (alertable crime types only)

**Agency filters**: Menlo Park, Atherton, Palo Alto, SMC Sheriff

**Geo filter**: "Menlo Oaks 3mi" — shows only incidents within 3 miles of the Menlo Oaks boundary. Draws the polygon outline on the map when active.

**Day range**: 1, 3, 7, 14, 31 days

### Deep linking

Filters sync to the URL bar via `history.replaceState`. Query parameters:

| Param | Values | Default |
|-------|--------|---------|
| `filter` | `all`, `incident`, `case`, `violent`, `property`, `alerts`, agency prefix | `all` |
| `days` | `1`, `3`, `7`, `14`, `31` | `7` |
| `geo` | `1` (Menlo Oaks 3mi on) | off |

Example: `?filter=property&days=14&geo=1`

Settings also persist in localStorage.

### Timeline chart

Stacked bar chart showing incidents per day, broken down by police watch period:

| Watch | Hours | Color |
|-------|-------|-------|
| Day | 7:00 AM – 3:00 PM | Yellow |
| Swing | 3:00 PM – 11:00 PM | Orange |
| Night | 11:00 PM – 7:00 AM | Navy |

- Weekend day labels shown in red
- Expand button opens a fullscreen overlay with the chart at viewport scale
- Responds to all active filters (type, agency, geo, day range)

### Heatmap table

Watch period x day-of-week cross-tabulation below the chart:

- Rows: Day, Swing, Night watches
- Columns: Mon – Sun
- Cells colored on a green-to-red gradient based on incident count
- Row totals, column totals, and grand total

## Tests

```bash
python3 -m unittest test_alerts -v
```

65 tests covering:
- Alert regex matching (crime types, exclusions)
- Distance tier logic (0.25mi suspicious, 3mi property)
- Polygon geometry (point-in-polygon, distance-to-edge)
- Crime text formatting and ID extraction

A pre-commit hook runs the full test suite before every commit.

## CI/CD

GitHub Actions workflow (`.github/workflows/update.yml`):
1. Runs every 5 minutes via cron
2. Executes `python generate.py` with `DAYS=31`
3. Checks alerts and sends emails if triggered
4. Commits and pushes updated JSON files if data changed
