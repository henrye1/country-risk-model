import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CountryListPage } from "../src/features/countries/CountryListPage";

vi.mock("../src/lib/api", () => ({
  api: {
    listCountries: vi.fn().mockResolvedValue([
      { iso3: "USA", name: "UNITED STATES", region: "DEVELOPED" },
      { iso3: "ZAF", name: "SOUTH AFRICA", region: "AFRICA" },
    ]),
  },
}));

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;
}

describe("CountryListPage", () => {
  it("renders the count and each country row", async () => {
    render(wrap(<CountryListPage />));
    await waitFor(() => expect(screen.getByText(/countries \(2\)/i)).toBeInTheDocument());
    expect(screen.getByText(/united states/i)).toBeInTheDocument();
    expect(screen.getByText(/south africa/i)).toBeInTheDocument();
  });
});
