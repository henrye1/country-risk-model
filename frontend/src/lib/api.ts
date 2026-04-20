import { z } from "zod";
import { supabase } from "./supabase";

const API_BASE = import.meta.env.VITE_API_BASE_URL;

export class ApiError extends Error {
  public status: number;
  public details?: unknown;
  constructor(status: number, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

async function authHeader(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  return data.session ? { Authorization: `Bearer ${data.session.access_token}` } : {};
}

async function request<T>(path: string, schema: z.ZodType<T>, init?: RequestInit): Promise<T> {
  const headers = { "Content-Type": "application/json", ...(await authHeader()), ...(init?.headers ?? {}) };
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    let body: unknown = null;
    try { body = await res.json(); } catch { /* ignore */ }
    throw new ApiError(res.status, res.statusText, body);
  }
  const json = await res.json();
  return schema.parse(json);
}

// --- Shared primitives ---------------------------------------------------

export const IsoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);

// --- Reference types -----------------------------------------------------

export const Variable = z.object({
  code: z.string(),
  name: z.string(),
  category: z.string(),
  direction: z.string(),
  is_quantitative: z.boolean(),
  description: z.string().nullable().optional(),
});
export type Variable = z.infer<typeof Variable>;

// --- Country types -------------------------------------------------------

export const CountrySummary = z.object({
  iso3: z.string().length(3),
  name: z.string(),
  region: z.string().nullable().optional(),
  latest_final_score: z.number().nullable(),
  latest_bucket_band: z.string().nullable(),
  latest_segment: z.string().nullable(),
  latest_snapshot_id: z.string().uuid().nullable(),
  latest_as_of_date: IsoDate.nullable(),
  latest_published_at: z.string().nullable(),
});
export type CountrySummary = z.infer<typeof CountrySummary>;

export const CountryScore = z.object({
  iso3: z.string().length(3),
  name: z.string(),
  segment: z.string(),
  final_score: z.number(),
  quant_score: z.number(),
  qual_score: z.number(),
  bucket_band: z.string().nullable(),
  snapshot_id: z.string().uuid(),
  snapshot_name: z.string(),
  as_of_date: IsoDate,
  published_at: z.string(),
  model_version_high: z.string().uuid().nullable(),
  model_version_low: z.string().uuid().nullable(),
  model_version_nodata: z.string().uuid().nullable(),
});
export type CountryScore = z.infer<typeof CountryScore>;

export const DriverBreakdown = z.object({
  variable_code: z.string(),
  variable_name: z.string(),
  category: z.string(),
  direction: z.string(),
  is_quantitative: z.boolean(),
  raw_value: z.number().nullable(),
  standardised_value: z.number().nullable(),
  bucket_score: z.number().nullable(),
  contribution: z.number(),
});
export type DriverBreakdown = z.infer<typeof DriverBreakdown>;

export const HistoryPoint = z.object({
  snapshot_id: z.string().uuid(),
  snapshot_name: z.string(),
  as_of_date: IsoDate,
  published_at: z.string(),
  segment: z.string(),
  final_score: z.number(),
  quant_score: z.number(),
  qual_score: z.number(),
  bucket_band: z.string().nullable(),
});
export type HistoryPoint = z.infer<typeof HistoryPoint>;

export const PublishedSnapshot = z.object({
  id: z.string().uuid(),
  name: z.string(),
  as_of_date: IsoDate,
  status: z.string(),
  model_version_high: z.string().uuid().nullable(),
  model_version_low: z.string().uuid().nullable(),
  model_version_nodata: z.string().uuid().nullable(),
  published_at: z.string(),
  published_notes: z.string().nullable().optional(),
});
export type PublishedSnapshot = z.infer<typeof PublishedSnapshot>;

// --- API surface ---------------------------------------------------------

export const api = {
  listCountries: () => request("/v1/countries", z.array(CountrySummary)),
  listVariables: () => request("/v1/variables", z.array(Variable)),
  getCountry: (iso3: string) =>
    request(`/v1/countries/${iso3}`, CountrySummary),
  getCountryScore: (iso3: string, opts?: { as_of?: string; snapshot_id?: string }) => {
    const qs = new URLSearchParams();
    if (opts?.as_of) qs.set("as_of", opts.as_of);
    if (opts?.snapshot_id) qs.set("snapshot_id", opts.snapshot_id);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request(`/v1/countries/${iso3}/score${suffix}`, CountryScore);
  },
  getCountryDrivers: (iso3: string, snapshot_id: string) =>
    request(
      `/v1/countries/${iso3}/score/drivers?snapshot_id=${snapshot_id}`,
      z.array(DriverBreakdown),
    ),
  getCountryHistory: (iso3: string) =>
    request(`/v1/countries/${iso3}/history`, z.array(HistoryPoint)),
  listSnapshots: () => request("/v1/snapshots", z.array(PublishedSnapshot)),
};

// Re-export the old Country shape for any legacy consumer (in case a test references it).
export const Country = z.object({
  iso3: z.string().length(3),
  name: z.string(),
  region: z.string().nullable().optional(),
});
export type Country = z.infer<typeof Country>;
