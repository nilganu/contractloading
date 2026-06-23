"""Shared data model — Pydantic schemas.

Mirrors the TypeScript types described in the product spec. The frontend has
parallel TypeScript types but the backend is the source of truth.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ExtractionMode(str, Enum):
    auto = "auto"
    text_only = "text_only"
    vision_allowed = "vision_allowed"
    vision_required = "vision_required"


class ChildColumnMode(str, Enum):
    dynamic_review = "dynamic_review"
    dynamic_export = "dynamic_export"
    strict_template = "strict_template"


class ExtractionOptions(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    supplierDefault: Optional[str] = None
    countryDefault: Optional[str] = None
    cityAreaDefault: Optional[str] = None
    currencyDefault: Optional[str] = None
    statusDefault: Optional[str] = None
    checkInDefault: Optional[str] = None
    checkOutDefault: Optional[str] = None
    childColumnMode: ChildColumnMode = ChildColumnMode.dynamic_review
    preserveChildPositions: bool = True
    extractionMode: ExtractionMode = ExtractionMode.auto


class DynamicChildColumn(BaseModel):
    key: str
    label: str
    ageFrom: Optional[float] = None
    ageTo: Optional[float] = None
    ageLabel: Optional[str] = None
    childPosition: Optional[Literal["first_child", "second_child", "third_child"]] = None
    valueType: Literal[
        "amount",
        "percentage_of_adult",
        "discount_percentage",
        "formula",
        "not_applicable",
        "unknown",
    ] = "unknown"


class ChildPolicy(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sourceRange: Optional[str] = None
    dynamicColumnName: Optional[str] = None
    ageFrom: Optional[float] = None
    ageTo: Optional[float] = None
    ageLabel: Optional[str] = None
    childPosition: Optional[Literal["first_child", "second_child", "third_child"]] = None
    roomCondition: Optional[str] = None
    mealPlanCondition: Optional[str] = None
    seasonCondition: Optional[str] = None
    stayDateFrom: Optional[str] = None
    stayDateTo: Optional[str] = None
    occupancyCondition: Optional[str] = None
    value: Optional[Any] = None
    valueType: Literal[
        "amount",
        "percentage_of_adult",
        "discount_percentage",
        "formula",
        "not_applicable",
        "unknown",
    ] = "unknown"
    meaning: Literal[
        "free",
        "charged_percentage",
        "discount_percentage",
        "fixed_amount",
        "same_as_adult",
        "meal_supplement_only",
        "not_applicable",
        "unknown",
    ] = "unknown"
    calculationBasis: Optional[str] = None
    sourceColumn: Optional[str] = None
    confidence: float = 0.5
    warnings: List[str] = Field(default_factory=list)


class ChildPolicyDetail(BaseModel):
    """Lightweight subset stored on a HotelRow for quick reference."""
    dynamicColumnName: Optional[str] = None
    ageLabel: Optional[str] = None
    meaning: Optional[str] = None
    value: Optional[Any] = None


class HotelMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    hotelName: Optional[str] = None
    supplier: Optional[str] = None
    starRating: Optional[str] = None
    shortDescription: Optional[str] = None
    addressLine1: Optional[str] = None
    addressLine2: Optional[str] = None
    addressLine3: Optional[str] = None
    addressLine4: Optional[str] = None
    postalCode: Optional[str] = None
    countryCode: Optional[str] = None
    stateOrRegion: Optional[str] = None
    cityOrArea: Optional[str] = None
    phoneNumber: Optional[str] = None
    emailAddress: Optional[str] = None
    hotelWebsite: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    checkIn: Optional[str] = None
    checkOut: Optional[str] = None
    currency: Optional[str] = None


class RoomType(BaseModel):
    name: str
    minAdult: Optional[int] = None
    maxAdult: Optional[int] = None
    maxPax: Optional[int] = None
    notes: Optional[str] = None


class RateBlock(BaseModel):
    title: Optional[str] = None
    ratePlan: Optional[str] = None
    season: Optional[str] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    sourceRange: Optional[str] = None


class HotelExtraction(BaseModel):
    hotelName: str
    sourceSheetOrPage: str
    metadata: HotelMetadata
    rateBlocks: List[RateBlock] = Field(default_factory=list)
    roomTypes: List[RoomType] = Field(default_factory=list)
    childPolicies: List[ChildPolicy] = Field(default_factory=list)


class HotelRow(BaseModel):
    """The flat row that maps to one line in the Moonstride Hotel sheet."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str
    sourceSheetOrPage: str

    # Strict Moonstride headers — keys match the export header exactly.
    hotel_name: Optional[str] = Field(default=None, alias="Hotel Name")
    supplier: Optional[str] = Field(default=None, alias="Supplier")
    star_rating: Optional[str] = Field(default=None, alias="Star Rating")
    short_description: Optional[str] = Field(default=None, alias="Short Description")
    address_line_1: Optional[str] = Field(default=None, alias="Address Line 1")
    address_line_2: Optional[str] = Field(default=None, alias="Address Line 2")
    address_line_3: Optional[str] = Field(default=None, alias="Address Line 3")
    address_line_4: Optional[str] = Field(default=None, alias="Address Line 4")
    postal_code: Optional[str] = Field(default=None, alias="Postal Code")
    # Note: the Moonstride header has a trailing space — we preserve it.
    country_code: Optional[str] = Field(default=None, alias="Country Code ")
    state_region: Optional[str] = Field(default=None, alias="State / Province / Region")
    city_area: Optional[str] = Field(default=None, alias="City / Area")
    phone_number: Optional[str] = Field(default=None, alias="Phone Number")
    email_address: Optional[str] = Field(default=None, alias="Email Address")
    hotel_website: Optional[str] = Field(default=None, alias="Hotel Website")
    latitude: Optional[float] = Field(default=None, alias="Latitude")
    longitude: Optional[float] = Field(default=None, alias="Longitude")
    check_in: Optional[str] = Field(default=None, alias="Check-In")
    check_out: Optional[str] = Field(default=None, alias="Check-Out")
    currency: Optional[str] = Field(default=None, alias="Currency")
    rate_type: Optional[str] = Field(default=None, alias="Rate Type")
    room_name: Optional[str] = Field(default=None, alias="Room Name")
    min_adult: Optional[int] = Field(default=None, alias="Min Adult")
    max_adult: Optional[int] = Field(default=None, alias="Max Adult")
    max_pax: Optional[int] = Field(default=None, alias="Max Pax")
    season: Optional[str] = Field(default=None, alias="Season")
    start_date: Optional[str] = Field(default=None, alias="Start Date")
    end_date: Optional[str] = Field(default=None, alias="End Date")
    # Moonstride 'Days' is a weekday mask, not an inclusive night count.
    # Stored as a string: "0 to 6" = active all days, "0,6" = Sun + Sat
    # only, "1 to 5" = weekdays only, etc.
    days: Optional[str] = Field(default=None, alias="Days")
    min_stay: Optional[int] = Field(default=None, alias="Min Stay")
    rate_plan: Optional[str] = Field(default=None, alias="Rate Plan")
    meal_plan: Optional[str] = Field(default=None, alias="Meal Plan")
    status: Optional[str] = Field(default=None, alias="Status")
    booking_limit: Optional[int] = Field(default=None, alias="Booking Limit")
    release_period: Optional[int] = Field(default=None, alias="Release Period")
    customer_price_currency: Optional[str] = Field(default=None, alias="Customer Price Currency")
    add_charge_type: Optional[str] = Field(default=None, alias="Add Charge Type")
    add_charge_value: Optional[float] = Field(default=None, alias="Add Charge Value")
    charge: Optional[Any] = Field(default=None, alias="Charge")
    sgl: Optional[float] = Field(default=None, alias="SGL")
    dbl: Optional[float] = Field(default=None, alias="DBL")
    tpl: Optional[float] = Field(default=None, alias="TPL")
    qdp: Optional[float] = Field(default=None, alias="QDP")
    extra_bed: Optional[float] = Field(default=None, alias="Extra Bed")

    dynamicChildValues: Dict[str, Optional[float]] = Field(default_factory=dict)

    supp_hb_adult: Optional[float] = Field(default=None, alias="SUPP-HB-ADULT")
    supp_hb_child: Optional[float] = Field(default=None, alias="SUPP-HB-CHILD")
    supp_ai_adult: Optional[float] = Field(default=None, alias="SUPP-AI-ADULT")
    supp_ai_child: Optional[float] = Field(default=None, alias="SUPP-AI-CHILD")

    childPolicyDetails: List[ChildPolicyDetail] = Field(
        default_factory=list, alias="_childPolicyDetails"
    )
    sourceRefs: List[str] = Field(default_factory=list, alias="_sourceRefs")
    confidence: float = Field(default=0.5, alias="_confidence")
    warnings: List[str] = Field(default_factory=list, alias="_warnings")
    # Per-field metadata. Keys are Moonstride header strings or dynamic CHD
    # keys; values are {confidence: 0..1, sourceRef: "Page:N | bbox(...)"}.
    cellMeta: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict, alias="_cellMeta"
    )
    # User review state. "auto" = produced by LLM. "verified" = a human
    # confirmed the row's values. "edited" = a human changed values after auto.
    reviewState: str = Field(default="auto", alias="_reviewState")


