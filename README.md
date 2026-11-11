# MedEvidence-XAI

**A Multimodal AI Framework for Evidence-Grounded Medical Document Understanding and Explainable Clinical Question Answering**

> **Research/educational prototype.** This is a research/educational prototype and is not a substitute for
> professional medical diagnosis or treatment. It is not a diagnostic system.

Final-year B.Tech (CSE, AI & ML) project. The long-term goal is to turn uploaded medical documents into
traceable evidence and answer questions only when the evidence supports them:
`answer → evidence → source document → page/region → confidence → reason`.

## Current status: hybrid retrieval and evidence ranking

> **New here? Start with [`docs/execution-steps.md`](docs/execution-steps.md)**, the step-by-step guide for
> installing, running and checking.

- **1:** repository layout, FastAPI backend, React + Vite + Tailwind frontend, `.env` configuration,
  PostgreSQL connection, Alembic migrations, health-check API, status dashboard, logging.
- **2:** secure PDF upload (extension + MIME type + `%PDF-` signature + size checks, safe filenames,
  UUID storage names), `documents` table, upload/list/metadata APIs, upload UI with progress, document list and
  metadata panel.

- **3:** page-level text extraction (PyMuPDF, pdfplumber fallback), detection of pages with little or no text,
  Tesseract OCR fallback with clear setup errors, per-page method/status, processing status API, page content API,
  extracted-text viewer.

- **4:** table detection (rows, columns, cells, page, table ID, source box), embedded-image extraction (metadata,
  file, page, placement box), optional OCR of text printed inside images, a page preview with the source region
  highlighted, and APIs/UI to inspect tables, images, source page and region. Images are never interpreted (no
  medical-image analysis).

- **5:** rule- and lexicon-based extraction of lab results, vital signs, medications, conditions, symptoms and dates
  from text, OCR text, tables and image-OCR text, with negation/uncertainty/family-history handling, normalisation that keeps
  the original text, a `ClinicalEvidence` model with exact source text, offsets, page region and a heuristic confidence, APIs,
  and a viewer. No trained model.

- **6:** every extracted evidence item gets a vector (stored in PostgreSQL, searched with exact FAISS/NumPy), search and
  retrieval APIs (by query, entity, document, page, with filters) that return evidence with full provenance, and an Evidence
  Explorer UI. The default embedding is offline and **lexical**; real semantic search needs the optional `sentence-transformers`
  backend.

- **7:** hybrid retrieval that fuses semantic similarity, BM25 keyword match, entity match (clinical lexicon), temporal fit
  (dates, latest/earliest), extraction confidence and source quality with a documented, configurable formula; metadata and date-range
  filters; every hit shows its score breakdown. A small synthetic benchmark measures Precision@K, Recall@K and MRR.

## Repository layout

```
backend/              FastAPI app, Alembic migrations
frontend/             React + Vite + Tailwind dashboard
document_processing/  PDF text, OCR, table and image extraction library (pure Python)
database/             (placeholder for DB assets)
tests/                pytest suite (tests/backend)
scripts/              check_secrets.sh, generate_sample_pdfs.py
docs/                 documentation
data/                 synthetic sample PDFs (data/sample/); data/uploads/ and data/images/ are git-ignored storage
```

## Prerequisites

- Python 3.11+ (developed on 3.13)
- Node.js 20+ and npm
- PostgreSQL 14+ (or Docker, using the provided `docker-compose.yml`)
- Tesseract OCR 5.x for scanned pages (`sudo apt install tesseract-ocr` / `brew install tesseract`); optional,
  text-layer PDFs work without it

## Setup

```bash
# 1. Configuration
cp .env.example .env
#    edit .env: replace POSTGRES_PASSWORD and the password inside DATABASE_URL (keep them identical)
#    optional: UPLOAD_DIR, IMAGE_DIR, MAX_UPLOAD_SIZE_MB, TESSERACT_CMD, OCR_LANGUAGES, OCR_DPI, AUTO_MULTIMODAL, IMAGE_OCR, AUTO_CLINICAL_EXTRACTION (see docs/execution-steps.md)

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

## Safety and data

Never commit real patient information. Use synthetic, anonymised, or legally reusable data only.
Run `scripts/check_secrets.sh` before sharing the repository.
