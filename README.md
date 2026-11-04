# MedEvidence-XAI

**A Multimodal AI Framework for Evidence-Grounded Medical Document Understanding and Explainable Clinical Question Answering**

> **Research/educational prototype.** This is a research/educational prototype and is not a substitute for
> professional medical diagnosis or treatment. It is not a diagnostic system.

Final-year B.Tech (CSE, AI & ML) project. The long-term goal is to turn uploaded medical documents into
traceable evidence and answer questions only when the evidence supports them:
`answer → evidence → source document → page/region → confidence → reason`.

## Current status: Medical document upload + storage

- **1:** repository layout, FastAPI backend, React + Vite + Tailwind frontend, `.env` configuration,
  PostgreSQL connection, Alembic migrations, health-check API, status dashboard, logging.
- **2:** secure PDF upload (extension + MIME type + `%PDF-` signature + size checks, safe filenames,
  UUID storage names), `documents` table, upload/list/metadata APIs, upload UI with progress, document list and
  metadata panel.

**Not implemented yet** PDF parsing, OCR, tables/images, clinical extraction, embeddings,
retrieval, QA. Nothing has been evaluated ("Not yet evaluated").

## Repository layout

```
backend/              FastAPI app, Alembic migrations
frontend/             React + Vite + Tailwind dashboard
document_processing/  (placeholder)
database/             (placeholder for DB assets)
tests/                pytest suite (tests/backend)
scripts/              helper scripts (check_secrets.sh)
docs/                 documentation
data/                 synthetic/legally reusable sample data only (data/uploads/ is git-ignored upload storage)
```

## Prerequisites

- Python 3.11+ (developed on 3.13)
- Node.js 20+ and npm
- PostgreSQL 14+ (or Docker, using the provided `docker-compose.yml`)

## Setup

```bash
# 1. Configuration
cp .env.example .env
#    edit .env: replace POSTGRES_PASSWORD and the password inside DATABASE_URL (keep them identical)
#    optional: UPLOAD_DIR (default data/uploads) and MAX_UPLOAD_SIZE_MB (default 25)

# 2. PostgreSQL (option A: Docker)
docker compose up -d postgres
#    (option B: use any local PostgreSQL and set DATABASE_URL accordingly)

# 3. Backend
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
alembic upgrade head                                    # apply migrations
uvicorn app.main:app --reload --port 8000

# 4. Frontend (new terminal)
cd frontend
npm install
npm run dev                                             # http://localhost:5173
```

Open http://localhost:5173 — the **Dashboard** tab shows backend and PostgreSQL status; the **Documents** tab
uploads PDFs and lists them. Only synthetic or anonymised documents should ever be uploaded.

Uploading from the command line:

```bash
curl -F "file=@sample.pdf;type=application/pdf" http://localhost:8000/api/documents
curl http://localhost:8000/api/documents
```
API docs: http://localhost:8000/docs

## Tests

```bash
# from the repository root, with the backend venv active
python -m pytest                      # unit + API tests on SQLite; PostgreSQL integration tests are skipped
TEST_DATABASE_URL="postgresql+psycopg://user:PASSWORD@localhost:5432/testdb" python -m pytest
```

> The PostgreSQL integration tests **downgrade/upgrade the schema and delete all rows in `documents`** in
> `TEST_DATABASE_URL`. Point it at a throwaway database, not data you care about.

## Documentation

See [`docs/`](docs/): project overview, architecture, API, database design, developer guide, safety,
limitations, and [changelog](docs/changelog.md).

## Safety and data

Never commit real patient information. Use synthetic, anonymised, or legally reusable data only.
Run `scripts/check_secrets.sh` before sharing the repository.
