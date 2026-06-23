"""Business / blocking rule validator.

Produces ValidationIssue records keyed to rows or notes. Blocking errors
must prevent export in strict modes; warnings are surfaced in the UI but
don't block export (UI requires explicit confirmation to export-with-warnings).
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List


REQUIRED_FIELDS = ["Hotel Name", "Room Name", "Start Date", "End Date"]


def _make_issue(
    *,
    severity: str,
    message: str,
    hotel_row_id: str | None = None,
    hotel_name: str | None = None,
    sheet_or_page: str | None = None,
    field: str | None = None,
    source_ref: str | None = None,
    quick_fix_type: str | None = None,
) -> Dict[str, Any]:
    return {
        "id": f"issue_{uuid.uuid4().hex[:8]}",
        "severity": severity,
        "message": message,
        "sourceRef": source_ref,
        "hotelName": hotel_name,
        "sheetOrPage": sheet_or_page,
        "hotelRowId": hotel_row_id,
        "field": field,
        "quickFixType": quick_fix_type,
    }


def _date_diff_days(start: str, end: str) -> int | None:
    try:
        sy, sm, sd = (int(x) for x in start.split("-"))
        ey, em, ed = (int(x) for x in end.split("-"))
        return (date(ey, em, ed) - date(sy, sm, sd)).days + 1
    except Exception:  # noqa: BLE001
        return None


def validate_result(result: Dict[str, Any], options: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    mode = options.get("childColumnMode", "dynamic_review")

    for row in result.get("hotelRows", []):
        row_id = row.get("id")
        sheet = row.get("sourceSheetOrPage")
        hotel = row.get("Hotel Name")

        # blocking errors
        for f in REQUIRED_FIELDS:
            if row.get(f) in (None, ""):
                issues.append(
                    _make_issue(
                        severity="error",
                        message=f"Required field missing: {f}",
                        hotel_row_id=row_id,
                        hotel_name=hotel,
                        sheet_or_page=sheet,
                        field=f,
                        quick_fix_type=(
                            "set_default_supplier"
                            if f == "Supplier"
                            else None
                        ),
                    )
                )

        start = row.get("Start Date")
        end = row.get("End Date")
        if start and end:
            diff = _date_diff_days(start, end)
            if diff is None:
                issues.append(
                    _make_issue(
                        severity="error",
                        message="Start Date or End Date is malformed",
                        hotel_row_id=row_id,
                        hotel_name=hotel,
                        sheet_or_page=sheet,
                        field="Start Date",
                    )
                )
            elif diff <= 0:
                issues.append(
                    _make_issue(
                        severity="error",
                        message="End Date is before or equal to Start Date",
                        hotel_row_id=row_id,
                        hotel_name=hotel,
                        sheet_or_page=sheet,
                        field="End Date",
                    )
                )
            # Note: 'Days' is a Moonstride weekday-mask (eg "0,1,2,3,4,5,6"),
            # NOT an inclusive night count, so we no longer validate it
            # against the date range.

        # warnings
        if not row.get("Currency"):
            issues.append(
                _make_issue(
                    severity="warning",
                    message="Currency missing",
                    hotel_row_id=row_id,
                    hotel_name=hotel,
                    sheet_or_page=sheet,
                    field="Currency",
                    quick_fix_type="set_default_currency",
                )
            )
        if not row.get("Customer Price Currency"):
            issues.append(
                _make_issue(
                    severity="warning",
                    message="Customer Price Currency missing",
                    hotel_row_id=row_id,
                    hotel_name=hotel,
                    sheet_or_page=sheet,
                    field="Customer Price Currency",
                    quick_fix_type="copy_currency_to_customer",
                )
            )
        if not row.get("Rate Type"):
            issues.append(
                _make_issue(
                    severity="warning",
                    message="Rate Type missing",
                    hotel_row_id=row_id,
                    hotel_name=hotel,
                    sheet_or_page=sheet,
                    field="Rate Type",
                )
            )
        if not row.get("Rate Plan"):
            issues.append(
                _make_issue(
                    severity="warning",
                    message="Rate Plan missing",
                    hotel_row_id=row_id,
                    hotel_name=hotel,
                    sheet_or_page=sheet,
                    field="Rate Plan",
                )
            )
        if not row.get("Meal Plan"):
            issues.append(
                _make_issue(
                    severity="warning",
                    message="Meal Plan missing",
                    hotel_row_id=row_id,
                    hotel_name=hotel,
                    sheet_or_page=sheet,
                    field="Meal Plan",
                )
            )
        if not row.get("_sourceRefs"):
            issues.append(
                _make_issue(
                    severity="warning",
                    message="Source reference missing",
                    hotel_row_id=row_id,
                    hotel_name=hotel,
                    sheet_or_page=sheet,
                )
            )
        if (row.get("_confidence") or 0) < 0.4:
            issues.append(
                _make_issue(
                    severity="warning",
                    message=f"Low confidence ({row.get('_confidence'):.2f})",
                    hotel_row_id=row_id,
                    hotel_name=hotel,
                    sheet_or_page=sheet,
                )
            )

        if mode == "strict_template":
            from ..schemas.models import STRICT_TEMPLATE_CHILD_COLUMNS

            for k in row.get("dynamicChildValues", {}).keys():
                if k not in STRICT_TEMPLATE_CHILD_COLUMNS:
                    issues.append(
                        _make_issue(
                            severity="warning",
                            message=(
                                f"Child age band '{k}' is not in the strict template. "
                                "Value will be moved to Extraction Notes on export."
                            ),
                            hotel_row_id=row_id,
                            hotel_name=hotel,
                            sheet_or_page=sheet,
                            field=k,
                        )
                    )

    # info-level — surface unknown sheets
    for entry in result.get("workbookSummary", {}).get("ignoredSheetsOrPages", []):
        issues.append(
            _make_issue(
                severity="info",
                message=f"Sheet/page ignored: {entry.get('name')} ({entry.get('reason')})",
                sheet_or_page=entry.get("name"),
            )
        )

    return issues
