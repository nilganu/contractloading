# Fixtures

Drop sample contracts here:

- `Volonline Contract & SPO - Year 2025-2026.xlsx`
- any other supplier contract in XLSX, XLS, PDF, DOCX, PNG, JPG, JPEG or TIFF format

The backend tests generate a synthetic in-memory multi-sheet workbook that
mirrors the Volonline structure (a `Hotel List` index sheet + per-hotel rate
sheets) so the full pipeline runs without committing real supplier
contracts to the repo.

To run the end-to-end UI test against a real fixture:

1. Save the contract here, e.g. `fixtures/Volonline Contract & SPO - Year 2025-2026.xlsx`.
2. Start the backend (`uvicorn app.main:app --reload --port 8000`).
3. Start the frontend (`npm run dev`).
4. Upload the fixture from the UI.
5. Confirm:
   - The pre-extraction summary shows all the workbook sheets.
   - `Hotel List` is classified as `index_reference`.
   - Every other sheet is classified as `hotel_contract`.
   - The review screen lists one or more rows for each hotel sheet.
   - The Hotel Rows grid renders dynamic `CHD(...)` columns that match the
     age bands in the contract (not the strict template's sample columns).
   - The exported XLSX has a `Hotel` sheet and an `Extraction Notes` sheet.
