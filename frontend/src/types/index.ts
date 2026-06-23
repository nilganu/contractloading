// Types mirror the backend Pydantic schemas (app/schemas/models.py)

export type ExtractionMode = "auto" | "text_only" | "vision_allowed" | "vision_required";
export type ChildColumnMode = "dynamic_review" | "dynamic_export" | "strict_template";

export type JobStatus =
  | "uploaded"
  | "detecting_file_type"
  | "parsing"
  | "extracting_tables"
  | "classifying_sheets_or_pages"
  | "running_ocr_or_vision"
  | "building_intermediate_representation"
  | "running_llm_extraction"
  | "normalizing"
  | "validating"
  | "ready_for_review"
  | "exporting"
  | "completed"
  | "failed";

export interface ExtractionOptions {
  supplierDefault?: string | null;
  countryDefault?: string | null;
  cityAreaDefault?: string | null;
  currencyDefault?: string | null;
  statusDefault?: string | null;
  checkInDefault?: string | null;
  checkOutDefault?: string | null;
  childColumnMode: ChildColumnMode;
  preserveChildPositions: boolean;
  extractionMode: ExtractionMode;
}

export interface DynamicChildColumn {
  key: string;
  label: string;
  ageFrom: number | null;
  ageTo: number | null;
  ageLabel: string | null;
  childPosition: "first_child" | "second_child" | "third_child" | null;
  valueType:
    | "amount"
    | "percentage_of_adult"
    | "discount_percentage"
    | "formula"
    | "not_applicable"
    | "unknown";
}

export interface HotelRow {
  id: string;
  sourceSheetOrPage: string;
  "Hotel Name": string | null;
  Supplier: string | null;
  "Star Rating": string | null;
  "Short Description": string | null;
  "Address Line 1": string | null;
  "Address Line 2": string | null;
  "Address Line 3": string | null;
  "Address Line 4": string | null;
  "Postal Code": string | null;
  "Country Code ": string | null; // trailing space is intentional
  "State / Province / Region": string | null;
  "City / Area": string | null;
  "Phone Number": string | null;
  "Email Address": string | null;
  "Hotel Website": string | null;
  Latitude: number | null;
  Longitude: number | null;
  "Check-In": string | null;
  "Check-Out": string | null;
  Currency: string | null;
  "Rate Type": string | null;
  "Room Name": string | null;
  "Min Adult": number | null;
  "Max Adult": number | null;
  "Max Pax": number | null;
  Season: string | null;
  "Start Date": string | null;
  "End Date": string | null;
  Days: string | null;
  "Min Stay": number | null;
  "Rate Plan": string | null;
  "Meal Plan": string | null;
  Status: string | null;
  "Booking Limit": number | null;
  "Release Period": number | null;
  "Customer Price Currency": string | null;
  "Add Charge Type": string | null;
  "Add Charge Value": number | null;
  Charge: number | string | null;
  SGL: number | null;
  DBL: number | null;
  TPL: number | null;
  QDP: number | null;
  "Extra Bed": number | null;
  dynamicChildValues: Record<string, number | null>;
  "SUPP-HB-ADULT": number | null;
  "SUPP-HB-CHILD": number | null;
  "SUPP-AI-ADULT": number | null;
  "SUPP-AI-CHILD": number | null;
  _childPolicyDetails?: unknown[];
  _sourceRefs?: string[];
  _confidence?: number;
  _warnings?: string[];
  // Per-field metadata. Keys are header strings or CHD dynamic keys.
  _cellMeta?: Record<string, { confidence?: number; sourceRef?: string | null }>;
  _reviewState?: "auto" | "verified" | "edited";
}

export interface ExtractionNote {
  id: string;
  "Source File": string;
  Page: string;
  Category: string;
  Note: string;
  _sourceRefs?: string[];
  _confidence?: number;
  hotelName?: string | null;
  linkedHotelRowId?: string | null;
}

export interface ValidationIssue {
  id: string;
  severity: "error" | "warning" | "info";
  message: string;
  sourceRef: string | null;
  hotelName: string | null;
  sheetOrPage: string | null;
  hotelRowId?: string | null;
  field?: string | null;
  quickFixType?: string | null;
}

export interface WorkbookSummary {
  sourceFile: string;
  inputFormat: string;
  sheetsOrPagesProcessed: string[];
  indexSheets: string[];
  hotelSheets: string[];
  ignoredSheetsOrPages: Array<{ name: string; reason: string }>;
  overallConfidence: number;
}

export interface NormalizedExtractionResult {
  workbookSummary: WorkbookSummary;
  dynamicColumns: { childColumns: DynamicChildColumn[] };
  hotels: unknown[];
  hotelRows: HotelRow[];
  extractionNotes: ExtractionNote[];
  validationIssues: ValidationIssue[];
}

export interface JobStatusResponse {
  id: string;
  status: JobStatus;
  progress: number;
  fileName: string;
  fileType: string | null;
  warnings: string[];
  errors: string[];
  sheetSummary: Array<{
    id: string;
    kind: string;
    classification: string;
    detectedHotelName: string | null;
    sourceRef: string;
    summary: Record<string, unknown>;
  }>;
  options: ExtractionOptions;
  createdAt: string;
  updatedAt: string;
}

export interface JobResultResponse {
  jobId: string;
  status: JobStatus;
  options: ExtractionOptions;
  result: NormalizedExtractionResult;
}

export interface TemplateMetadata {
  fixedBaseHeaders: string[];
  fixedSupplementHeaders: string[];
  strictTemplateChildColumns: string[];
  extractionNotesHeaders: string[];
}

export interface AuditResponse {
  jobId: string;
  fileName: string;
  fileType: string | null;
  parserVersion: string;
  promptVersion: string;
  openaiModel: string | null;
  extractionMode: string;
  audit: Array<{ at: string; event: string; detail: Record<string, unknown> }>;
  warnings: string[];
  errors: string[];
  createdAt: string;
  updatedAt: string;
  exportPath: string | null;
}
