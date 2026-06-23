"""Canonical Pydantic model for contract extraction.

The LLM populates one ``ContractExtraction`` (via OpenAI strict
``json_schema`` mode through ``client.responses.parse(text_format=...)``).
Everything downstream — both Moonstride Excel files — is derived from
this object by deterministic Python.

Design constraints (so the schema is OpenAI-strict friendly):
- All fields are typed; ``Optional[X] = None`` is the form for nullable.
- Dates use ``str`` (ISO ``YYYY-MM-DD``) — date types serialise fine but
  prompt + downstream code stays simpler with strings.
- Enums use ``Literal[...]``.
- Nesting depth kept modest (well under OpenAI's strict-mode limits).
- No defaults that rely on factories at schema-generation time.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Enumerations (canonical values; LLM is constrained to these)
# --------------------------------------------------------------------------

RateTypeCanonical = Literal[
    "Per Person Per Night",
    "Per Person Per Day",
    "Per Room Per Night",
    "Per Room Per Night (Pax Count)",
    "Per Room Per Stay",
    "Per Person Per Stay",
]

MealPlanCanonical = Literal[
    "Bed and Breakfast",
    "Half board",
    "Full board",
    "Special Full Board",
    "All inclusive",
    "Ultra All Inclusive",
    "Premium All Inclusive",
    "Room only",
    "Breakfast",
    "Continental breakfast",
    "Dinner",
    "Lunch",
    "American",
    "European",
    "Modified American",
    "Family plan",
    "Self-catering",
    "No meals",
    "As brochured",
    "Other",
]

StarRatingCanonical = Literal[
    "1 Star",
    "2 Star",
    "3 Star",
    "4 Star",
    "5 Star",
    "6 Star",
    "7 Star",
    "Boutique Hotel",
    "Self Catering",
]

ChargeTypeCanonical = Literal[
    "Per Person Per Night",
    "Per Room Per Night",
    "Per Person Per Stay",
    "Per Room Per Stay",
]

CalculationMethodCanonical = Literal["Standard", "Pax Count", "Pax Index"]

TravelerTypeCanonical = Literal["Traveller", "Adult", "Child", "Infant"]

ChildPositionCanonical = Literal["first_child", "second_child", "third_child"]

SupplementKindCanonical = Literal[
    "meal_upgrade",
    "single_room",
    "gala_dinner",
    "festive_period",
    "extra_bed",
    "special_offer",
    "transfer",
    "tax",
    "city_fee",
    "honeymoon",
    "room_view",
    "other",
]

BedTypeCanonical = Literal[
    "Single", "Double", "Twin", "King", "Queen", "Sofa bed", "Murphy bed",
    "Tatami mats", "Water bed", "Dorm bed", "Run of the house", "Futon",
    "Full", "Other",
]

# --------------------------------------------------------------------------
# Hotel metadata
# --------------------------------------------------------------------------


class HotelMetadata(BaseModel):
    """One hotel's identity and contact details. One per hotel in the contract."""

    name: str = Field(description="Property/resort name (NEVER a villa/room category).")
    code: Optional[str] = Field(default=None, description="Hotel code if the contract assigns one.")
    sell_channel: Optional[str] = None
    supplier: Optional[str] = None
    star_rating: Optional[StarRatingCanonical] = None
    short_description: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    address_line_3: Optional[str] = None
    address_line_4: Optional[str] = None
    postal_code: Optional[str] = None
    country_code: Optional[str] = Field(default=None, description="ISO-3166-1 alpha-2 uppercase, e.g. 'GR'.")
    county_state_province: Optional[str] = None
    city_area: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    check_in: Optional[str] = Field(default=None, description="'HH:MM' 24h.")
    check_out: Optional[str] = Field(default=None, description="'HH:MM' 24h.")
    currency: Optional[str] = Field(default=None, description="ISO-4217 code, e.g. 'EUR', 'USD'.")
    contract_start: Optional[str] = Field(default=None, description="ISO 'YYYY-MM-DD'.")
    contract_end: Optional[str] = Field(default=None, description="ISO 'YYYY-MM-DD'.")
    contract_period_label: Optional[str] = Field(
        default=None, description="Free-text label, e.g. 'Summer 2025'."
    )


