import { render, screen, fireEvent } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";

import UploadPage from "../src/pages/UploadPage";

vi.mock("../src/api/client", () => ({
  uploadContract: vi.fn(async () => ({
    id: "job_123",
    status: "uploaded",
    progress: 0,
    fileName: "x.xlsx",
    fileType: "xlsx",
    warnings: [],
    errors: [],
    sheetSummary: [],
    options: {
      childColumnMode: "dynamic_review",
      preserveChildPositions: true,
      extractionMode: "auto",
    },
    createdAt: "",
    updatedAt: "",
  })),
}));

function wrap(node: React.ReactNode) {
  const qc = new QueryClient();
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>{node}</BrowserRouter>
    </QueryClientProvider>
  );
}

describe("UploadPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders extraction option controls", () => {
    render(wrap(<UploadPage />));
    expect(screen.getByText(/Upload contract/i)).toBeInTheDocument();
    expect(screen.getByText(/Child column mode/i)).toBeInTheDocument();
    expect(screen.getByText(/Extraction mode/i)).toBeInTheDocument();
  });

  it("disables submit when no file is chosen", () => {
    render(wrap(<UploadPage />));
    const button = screen.getByRole("button", { name: /Start extraction/i });
    expect(button).toBeDisabled();
  });

  it("enables submit once a file is set", async () => {
    render(wrap(<UploadPage />));
    const file = new File(["x"], "contract.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const input = screen.getByTestId("file-input") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    const button = screen.getByRole("button", { name: /Start extraction/i });
    expect(button).not.toBeDisabled();
  });
});
