import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

import HotelRowsGrid from "../src/components/HotelRowsGrid";
import type { NormalizedExtractionResult, TemplateMetadata } from "../src/types";

const TEMPLATE: TemplateMetadata = {
  fixedBaseHeaders: ["Hotel Name", "Room Name", "Start Date", "End Date", "Currency"],
  fixedSupplementHeaders: ["SUPP-AI-CHILD"],
  strictTemplateChildColumns: ["CHD(0-2)", "CHD(3-11)"],
  extractionNotesHeaders: ["Source File", "Page", "Category", "Note"],
};

function makeResult(): NormalizedExtractionResult {
  return {
    workbookSummary: {
      sourceFile: "x.xlsx",
      inputFormat: "xlsx",
      sheetsOrPagesProcessed: ["Sheet:Hotel A"],
      indexSheets: [],
      hotelSheets: ["Sheet:Hotel A"],
      ignoredSheetsOrPages: [],
      overallConfidence: 0.5,
    },
    dynamicColumns: {
      childColumns: [
        {
          key: "CHD(2-11.99)",
          label: "CHD(2-11.99)",
          ageFrom: 2,
          ageTo: 11.99,
          ageLabel: null,
          childPosition: null,
          valueType: "amount",
        },
      ],
    },
    hotels: [],
    hotelRows: [
      {
        id: "row1",
        sourceSheetOrPage: "Sheet:Hotel A",
        "Hotel Name": "Hotel A",
        "Room Name": "Standard",
        "Start Date": "2025-05-01",
        "End Date": "2025-10-31",
        Currency: "EUR",
        "Customer Price Currency": "EUR",
        Supplier: null,
        "Star Rating": null,
        "Short Description": null,
        "Address Line 1": null,
        "Address Line 2": null,
        "Address Line 3": null,
        "Address Line 4": null,
        "Postal Code": null,
        "Country Code ": null,
        "State / Province / Region": null,
        "City / Area": null,
        "Phone Number": null,
        "Email Address": null,
        "Hotel Website": null,
        Latitude: null,
        Longitude: null,
        "Check-In": null,
        "Check-Out": null,
        "Rate Type": null,
        "Min Adult": null,
        "Max Adult": null,
        "Max Pax": null,
        Season: null,
        Days: "1234567",
        "Min Stay": null,
        "Rate Plan": "Contract",
        "Meal Plan": "Bed & Breakfast",
        Status: "Open",
        "Booking Limit": null,
        "Release Period": null,
        "Add Charge Type": null,
        "Add Charge Value": null,
        Charge: null,
        SGL: null,
        DBL: 120,
        TPL: null,
        QDP: null,
        "Extra Bed": null,
        dynamicChildValues: { "CHD(2-11.99)": 60 },
        "SUPP-HB-ADULT": null,
        "SUPP-HB-CHILD": null,
        "SUPP-AI-ADULT": null,
        "SUPP-AI-CHILD": null,
        _confidence: 0.6,
        _sourceRefs: ["x.xlsx | Hotel A!A1:S20"],
        _warnings: [],
      },
    ],
    extractionNotes: [],
    validationIssues: [],
  };
}

describe("HotelRowsGrid", () => {
  it("renders dynamic child columns from the result", () => {
    const onPatch = vi.fn();
    render(
      <HotelRowsGrid
        result={makeResult()}
        template={TEMPLATE}
        onPatch={onPatch}
        patching={false}
      />
    );
    expect(screen.getByTitle("CHD(2-11.99)")).toBeInTheDocument();
    expect(screen.getByTitle("SUPP-AI-CHILD")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Hotel A")).toBeInTheDocument();
    expect(screen.getByDisplayValue("60")).toBeInTheDocument();
  });

  it("emits a patch when a cell is edited and blurred", () => {
    const onPatch = vi.fn();
    render(
      <HotelRowsGrid
        result={makeResult()}
        template={TEMPLATE}
        onPatch={onPatch}
        patching={false}
      />
    );
    const hotelInput = screen.getByDisplayValue("Hotel A");
    fireEvent.change(hotelInput, { target: { value: "Hotel Edited" } });
    fireEvent.blur(hotelInput);
    expect(onPatch).toHaveBeenCalledTimes(1);
    const patched = onPatch.mock.calls[0][0] as NormalizedExtractionResult;
    expect(patched.hotelRows[0]["Hotel Name"]).toBe("Hotel Edited");
  });
});
