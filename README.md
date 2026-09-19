# Market Visit Tracker API

A small FastAPI service for logging retailer visits and reporting
coverage by **TL** (Team Leader), **SS** (Sales Supervisor), and **RDS**
(distributor) — so management can see retailer-wise tracking from any
system that can call a web API.

It comes pre-seeded with the 641 retailers from your Zone A tertiary
dashboard, each tagged with its TL, SS, RDS, zone, club tier, and
status. When a visit is logged, the API looks up the retailer in that
list and automatically fills in TL/SS/RDS — no need to send them
yourself.

## 1. Run it locally

Requires Python 3.9+.

```bash
cd market-visit-api
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then edit .env and set API_KEY
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000/docs** for interactive, try-it-yourself API
docs (Swagger UI) — the easiest way to explore every endpoint.

The database is a single SQLite file at `./data/market_visits.db`,
created automatically on first run. No separate database server needed.

## 2. Authentication

Set `API_KEY` in `.env` (or your host's environment variables) to a long
random string. Every request must then include it as a header:

```
X-API-Key: your-key-here
```

`DELETE /visits/{id}` optionally uses a separate, stronger
`ADMIN_API_KEY` — set it if you want a different key for destructive
actions than for everyday reads/writes. If you don't set it, it falls
back to `API_KEY`.

**If you leave `API_KEY` unset, authentication is disabled entirely.**
That's fine for testing on your own machine, but never deploy it that
way anywhere reachable from the internet.

## 3. Endpoints

| Method | Path                  | Purpose                                              |
|--------|-----------------------|-------------------------------------------------------|
| POST   | `/visits`             | Log a new visit                                       |
| GET    | `/visits`             | List visits (filter by `retailer`, `tl`, `ss`, `rds`, `date_from`, `date_to`, `search`) |
| GET    | `/visits/{id}`        | Get one visit                                         |
| DELETE | `/visits/{id}`        | Delete a visit (admin key)                            |
| GET    | `/visits/export.csv`  | Download filtered visits as CSV                       |
| GET    | `/retailers`          | List the master retailer list (filter by `tl`, `ss`, `rds`, `search`) |
| GET    | `/coverage?group_by=` | Coverage by `tl`, `ss`, or `rds`: assigned vs. visited retailers, coverage %, total visits |
| GET    | `/stats`              | Overall totals                                        |
| GET    | `/health`             | Unauthenticated health check                          |

### Example: log a visit

```bash
curl -X POST http://localhost:8000/visits \
  -H "X-API-Key: your-key-here" \
  -H "Content-Type: application/json" \
  -d '{
        "retailer": "Tahmina Electicals & Electronics (Retailer)",
        "market": "Guwahati market",
        "visit_date": "2026-09-19",
        "feedback": "Good stock, wants more posters",
        "suggestions": "Send festive-season POS material",
        "submitted_by": "Rahul"
      }'
```

The response includes `tl`, `ss`, and `rds` filled in automatically from
the retailer master list.

### Example: coverage by TL

```bash
curl -H "X-API-Key: your-key-here" \
  "http://localhost:8000/coverage?group_by=tl"
```

```json
[
  {"name": "Bichitra Saharia", "assigned": 12, "visited": 3, "coverage_pct": 25.0, "total_visits": 4},
  {"name": "Gobindo Mandal", "assigned": 15, "visited": 0, "coverage_pct": 0.0, "total_visits": 0}
]
```

Swap `group_by=tl` for `ss` or `rds` for the same breakdown at those
levels.

## 4. Deploying it somewhere real

You haven't picked a host yet, so here are the simplest options:

**Render / Railway / Fly.io (easiest)**
1. Push this folder to a GitHub repo.
2. Create a new "Web Service" and point it at the repo — they auto-detect
   the `Dockerfile`, or you can set the start command to
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
3. Add `API_KEY` (and optionally `ADMIN_API_KEY`) as environment
   variables in the host's dashboard.
4. **Important:** these platforms often use an ephemeral filesystem —
   the SQLite file can be wiped on redeploy. Look for a "persistent
   disk" / "volume" option and mount it at the path in `DB_PATH`
   (`/app/data` if using the Dockerfile), or switch to a hosted
   Postgres if the platform offers one for free.

**Your own server/VPS**
```bash
docker build -t market-visit-api .
docker run -d -p 8000:8000 \
  -e API_KEY=your-key-here \
  -v $(pwd)/data:/app/data \
  market-visit-api
```
Put a reverse proxy (nginx, Caddy) in front for HTTPS.

**Just running locally for now**
The steps in section 1 are all you need. Anyone on your network can
reach it at `http://<your-machine-ip>:8000` while it's running.

## 5. Swapping in a bigger database later

Everything sits behind `app/database.py` and `app/crud.py`. If you
outgrow SQLite (many concurrent writers, need it always-on across
redeploys), swapping in Postgres means rewriting those two files —
the API routes in `app/main.py` don't need to change.

## 6. Re-seeding or updating the retailer list

`app/retailers_seed.json` is only used to seed the `retailers` table
the first time the database is created. To load an updated retailer
list later, either:
- delete the SQLite file and restart (full re-seed), or
- write a small script that reads a new JSON/CSV and upserts into the
  `retailers` table directly.

Ask me to regenerate `retailers_seed.json` any time you upload a newer
version of the tertiary sales dashboard.
