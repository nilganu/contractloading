# Hotel Contract Extraction & Review System

A full-stack system that ingests hotel supplier contracts (XLSX, XLS, PDF, DOCX, images),
extracts structured hotel / rate / room / child-policy data through a deterministic-first
pipeline with an OpenAI LLM extraction stage, lets humans review and edit the output, and
exports a Moonstride-compatible Excel import workbook.

## Architecture

```
Uploaded file
  -> file-type detection
  -> deterministic parser (openpyxl / pdfplumber / python-docx)
  -> OCR / vision fallback (only when needed)
  -> normalized intermediate representation (IR)
  -> OpenAI LLM extraction into strict JSON
  -> JSON schema validation (Pydantic)
  -> normalization + business validation
  -> human review UI (React)
  -> final XLSX export (openpyxl)
```

The LLM never writes the workbook directly. It returns JSON. The backend
validates, normalizes, and exports.

## Tech stack

- **Backend** : Python 3.11+, FastAPI, SQLite (SQLAlchemy), Pydantic v2,
  openpyxl, pdfplumber, python-docx, pillow, OpenAI SDK, pytest.
- **Frontend** : React 18, TypeScript, Vite, TanStack Table, TanStack Query,
  Vitest + React Testing Library.

## Repository layout

```
backend/                Python FastAPI backend
  app/
    api/                HTTP routes
    services/
      parsers/          excel, pdf, docx, image parsers
      classifier.py     sheet / page classifier
      ir_builder.py     normalized intermediate representation
      llm_extractor.py  OpenAI extraction wrapper
      normalizer.py     post-extraction normalization
      validator.py      business / blocking rule validator
      exporter.py       XLSX export
      jobs.py           in-memory + sqlite job service
      audit.py          audit log
    schemas/            Pydantic schemas (data model)
    db.py               SQLAlchemy / SQLite setup
    config.py           app config and .env loading
    main.py             FastAPI app
  prompts/              prompt files (versioned)
  storage/              uploads + exports (gitignored)
  tests/                pytest suite
  requirements.txt
  .env.example
frontend/               React + Vite + TS review UI
  src/
    pages/              Upload, Job, Review screens
    components/         Grid, Tabs, Source Preview, ...
    api/                fetch client wrapping backend
    hooks/              react-query hooks
    types/              shared TS types mirroring backend
  package.json
  vite.config.ts
fixtures/               Sample contracts (place your Volonline file here)
exports_samples/        Reference / generated XLSX exports
```

## Setup

### 1. Backend

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# edit .env and set OPENAI_API_KEY if you want real LLM extraction
# without an API key the system falls back to a deterministic stub extractor

uvicorn app.main:app --reload --port 8000
```

Backend runs on http://localhost:8000

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on http://localhost:5173 and proxies `/api` to the backend.

## Environment variables (`backend/.env`)

| Variable                | Purpose                                                  | Default              |
|-------------------------|----------------------------------------------------------|----------------------|
| `OPENAI_API_KEY`        | Required for LLM extraction                              | empty -> stub mode   |
| `OPENAI_MODEL`          | OpenAI chat completions model id                         | `gpt-4o`             |
| `OPENAI_VISION_MODEL`   | OpenAI vision-capable model id                           | `gpt-4o`             |
| `STORAGE_DIR`           | Where uploads + exports live                             | `./storage`          |
| `DATABASE_URL`          | SQLAlchemy URL                                           | `sqlite:///./hotel.db` |
| `CHILD_COLUMN_MODE`     | `dynamic_review` / `dynamic_export` / `strict_template`  | `dynamic_review`     |
| `PRESERVE_CHILD_POSITIONS` | `true` / `false`                                      | `true`               |
| `PROMPT_VERSION`        | Logged into audit                                        | `v1`                 |
| `PARSER_VERSION`        | Logged into audit                                        | `v1`                 |
| `ALLOWED_ORIGINS`       | CORS, comma separated                                    | `http://localhost:5173` |

## Run tests

```bash
# Backend
cd backend
pytest -q

# Frontend
cd frontend
npm test
```

## Use it

1. Open http://localhost:5173
2. Drop or pick a contract (XLSX, XLS, PDF, DOCX, PNG, JPG, JPEG, TIFF).
3. Fill defaults (supplier, country, currency, etc.) and pick a child-column mode.
4. Submit. Watch the timeline.
5. Open the review screen. Tabs:
   - Extraction summary
   - Hotel rows (editable grid with dynamic child columns)
   - Child policies
   - Extraction notes
   - Source preview
   - Validation issues
   - Raw normalized JSON
   - Audit
6. Fix any blocking errors. Edit cells. Move ambiguous values to Extraction Notes.
7. Click "Export XLSX". You get a Moonstride-compatible workbook with
   `Hotel` and `Extraction Notes` sheets.

## Export modes

| Mode             | Behavior                                                              |
|------------------|------------------------------------------------------------------------|
| `dynamic_review` | Used in UI. Dynamic child + child-position columns visible.            |
| `dynamic_export` | XLSX includes dynamic child columns derived from the contract.        |
| `strict_template`| XLSX uses only the fixed template columns. Unsupported child bands are moved to `Extraction Notes` with a warning. |

