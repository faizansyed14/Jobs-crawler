# Job Scraper — Multi-Portal Gulf Job Crawler

```
crawler/
├── backend/          # Python crawler + FastAPI
│   ├── api/          # REST API for frontend
│   ├── browsers/     # nodriver → seleniumbase → camoufox fallbacks
│   ├── config/       # settings + portal/location/industry maps
│   ├── core/         # dates, rate limit, robots, cookies
│   ├── database/     # SQLAlchemy models + repository
│   ├── extractors/   # BaseExtractor + Naukrigulf API client
│   ├── orchestrator.py
│   ├── main.py       # CLI
│   └── requirements.txt
└── frontend/         # Vite + React UI (location/industry select)
```

## Quick start

### Backend

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`. For local smoke tests without Postgres:

```
DATABASE_URL=sqlite:///./gulf_crawler.db
```

Init DB + crawl Dubai IT (2 pages):

```bash
python main.py init-db
python main.py list-meta
python main.py crawl --locations dubai --industry it --max-pages 2 --full
python main.py serve
```

API: `http://127.0.0.1:8000` · docs: `/docs`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` — select locations, industry (IT default), start crawl.

## CLI examples

```bash
# Multiple Gulf cities, IT filter
python main.py crawl --locations dubai,abu-dhabi,riyadh,qatar,kuwait --industry it

# Freshness window from DB cutoff (incremental)
python main.py crawl --locations dubai --industry it

# Full refresh ignore cutoff
python main.py crawl --locations dubai --industry it --full --max-pages 5
```

## Architecture notes

- Primary path: Naukrigulf JSON API `/spapi/jobapi/search`
- Headers: `appId=205`, `systemId=2323`, `version=v1`
- IT industry: `ClusterInd=25`
- Dedup: unique `(source_portal, job_id)`
- Incremental: `MAX(posted_at)` cutoff; promoted jobs do not stop early
- Polite delays + robots.txt check