class ExtractionNote(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    source_file: str = Field(alias="Source File")
    page: str = Field(default="", alias="Page")
    category: str = Field(alias="Category")
    note: str = Field(alias="Note")
    sourceRefs: List[str] = Field(default_factory=list, alias="_sourceRefs")
    confidence: float = Field(default=0.5, alias="_confidence")
    hotelName: Optional[str] = None
    linkedHotelRowId: Optional[str] = None


class ValidationIssue(BaseModel):
    id: str
    severity: Literal["error", "warning", "info"]
    message: str
    sourceRef: Optional[str] = None
    hotelName: Optional[str] = None
    sheetOrPage: Optional[str] = None
    hotelRowId: Optional[str] = None
    field: Optional[str] = None
    quickFixType: Optional[str] = None


class WorkbookSummary(BaseModel):
    sourceFile: str
    inputFormat: Literal["xlsx", "xls", "pdf", "docx", "image", "mixed", "unknown"]
    sheetsOrPagesProcessed: List[str] = Field(default_factory=list)
    indexSheets: List[str] = Field(default_factory=list)
    hotelSheets: List[str] = Field(default_factory=list)
    ignoredSheetsOrPages: List[Dict[str, Any]] = Field(default_factory=list)
    overallConfidence: float = 0.5


class NormalizedExtractionResult(BaseModel):
    workbookSummary: WorkbookSummary
    dynamicColumns: Dict[str, List[DynamicChildColumn]]
    hotels: List[HotelExtraction] = Field(default_factory=list)
    hotelRows: List[HotelRow] = Field(default_factory=list)
    extractionNotes: List[ExtractionNote] = Field(default_factory=list)
    validationIssues: List[ValidationIssue] = Field(default_factory=list)


# Strict, ordered list of fixed Moonstride header columns (before dynamic
# child columns). Trailing space on "Country Code " is intentional.
FIXED_BASE_HEADERS: List[str] = [
    "Hotel Name",
    "Supplier",
    "Star Rating",
    "Short Description",
    "Address Line 1",
    "Address Line 2",
    "Address Line 3",
    "Address Line 4",
    "Postal Code",
    "Country Code ",
    "State / Province / Region",
    "City / Area",
    "Phone Number",
    "Email Address",
    "Hotel Website",
    "Latitude",
    "Longitude",
    "Check-In",
    "Check-Out",
    "Currency",
    "Rate Type",
    "Room Name",
    "Min Adult",
    "Max Adult",
    "Max Pax",
    "Season",
    "Start Date",
    "End Date",
    "Days",
    "Min Stay",
    "Rate Plan",
    "Meal Plan",
    "Status",
    "Booking Limit",
    "Release Period",
    "Customer Price Currency",
    "Add Charge Type",
    "Add Charge Value",
    "Charge",
    "SGL",
    "DBL",
    "TPL",
    "QDP",
    "Extra Bed",
]

FIXED_SUPP_HEADERS: List[str] = [
    "SUPP-HB-ADULT",
    "SUPP-HB-CHILD",
    "SUPP-AI-ADULT",
    "SUPP-AI-CHILD",
]

STRICT_TEMPLATE_CHILD_COLUMNS: List[str] = [
    "CHD(0-2)",
    "CHD(0-4)",
    "CHD(3-11)",
    "CHD(0-10)",
    "CHD(5-12)",
]

EXTRACTION_NOTES_HEADERS: List[str] = ["Source File", "Page", "Category", "Note"]

NOTE_CATEGORIES: List[str] = [
    "Taxes/service",
    "Child policy",
    "Cancellation",
    "Gala dinner",
    "Special offer",
    "Booking window",
    "Minimum stay",
    "Room allocation",
    "Rate anomaly",
    "Meal plan nuance",
    "Room supplement",
    "Source ambiguity",
    "Other",
]