## Generalization features

This isn't a one-off Acrotel extractor. The pipeline has five guarantees
that make it work across varied contracts:

### 1. PDF strategy router ([backend/app/services/pdf_strategy.py](backend/app/services/pdf_strategy.py))

Picks the right extraction path per PDF based on parser diagnostics:

| Detected layout | Strategy chosen |
|---|---|
| Clean digital PDF, real text + numeric tables | `native_text_llm` — cheap text→LLM path |
| Form-style PDF with merged cells / scrambled OCR'd text | `two_call_vision` — skeleton-then-fill |
| Pure scan / no text at all | `vision_only` |
| User picks `extractionMode=text_only` | forced `native_text_llm` |
| User picks `extractionMode=vision_required` | forced `vision_only` |

The selected strategy appears in the Audit tab as `pdf_strategy_selected`.

### 2. Two-call vision extraction (skeleton → fill)

For visually complex tables (merged period cells, multi-board rows, child
policy rows below the rate table), single-shot vision collapses rows. The
two-call path ([direct_vision_extractor.py](backend/app/services/direct_vision_extractor.py))
runs:

- **Call A** ([prompts/direct-vision-skeleton-v1.txt](backend/prompts/direct-vision-skeleton-v1.txt)):
  list the room types (from the occupancy table), period date ranges
  (expanding stacked dates into separate periods + shared `priceRowGroup`),
  meal plans, per-room child-policy literals.
- **Call B** ([prompts/direct-vision-fill-v1.txt](backend/prompts/direct-vision-fill-v1.txt)):
  given the skeleton as a hard constraint, produce exactly
  `rooms × periods × meals` rows with filled prices.

### 3. Defensive cell audit ([backend/app/services/cell_audit.py](backend/app/services/cell_audit.py))

After extraction, every numeric price cell in the source vision tables is
compared against the prices that ended up in any Hotel row. **Unmapped
source cells become Extraction Notes**, so a value visible in the PDF can
never silently disappear. The Audit tab shows the cell-audit stats:
`source_price_cells`, `mapped_price_values`, `unmapped_cells`, `rows_without_prices`.

### 4. Per-cell metadata + review state

`HotelRow._cellMeta` carries `{confidence, sourceRef}` per field. The
review grid colors low-confidence cells (yellow), tooltips show the
source reference, and `_reviewState` flips from `auto` → `edited` on user
edit (or `verified` when explicitly confirmed). Reviewers know what to
focus on.

### 5. Per-supplier template cache ([backend/app/services/supplier_templates.py](backend/app/services/supplier_templates.py))

On every successful export, the structural skeleton (rooms, periods,
meal plans, dynamic CHD columns) is persisted to
`backend/storage/templates/<supplier-slug>.json`. The next upload from
the same supplier passes this template into the LLM as a strong layout
hint so the model spends its budget on values, not on re-discovering the
structure.

### 6. Regression fixtures (`tests/regression/`)

Pytest-discovered regression suite. Each fixture is a directory with:

```
tests/regression/fixtures/<name>/
  input.<xlsx|pdf|docx|png>     # source contract
  options.json                  # optional upload-form defaults
  expected.json                 # known-good normalized output
```

To add a fixture:

```bash
mkdir backend/tests/regression/fixtures/my-supplier
cp /path/to/contract.xlsx backend/tests/regression/fixtures/my-supplier/input.xlsx
# review the result, then capture expected.json:
cd backend
python -m tests.regression.runner --record my-supplier
# commit input.xlsx, options.json (optional), expected.json
```

The runner uses the deterministic **stub extractor** (no live OpenAI
calls), so the test is reproducible across machines and CI. Any code or
prompt change that breaks a contract's expected output fails fast.

Run only regression tests:

```bash
cd backend
pytest tests/test_regression.py -v
```

## Known limitations

- OCR / vision uses OpenAI vision; if `OPENAI_API_KEY` is unset the image
  parser returns empty text and the LLM stage uses a deterministic stub.
- XLS (legacy) is parsed through openpyxl when possible, then through
  `xlrd` for `.xls` files. Encrypted workbooks are not supported.
- PDF table extraction uses pdfplumber's heuristics. Very visual PDFs fall
  back to vision automatically when `extraction_mode != text_only`.
- The shipping prompt is conservative: ambiguous rows go to Extraction Notes
  rather than fabricating numbers.

## Next recommended improvements

- Move job state from SQLite to Postgres + a real queue (rq / celery / arq).
- Plug Camelot / Tabula in for high-quality PDF table extraction (an
  additional `native_text_llm` enrichment before LLM).
- User accounts + scoped supplier-template store (so multiple users don't
  share a single template namespace).
- Persist edited rows as training data and replay them on future uploads
  from the same supplier (auto-correct from review history).
- Side-by-side source preview alignment: click a cell, show its source
  bbox highlighted on the rendered PDF page.
- Diff view between raw LLM output and edited result for audit trails.
