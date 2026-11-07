# NightRead

A private, self-hosted reading room for EPUB, PDF and TXT books. Designed for a warm editorial library, a distraction-free reader, and responsive use on Android.

## Stack
- React + TypeScript + Vite frontend
- FastAPI backend
- SQLite metadata and reading progress
- Docker Compose deployment
- Persistent books and database on the host
- Tailscale for private remote access

## Run locally
Requirements: Node 20+, Python 3.12+.

Backend:
```bash
cd backend
python -m venv .venv
# activate the environment, then:
pip install -r requirements.txt
uvicorn app:app --reload --port 8080
```

Frontend:
```bash
cd frontend
npm install
npm run dev
```

The Vite development server currently expects the API at the same origin; use the Docker deployment for the integrated production experience.

## Deploy on CasaOS / Ubuntu
From the repository root:
```bash
docker compose up -d --build
```
Open `http://SERVER-IP:8088`. For private remote access, use the server's Tailscale IP, e.g. `http://100.x.y.z:8088`.

## Persistent paths
- Books: `/DATA/Media/NightRead`
- SQLite database: `/DATA/AppData/nightread/database/nightread.db`

## Supported uploads
EPUB, PDF and TXT; maximum upload size is 100 MB per file.

## Current scope
This is the initial self-hosted MVP foundation: library upload/listing, TXT text preview, progress persistence, file download endpoint, responsive library dashboard and light/dark themes. EPUB/PDF reading controls, metadata editing, authentication, robust offline sync and bookmarks UI are planned follow-up work. Do not expose the app publicly without adding authentication and access controls.