# --------------------------------------------------------------------------
# Rooms / seasons / meal plans
# --------------------------------------------------------------------------


class RoomType(BaseModel):
    """A bookable accommodation unit. Villas/Pavilions/Bungalows/Suites all count as rooms here."""

    name: str
    code: Optional[str] = None
    bed_type: Optional[BedTypeCanonical] = None
    min_adult: Optional[int] = None
    max_adult: Optional[int] = None
    max_pax: Optional[int] = None
    max_rollaways: Optional[int] = None
    max_cribs: Optional[int] = None
    max_children: Optional[int] = None


class Season(BaseModel):
    label: str = Field(description="Contract-given label, e.g. 'High', 'Peak', '01.05-15.05'.")
    start_date: str = Field(description="ISO 'YYYY-MM-DD'.")
    end_date: str = Field(description="ISO 'YYYY-MM-DD'.")
    min_stay: Optional[int] = Field(
        default=None,
        description="Minimum nights required in this season. Null when not specified.",
    )
    release_period: Optional[int] = Field(
        default=None,
        description="Days before arrival when allotment is released back to the hotel.",
    )


class MealPlanEntry(BaseModel):
    code: str = Field(description="Contract code, e.g. 'BB', 'HB', 'PAI', 'AI'.")
    canonical: MealPlanCanonical = Field(description="Closest match from the canonical list.")


# --------------------------------------------------------------------------
# Rates and child policy
# --------------------------------------------------------------------------


class Rate(BaseModel):
    """One rate cell — joins to room name, season label, meal code."""

    room_name: str
    season_label: str
    meal_code: str
    sgl: Optional[float] = Field(default=None, description="Single occupancy / Adult 1 rate.")
    dbl: Optional[float] = Field(default=None, description="Double occupancy / Adult 2 rate.")
    tpl: Optional[float] = Field(default=None, description="Triple occupancy / Adult 3 rate.")
    qdp: Optional[float] = Field(default=None, description="Quad occupancy / Adult 4 rate.")
    extra_bed_adult: Optional[float] = Field(
        default=None,
        description=(
            "Extra-adult charge. If the contract gives a bare currency amount "
            "(e.g. '25 EUR'), store that number and set extra_bed_adult_kind='amount'. "
            "If it's a discount % off the adult rate (e.g. '-30%'), store the "
            "discount number (30) and set extra_bed_adult_kind='discount_percentage' — "
            "the mapper computes the EUR amount per row from that row's adult rate. "
            "Leave null if not applicable."
        ),
    )
    extra_bed_adult_kind: Optional[
        Literal["amount", "discount_percentage"]
    ] = Field(
        default=None,
        description="How to interpret extra_bed_adult. Required when extra_bed_adult is non-null.",
    )
    extra_bed_child: Optional[float] = None
    extra_bed_child_kind: Optional[
        Literal["amount", "discount_percentage"]
    ] = None


class ChildAgeBand(BaseModel):
    """One child-policy band — drives the per-room child supplement rows."""

    position: Optional[ChildPositionCanonical] = Field(
        default=None,
        description="first_child / second_child / third_child if the contract distinguishes by position.",
    )
    label: Optional[str] = Field(default=None, description="Free-form label e.g. '1st Child (2-12)'.")
    age_from: float
    age_to: float
    value_type: Literal[
        "amount", "discount_percentage", "percentage_of_adult", "not_applicable"
    ]
    value: Optional[float] = Field(
        default=None,
        description="For discount_percentage value=50 means 50% off. amount in hotel currency.",
    )
    conditions: Optional[str] = None
    applies_to_rooms: Optional[List[str]] = Field(
        default=None,
        description=(
            "Names of rooms this band applies to. When the contract gives"
            " a per-room child policy table (e.g. 'Double Room: n/a;"
            " Superior/Family: 1st free, 2nd -50%'), emit ONE band per"
            " (room-set × rule) and set this list to the matching room"
            " names. When null/empty, the band applies to ALL rooms."
            " Use the EXACT same strings here as in rooms[].name."
        ),
    )


# --------------------------------------------------------------------------
# Supplements
# --------------------------------------------------------------------------


