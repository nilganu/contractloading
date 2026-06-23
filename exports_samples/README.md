# Export samples

Run the backend test suite to generate sample exported workbooks in the
`backend/storage/exports/` directory at runtime, or upload a contract via the
UI and download the result from the review screen.

The exporter produces two sheets:

1. `Hotel` — Moonstride header order:
   `Hotel Name … Extra Bed`,
   then dynamic `CHD(...)` columns from the contract,
   then `SUPP-HB-ADULT, SUPP-HB-CHILD, SUPP-AI-ADULT, SUPP-AI-CHILD`,
   and optionally `_source_refs, _confidence, _warnings` in review mode.
2. `Extraction Notes` — `Source File, Page, Category, Note`.

Strict template mode replaces the dynamic CHD columns with the fixed sample
columns (`CHD(0-2)`, `CHD(0-4)`, `CHD(3-11)`, `CHD(0-10)`, `CHD(5-12)`) and
emits an Extraction Note for every contract child age band that doesn't fit
those buckets so the data is never silently lost.
