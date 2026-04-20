import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { CountryListPage } from "../src/features/countries/CountryListPage";

vi.mock("../src/lib/api", () => ({
  api: {
    listCountries: vi.fn().mockResolvedValue([
      {
        iso3: "USA", name: "UNITED STATES", region: "DEVELOPED",
        latest_final_score: 1.5, latest_bucket_band: null, latest_segment: "HIGH",
        latest_snapshot_id: "11111111-1111-1111-1111-111111111111",
        latest_as_of_date: "2022-12-31", latest_published_at: "2026-04-20T10:00:00Z",
      },
      {
        iso3: "ZAF", name: "SOUTH AFRICA", region: "AFRICA",
        latest_final_score: null, latest_bucket_band: null, latest_segment: null,
        latest_snapshot_id: null, latest_as_of_date: null, latest_published_at: null,
      },
    ]),
  },
}));

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>;
}

describe("CountryListPage", () => {
  it("renders the counts and both countries", async () => {
    render(wrap(<CountryListPage />));
    await waitFor(() => expect(screen.getByText(/1 scored \/ 2 total/i)).toBeInTheDocument());
    expect(screen.getByText(/united states/i)).toBeInTheDocument();
    expect(screen.getByText(/south africa/i)).toBeInTheDocument();
  });

  it("shows the score for scored countries and a dash for unscored", async () => {
    render(wrap(<CountryListPage />));
    await waitFor(() => expect(screen.getByText("1.500")).toBeInTheDocument());
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});