class Supplement(BaseModel):
    """One supplement line — one Excel row in the Hotel Supplement Import sheet.

    The model is the source of truth; the deterministic mapper applies the
    Standard/Count/Index blanking rule, the Yes/blank forces, the date
    formatting, and the FareType Name canonicalisation.
    """

    name: str = Field(description="Human-readable name, e.g. 'Half Board upgrade'.")
    code: Optional[str] = Field(
        default=None, description="Short stable id, e.g. 'HB-UPGRADE'."
    )
    kind: SupplementKindCanonical
    description: Optional[str] = None
    hotel_name: str = Field(
        description="Must match exactly one HotelMetadata.name in this extraction."
    )
    rooms: Optional[str] = Field(
        default=None,
        description="Free-text room scope, e.g. 'All Rooms', 'Beach Pavilion only'.",
    )
    rate_plans: Optional[str] = None
    min_stay: Optional[int] = None
    max_stay: Optional[int] = None
    suppliment_type: Optional[str] = Field(
        default=None,
        description="Contract's supplement type/category label, free text.",
    )
    display_as_separate_room: Optional[Literal["Yes", "No"]] = Field(
        default=None, description="Default 'No' if unset."
    )
    contract_period: Optional[str] = None
    season_label: Optional[str] = None
    start_date: Optional[str] = Field(default=None, description="ISO 'YYYY-MM-DD'.")
    end_date: Optional[str] = Field(default=None, description="ISO 'YYYY-MM-DD'.")
    charge_type: ChargeTypeCanonical
    calculation_method: CalculationMethodCanonical
    traveler_type: TravelerTypeCanonical
    ordinal: Optional[int] = Field(
        default=None,
        description=(
            "For Pax Count: how many travelers of this type (1, 2, 3, ...; 0 for Extra). "
            "For Pax Index: ordinal position (1, 2, 3). For Standard: leave null."
        ),
    )
    fare_type_name: Optional[str] = Field(
        default=None,
        description=(
            "For Standard the mapper sets 'Per Adult'/'Per Child'/'Per Infant'. "
            "For Pax Count/Pax Index emit the contract's label here, "
            "e.g. 'ABC Adult', '1st Adult', '1 Child (2-12)'."
        ),
    )
    age_min: Optional[float] = None
    age_max: Optional[float] = None
    supplier_cost: Optional[float] = None
    customer_price: Optional[float] = None
    cost_format: Literal["amount", "percentage"] = Field(
        default="amount",
        description=(
            "How to interpret supplier_cost / customer_price. "
            "'amount' (default) = the value is a literal EUR figure. "
            "'percentage' = the value is a percent of the room rate "
            "(e.g. 50 means 50%). The mapper renders percentage values "
            "as 'N%' strings in the Supplier Cost / Customer Price "
            "cells so the contract semantics survive to the Excel."
        ),
    )


# --------------------------------------------------------------------------
# Per-hotel + whole-contract aggregates
# --------------------------------------------------------------------------


class ExtractionNote(BaseModel):
    """Free-form note (cancellation terms, taxes, payment terms, etc.) for review."""

    category: Literal[
        "Cancellation",
        "Payment terms",
        "Taxes",
        "Service charge",
        "Booking window",
        "Minimum stay",
        "Room allocation",
        "Special offer",
        "Source ambiguity",
        "Other",
    ]
    note: str
    hotel_name: Optional[str] = None


class HotelExtraction(BaseModel):
    metadata: HotelMetadata
    rooms: List[RoomType]
    seasons: List[Season]
    meal_plans: List[MealPlanEntry]
    rates: List[Rate]
    child_policy: List[ChildAgeBand]


class ContractExtraction(BaseModel):
    """Root extraction object — what GPT returns via ``responses.parse(text_format=...)``."""

    source_filename: str
    is_multi_hotel: bool
    detected_rate_type: RateTypeCanonical = Field(
        description="Dominant rate type across hotels; drives the Moonstride hotel template choice."
    )
    hotels: List[HotelExtraction]
    supplements: List[Supplement] = Field(
        description=(
            "Flat list — each supplement carries hotel_name so multi-hotel contracts "
            "still work. Use [] when the contract has no supplements."
        )
    )
    notes: List[ExtractionNote] = Field(
        description="Cancellation, payment, T&C and other notes. Use [] if none."
    )
