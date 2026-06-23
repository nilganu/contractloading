"""Orchestrator for multi-hotel contract extraction (Phase 2).

Flow:
  1. Outline: enumerate hotels in the uploaded file.
     - Excel: free local sheet listing.
     - PDF / DOCX / image / other: one strict-schema LLM call against the
       whole file.
  2. Per hotel: carve a sub-file containing ONLY that hotel's data
     (single-sheet xlsx, single-page-range pdf, or a copy when we can't
     split), upload it to OpenAI, run the canonical extraction with a
     focused user directive, delete the upload.
  3. Aggregate the per-hotel ContractExtractions into one.

Parallelism: bounded thread pool. The OpenAI SDK is thread-safe for
concurrent calls. Each per-hotel call has its OWN sub-file upload, so
calls don't share state with each other beyond the shared client.

Fallback: if outline finds 0–1 hotels or any per-hotel call errors out,
the orchestrator falls through to the single-shot ``extract_contract``
path against the whole file. We always prefer SOME output over none.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from .canonical import ContractExtraction
from .extractor import (
    _make_openai_client,
    extract_contract,
    parse_extraction_with_file,
    upload_file,
)
from .outline import (
    DocumentOutline,
    HotelOutlineEntry,
    outline_excel_locally,
    outline_via_llm,
)
from .splitters import split_for_hotel
from .validators import ValidationIssue, validate_hotel
from .verifier import collect_missing_supplement_names, verify_hotel

logger = logging.getLogger(__name__)

_MAX_PARALLEL = 4
_MAX_RATE_RETRIES = 2
_RETRY_PREVIEW_CAP = 60  # max combinations to print verbatim in retry prompt


def orchestrate_extraction(
    file_path: str | Path,
    *,
    options: Optional[Dict[str, Any]] = None,
) -> ContractExtraction:
    """Run the multi-hotel-aware extraction.

    Single-hotel files go through the existing single-shot path. Multi-
    hotel files are decomposed into per-hotel sub-files and processed in
    parallel.
    """
    file_path = Path(file_path)
    ext = file_path.suffix.lower()
    client = _make_openai_client()

    # ----------------------------------------------------------------------
    # 1. Outline
    # ----------------------------------------------------------------------
    outline: Optional[DocumentOutline] = None
    whole_file_id: Optional[str] = None
    if ext in (".xlsx", ".xls"):
        outline = outline_excel_locally(file_path)
        logger.info(
            "outline (excel, local): %d hotel(s)", len(outline.hotels)
        )
    else:
        # PDF / DOCX / image / other → one LLM call against the whole file
        # to enumerate hotels. We keep the upload around as a fallback.
        try:
            whole_file_id, whole_block = upload_file(client, file_path)
            outline = outline_via_llm(
                client, whole_file_id, whole_block,
                source_filename=file_path.name,
            )
            logger.info(
                "outline (llm): %d hotel(s)", len(outline.hotels)
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "outline pass failed (%s); falling back to single-shot", e
            )
            outline = None

    # ----------------------------------------------------------------------
    # 2. Single-hotel fast path — must STILL go through validate+retry and
    #    the verifier; otherwise single-hotel files get worse coverage
    #    than the per-hotel sub-files in the multi-hotel path.
    # ----------------------------------------------------------------------
    if outline is None or len(outline.hotels) <= 1:
        try:
            if whole_file_id is None:
                whole_file_id, _ = upload_file(client, file_path)
            file_block = {"type": "input_file", "file_id": whole_file_id}
            extraction = parse_extraction_with_file(
                client, file_block,
                file_name=file_path.name, options=options,
            )
            focus_name = (
                outline.hotels[0].name
                if outline and outline.hotels
                else (
                    extraction.hotels[0].metadata.name
                    if extraction.hotels else ""
                )
            )
            extraction = _retry_until_rates_filled(
                client, file_block, file_path, focus_name,
                options, extraction,
            )
            extraction = _verify_and_retry_supplements(
                client, file_block, file_path, focus_name,
                options, extraction,
            )
            _dedup_supplements(extraction)
            return extraction
        finally:
            if whole_file_id is not None:
                _try_delete(client, whole_file_id)

    # ----------------------------------------------------------------------
    # 3. Multi-hotel: per-hotel sub-files in parallel
    # ----------------------------------------------------------------------
    sub_dir = Path(tempfile.mkdtemp(prefix="hotel-extract-"))
    per_hotel_results: List[ContractExtraction] = []
    errors: List[str] = []
    try:
        # Free the whole-file upload — per-hotel calls upload their own
        # sub-files separately.
        if whole_file_id is not None:
            _try_delete(client, whole_file_id)
            whole_file_id = None

        with ThreadPoolExecutor(max_workers=_MAX_PARALLEL) as ex:
            futures = {
                ex.submit(
                    _extract_one_hotel,
                    client, file_path, hotel, sub_dir, options,
                ): hotel
                for hotel in outline.hotels
            }
            for fut in as_completed(futures):
                hotel = futures[fut]
                try:
                    per_hotel_results.append(fut.result())
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{hotel.name}: {type(e).__name__}: {e}")
                    logger.warning(
                        "per-hotel extraction failed for %r: %s",
                        hotel.name, e,
                    )
    finally:
        shutil.rmtree(sub_dir, ignore_errors=True)

    if not per_hotel_results:
        # All per-hotel calls failed → fall back to single-shot.
        logger.warning(
            "no per-hotel results (%d errors); falling back to single-shot",
            len(errors),
        )
        return extract_contract(file_path, options=options)

    logger.info(
        "multi-hotel extraction: %d/%d hotels succeeded",
        len(per_hotel_results), len(outline.hotels),
    )
    return _aggregate(per_hotel_results, source_filename=file_path.name)


# --------------------------------------------------------------------------
# Per-hotel worker
# --------------------------------------------------------------------------


def _extract_one_hotel(
    client,
    src_file: Path,
    hotel: HotelOutlineEntry,
    sub_dir: Path,
    options: Optional[Dict[str, Any]],
) -> ContractExtraction:
    """Carve a sub-file for this hotel, upload it, extract, validate,
    retry on missing rates, delete the upload. Runs inside a worker
    thread."""
    logger.info("per-hotel extraction starting: %r", hotel.name)
    sub_path, mode = split_for_hotel(
        src_file, hotel.name, hotel.source_hint, sub_dir
    )
    logger.info(
        "per-hotel sub-file for %r: %s (mode=%s, size=%dB)",
        hotel.name, sub_path.name, mode, sub_path.stat().st_size,
    )
    file_id, file_block = upload_file(client, sub_path)
    try:
        extraction = parse_extraction_with_file(
            client,
            file_block,
            file_name=src_file.name,
            options=options,
            hotel_focus=hotel.name,
        )
        extraction = _retry_until_rates_filled(
            client, file_block, src_file, hotel.name, options, extraction
        )
        extraction = _verify_and_retry_supplements(
            client, file_block, src_file, hotel.name, options, extraction
        )
        _dedup_supplements(extraction)
        return extraction
    finally:
        _try_delete(client, file_id)


def _verify_and_retry_supplements(
    client,
    file_block: Dict[str, Any],
    src_file: Path,
    hotel_name: str,
    options: Optional[Dict[str, Any]],
    extraction: ContractExtraction,
) -> ContractExtraction:
    """Phase 4 — independent verifier pass per hotel. Surfaces missing
    supplements the LLM dropped (e.g. multi-market gala variants), then
    runs ONE focused retry to fetch them. Failures here are non-fatal —
    if the verifier or retry errors out, the upstream Phase-3 result
    survives unchanged."""
    if not extraction.hotels:
        return extraction
    target = next(
        (
            h for h in extraction.hotels
            if (h.metadata.name or "").strip().lower()
            == hotel_name.strip().lower()
        ),
        extraction.hotels[0],
    )
    supplements_for_hotel = [
        s for s in (extraction.supplements or [])
        if (s.hotel_name or "").strip().lower()
        == (target.metadata.name or "").strip().lower()
    ]
    try:
        report = verify_hotel(
            client, file_block, target, supplements_for_hotel,
            file_name=src_file.name,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "verifier pass failed for %r (%s); skipping verify step",
            hotel_name, e,
        )
        return extraction
    missing_names = collect_missing_supplement_names(report)
    logger.info(
        "verifier %r: %d finding(s), %d missing supplement(s) flagged",
        hotel_name, len(report.findings), len(missing_names),
    )
    if not missing_names:
        return extraction

    directive = _build_missing_supplements_directive(hotel_name, missing_names)
    try:
        patch = parse_extraction_with_file(
            client,
            file_block,
            file_name=src_file.name,
            options=options,
            hotel_focus=hotel_name,
            retry_directive=directive,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "verifier-driven retry failed for %r (%s)", hotel_name, e,
        )
        return extraction

    _merge_new_supplements(extraction, patch, hotel_name)
    return extraction


def _build_missing_supplements_directive(
    hotel_name: str, missing_names: List[str]
) -> str:
    preview = missing_names[:_RETRY_PREVIEW_CAP]
    names_str = "; ".join(f"{n!r}" for n in preview)
    overflow = ""
    if len(missing_names) > len(preview):
        overflow = (
            f" Plus {len(missing_names) - len(preview)} more, following the same pattern."
        )
    return (
        f"RETRY — MISSING SUPPLEMENTS. An audit pass identified these "
        f"supplement rows for hotel {hotel_name!r} as present in the "
        f"contract but absent from your previous extraction: "
        f"{names_str}.{overflow} "
        f"Re-read the relevant sections of the contract and emit the "
        f"missing supplement rows in the `supplements` array. Each "
        f"flagged name may correspond to one OR multiple rows (e.g. one "
        f"Adult row + one Child row). Keep all previously-correct "
        f"supplements; just ADD the missing ones with correct "
        f"hotel_name, charge_type, calculation_method, traveler_type, "
        f"supplier_cost, and any age_min/age_max."
    )


def _merge_new_supplements(
    extraction: ContractExtraction,
    patch: ContractExtraction,
    hotel_name: str,
) -> None:
    """Append new supplements for this hotel from the patch, deduped by
    a stable identity key (name, kind, charge_type, calculation_method,
    traveler_type, ordinal, age_min, age_max, supplier_cost,
    season_label)."""
    def _key(s) -> Any:
        # Identity signature for dedup. The name field is INTENTIONALLY
        # omitted — the LLM frequently rephrases names on retry (e.g.
        # "X- Mass Gala Dinner 24.12.25 Obligatory" → "X-Mass Gala
        # Dinner — 24.12.25"), and a name-based key would let those
        # duplicates through. The combination of dates, traveler type,
        # cost, charge/calc method and season is enough to identify
        # a unique supplement.
        return (
            s.kind, s.charge_type, s.calculation_method,
            s.traveler_type, s.ordinal,
            s.age_min, s.age_max,
            s.supplier_cost, s.customer_price,
            (s.season_label or "").strip().lower(),
            s.start_date, s.end_date,
        )

    existing_keys = {
        _key(s) for s in (extraction.supplements or [])
        if (s.hotel_name or "").strip().lower()
        == hotel_name.strip().lower()
    }
    added = 0
    for s in (patch.supplements or []):
        if (s.hotel_name or "").strip().lower() != hotel_name.strip().lower():
            # Patch may emit supplements tagged differently; force the
            # hotel name we asked for so downstream joins work.
            s.hotel_name = hotel_name
        k = _key(s)
        if k in existing_keys:
            continue
        extraction.supplements.append(s)
        existing_keys.add(k)
        added += 1
    logger.info(
        "merged %d new supplement(s) for hotel %r from verifier-driven retry",
        added, hotel_name,
    )


def _retry_until_rates_filled(
    client,
    file_block: Dict[str, Any],
    src_file: Path,
    hotel_name: str,
    options: Optional[Dict[str, Any]],
    extraction: ContractExtraction,
) -> ContractExtraction:
    """Validate the per-hotel extraction; if rates are missing, re-call
    the LLM with a focused directive naming the exact (room, season,
    meal_code) triples it skipped. Merge new rates back. Stops when
    coverage is acceptable or after ``_MAX_RATE_RETRIES`` attempts."""
    if not extraction.hotels:
        return extraction
    target = next(
        (
            h for h in extraction.hotels
            if (h.metadata.name or "").strip().lower()
            == hotel_name.strip().lower()
        ),
        extraction.hotels[0],
    )

    _dedup_canonical(target)

    for attempt in range(1, _MAX_RATE_RETRIES + 1):
        issues = validate_hotel(target)
        missing_triples: List[Any] = []
        for issue in issues:
            if issue.code == "MISSING_RATES":
                missing_triples.extend(issue.missing_combinations)
        if not missing_triples:
            return extraction

        directive = _build_missing_rates_directive(hotel_name, missing_triples)
        logger.info(
            "retry %d/%d for %r: %d missing rate combinations",
            attempt, _MAX_RATE_RETRIES, hotel_name, len(missing_triples),
        )
        try:
            patch = parse_extraction_with_file(
                client,
                file_block,
                file_name=src_file.name,
                options=options,
                hotel_focus=hotel_name,
                retry_directive=directive,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "retry pass failed for %r (%s); keeping current extraction",
                hotel_name, e,
            )
            return extraction

        _merge_new_rates(target, patch, missing_triples)
        _dedup_canonical(target)

    return extraction


def _dedup_supplements(extraction: ContractExtraction) -> None:
    """Collapse near-duplicate supplements emitted by the LLM in the
    initial pass or any retry. Identity is the SAME signature
    ``_merge_new_supplements`` uses — name is intentionally omitted
    because the model frequently rephrases it across retries (e.g.
    "X- Mass Gala Dinner 24.12.25 Obligatory" → "X-Mass Gala Dinner —
    24.12.25"). The combination of dates, traveler type, cost,
    charge/calc method and season is enough to identify a unique
    supplement.

    Per-hotel scoping: a "Gala 50 EUR Adult" at Hotel A and a separate
    "Gala 50 EUR Adult" at Hotel B are NOT duplicates."""
    def _key(s) -> Any:
        # Use whichever cost field is non-null as the canonical cost so
        # ``(supplier_cost=15, customer_price=None)`` and
        # ``(supplier_cost=None, customer_price=15)`` collapse — the LLM
        # sometimes fills one but not the other across retries.
        cost = s.supplier_cost if s.supplier_cost is not None else s.customer_price
        return (
            (s.hotel_name or "").strip().lower(),
            s.kind, s.charge_type, s.calculation_method,
            s.traveler_type, s.ordinal,
            s.age_min, s.age_max,
            cost,
            (s.season_label or "").strip().lower(),
            s.start_date, s.end_date,
        )

    # Two-pass merge: rather than naive first-seen wins, prefer the
    # entry with the MORE complete data (both prices filled) when
    # keys collide.
    def _completeness(s) -> int:
        return (
            (1 if s.supplier_cost is not None else 0)
            + (1 if s.customer_price is not None else 0)
            + (1 if s.name else 0)
        )

    best_by_key: Dict[Any, Any] = {}
    for s in (extraction.supplements or []):
        k = _key(s)
        existing = best_by_key.get(k)
        if existing is None or _completeness(s) > _completeness(existing):
            best_by_key[k] = s
    unique = list(best_by_key.values())
    if len(unique) != len(extraction.supplements or []):
        logger.info(
            "deduped supplements: %d → %d",
            len(extraction.supplements or []), len(unique),
        )
    extraction.supplements = unique


def _dedup_canonical(hotel) -> None:
    """Collapse LLM-emitted duplicate seasons and duplicate rate rows.

    Seasons are deduped by ``(label, start_date, end_date)`` — the LLM
    sometimes emits the same season repeatedly when it interprets a
    sheet as multi-market and ends up duplicating instead of splitting.
    Rates are deduped by ``(room_name, season_label, meal_code)``,
    keeping the row with the most filled occupancy prices."""
    def _season_key(s) -> Any:
        label = " ".join((s.label or "").lower().split())
        return (label, s.start_date, s.end_date)

    seen_keys = set()
    unique_seasons = []
    for s in hotel.seasons or []:
        key = _season_key(s)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique_seasons.append(s)
    # Date-range subsumption: when one emitted season's range is fully
    # CONTAINED within another's, drop the contained one — that's the
    # "01/04-13/06 & 15/09-31/10" vs "15/09-31/10" Acrotel case where
    # the LLM emitted the combined period AND one of its halves as
    # separate seasons. The longer / earlier period wins because the
    # rates attached to it are typically more complete.
    def _date_tuple(d):
        if not isinstance(d, str) or len(d) < 10:
            return None
        return d[:10]
    by_dates = [(s, _date_tuple(s.start_date), _date_tuple(s.end_date))
                for s in unique_seasons]
    keep = []
    for i, (s, sd, ed) in enumerate(by_dates):
        if sd is None or ed is None:
            keep.append(s)
            continue
        contained = False
        this_norm = " ".join((s.label or "").lower().split())
        for j, (other, osd, oed) in enumerate(by_dates):
            if i == j or osd is None or oed is None:
                continue
            other_norm = " ".join((other.label or "").lower().split())
            # Drop ONLY when (a) the date range is contained AND (b)
            # this season's label appears verbatim inside the wider
            # one's. The label check prevents disjoint multi-part
            # periods ("01/04-13/06 & 15/09-31/10") from swallowing a
            # genuinely separate season ("14/06-31/08") whose dates
            # happen to fall inside the calendar window.
            if (
                osd <= sd and ed <= oed
                and (osd < sd or ed < oed)
                and this_norm
                and this_norm in other_norm
            ):
                contained = True
                break
        if not contained:
            keep.append(s)
    if len(keep) != len(unique_seasons):
        logger.info(
            "subsumed seasons for %r: %d → %d",
            hotel.metadata.name, len(unique_seasons), len(keep),
        )
        unique_seasons = keep
    if len(unique_seasons) != len(hotel.seasons or []):
        logger.info(
            "deduped seasons for %r: %d → %d",
            hotel.metadata.name, len(hotel.seasons or []), len(unique_seasons),
        )
    hotel.seasons = unique_seasons
    # Rate season_labels may point at any of the duplicate-variant labels;
    # collapse to the canonical (lowercased-trimmed) representative so the
    # build_hotel_rows lookup matches.
    label_to_canonical = {}
    for s in hotel.seasons:
        label_to_canonical[
            " ".join((s.label or "").lower().split())
        ] = s.label
    for r in hotel.rates or []:
        normalised = " ".join((r.season_label or "").lower().split())
        canonical = label_to_canonical.get(normalised)
        if canonical is not None:
            r.season_label = canonical

    def _filled_score(r) -> int:
        return sum(
            1 for k in ("sgl", "dbl", "tpl", "qdp")
            if getattr(r, k, None) is not None
        )

    best_by_key: Dict[Any, Any] = {}
    for r in hotel.rates or []:
        key = (r.room_name, r.season_label, r.meal_code)
        existing = best_by_key.get(key)
        if existing is None or _filled_score(r) > _filled_score(existing):
            best_by_key[key] = r
    if len(best_by_key) != len(hotel.rates or []):
        logger.info(
            "deduped rates for %r: %d → %d",
            hotel.metadata.name, len(hotel.rates or []), len(best_by_key),
        )
    hotel.rates = list(best_by_key.values())

    # Child policy bands: source contracts often list the SAME band in
    # two places (e.g. inline child columns on the rate grid PLUS an
    # explicit "Children Policy" section below it). The LLM emits both,
    # then the supplement mapper expands each to N rooms → 2N rows
    # instead of N. Dedup by the band's identity signature so each
    # unique band appears at most once.
    def _band_key(b) -> Any:
        return (
            b.position, b.age_from, b.age_to,
            b.value_type, b.value,
        )

    seen_band_keys = set()
    unique_bands = []
    for b in hotel.child_policy or []:
        k = _band_key(b)
        if k in seen_band_keys:
            continue
        seen_band_keys.add(k)
        unique_bands.append(b)
    if len(unique_bands) != len(hotel.child_policy or []):
        logger.info(
            "deduped child policy bands for %r: %d → %d",
            hotel.metadata.name,
            len(hotel.child_policy or []), len(unique_bands),
        )
    hotel.child_policy = unique_bands


def _build_missing_rates_directive(
    hotel_name: str, missing: List[Any]
) -> str:
    """Compose the targeted retry instruction. We list up to N triples
    verbatim so the LLM can re-look-up the exact cells; beyond that we
    summarise so the prompt doesn't balloon."""
    preview = missing[:_RETRY_PREVIEW_CAP]
    triples_str = "; ".join(
        f"({room!r}, {season!r}, {meal!r})"
        for room, season, meal in preview
    )
    overflow = ""
    if len(missing) > len(preview):
        overflow = (
            f" Plus {len(missing) - len(preview)} more (room, season, "
            f"meal_code) combinations following the same pattern."
        )
    return (
        f"RETRY — RATE-MATRIX GAP. Your previous extraction for hotel "
        f"{hotel_name!r} returned room / season / meal_plan lists that "
        f"imply {len(missing)} more rate cells than you emitted. "
        f"Re-read the rate grid carefully and return a ContractExtraction "
        f"whose hotels[0].rates array INCLUDES at least these specific "
        f"(room_name, season_label, meal_code) combinations, each with "
        f"the correct sgl/dbl/tpl/qdp values from the contract. Use the "
        f"EXACT same strings for room_name / season_label / meal_code as "
        f"in your previous output. Missing triples: {triples_str}.{overflow}"
    )


def _merge_new_rates(
    target,  # HotelExtraction
    patch: ContractExtraction,
    missing_triples: List[Any],
) -> None:
    """Append any newly-filled rates from ``patch`` into ``target.rates``.

    Only adopt rows whose ``(room_name, season_label, meal_code)`` triple
    is in ``missing_triples`` AND that carry at least one numeric price.
    Existing rates are NOT overwritten — the retry only fills gaps."""
    if not patch.hotels:
        return
    new_rates_by_hotel = []
    for h in patch.hotels:
        new_rates_by_hotel.extend(h.rates or [])
    missing_set = {tuple(t) for t in missing_triples}
    existing_keys = {
        (r.room_name, r.season_label, r.meal_code)
        for r in (target.rates or [])
        if any(
            getattr(r, k, None) is not None
            for k in ("sgl", "dbl", "tpl", "qdp")
        )
    }
    added = 0
    for r in new_rates_by_hotel:
        key = (r.room_name, r.season_label, r.meal_code)
        if key not in missing_set or key in existing_keys:
            continue
        if not any(
            getattr(r, k, None) is not None
            for k in ("sgl", "dbl", "tpl", "qdp")
        ):
            continue
        target.rates.append(r)
        existing_keys.add(key)
        added += 1
    logger.info(
        "merged %d new rate(s) into hotel %r (was %d missing)",
        added, target.metadata.name, len(missing_triples),
    )


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------


def _aggregate(
    extractions: List[ContractExtraction],
    *,
    source_filename: str,
) -> ContractExtraction:
    """Merge per-hotel ContractExtractions into one whole-contract object.

    - `hotels`, `supplements`, `notes` are concatenated (deduplicating
      hotels by name).
    - `detected_rate_type` takes the modal value across per-hotel results.
    - `is_multi_hotel` reflects the merged hotel count.
    - `source_filename` reflects the originally-uploaded file.
    """
    seen_hotels: Dict[str, Any] = {}
    supplements: List[Any] = []
    notes: List[Any] = []
    # Weighted vote: each hotel's rate type counts proportionally to how
    # many priced rate rows it contributed. A 100-row hotel outweighs a
    # 1-row hotel where the LLM happened to misclassify.
    rate_type_votes: Dict[str, int] = {}

    for e in extractions:
        weight = 0
        for h in e.hotels:
            for r in (h.rates or []):
                if any(
                    getattr(r, k, None) is not None
                    for k in ("sgl", "dbl", "tpl", "qdp")
                ):
                    weight += 1
        weight = max(weight, 1)
        rate_type_votes[e.detected_rate_type] = (
            rate_type_votes.get(e.detected_rate_type, 0) + weight
        )
        for h in e.hotels:
            key = (h.metadata.name or "").strip().lower()
            if not key or key in seen_hotels:
                continue
            seen_hotels[key] = h
        supplements.extend(e.supplements or [])
        notes.extend(e.notes or [])

    hotels = list(seen_hotels.values())
    detected = (
        max(rate_type_votes.items(), key=lambda kv: kv[1])[0]
        if rate_type_votes
        else "Per Person Per Night"
    )

    return ContractExtraction(
        source_filename=source_filename,
        is_multi_hotel=len(hotels) > 1,
        detected_rate_type=detected,
        hotels=hotels,
        supplements=supplements,
        notes=notes,
    )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _try_delete(client, file_id: str) -> None:
    try:
        client.files.delete(file_id)
    except Exception:  # noqa: BLE001
        logger.warning("could not delete uploaded file %s", file_id)
