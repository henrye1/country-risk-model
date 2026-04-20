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

// --- Peer analysis ---

export const PeerStat = z.object({
  variable_code: z.string(),
  variable_name: z.string(),
  country_value: z.number().nullable(),
  n_peers: z.number(),
  peer_min: z.number(),
  peer_max: z.number(),
  peer_mean: z.number(),
  peer_std: z.number(),
  peer_p10: z.number(),
  peer_p25: z.number(),
  peer_median: z.number(),
  peer_p75: z.number(),
  peer_p90: z.number(),
  country_percentile: z.number().nullable(),
});
export type PeerStat = z.infer<typeof PeerStat>;

export const PeerAnalysis = z.object({
  iso3: z.string(),
  name: z.string(),
  segment: z.string(),
  snapshot_id: z.string().uuid().nullable(),
  rows: z.array(PeerStat),
});
export type PeerAnalysis = z.infer<typeof PeerAnalysis>;

// --- Model versions (admin) ---

export const ModelVersion = z.object({
  id: z.string().uuid(),
  segment: z.string(),
  status: z.string(),
  trained_at: z.string(),
  training_notes: z.string().nullable(),
  training_data_hash: z.string(),
  fit_metrics_json: z.record(z.string(), z.number()).default({}),
});
export type ModelVersion = z.infer<typeof ModelVersion>;

export const TrainResult = z.object({
  model_version_id: z.string().uuid(),
  segment: z.string(),
  fit_metrics: z.record(z.string(), z.number()),
  n_training_rows: z.number(),
});
export type TrainResult = z.infer<typeof TrainResult>;

async function downloadBinary(path: string, filename: string): Promise<void> {
  const { data } = await supabase.auth.getSession();
  const headers: Record<string, string> = data.session
    ? { Authorization: `Bearer ${data.session.access_token}` }
    : {};
  const res = await fetch(`${API_BASE}${path}`, { headers });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

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
  getCountryPeerAnalysis: (iso3: string) =>
    request(`/v1/countries/${iso3}/peer-analysis`, PeerAnalysis),
  listSnapshots: () => request("/v1/snapshots", z.array(PublishedSnapshot)),

  // Model lifecycle
  listModels: () => request("/admin/model-versions", z.array(ModelVersion)),
  getModel: (id: string) => request(`/admin/model-versions/${id}`, ModelVersion),
  trainModel: (body: { segment: string; quant_codes: string[]; qual_codes: string[]; notes?: string }) =>
    request("/admin/model-versions", TrainResult, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  approveModel: (id: string) =>
    request(`/admin/model-versions/${id}/approve`, ModelVersion, { method: "POST" }),
  activateModel: (id: string) =>
    request(`/admin/model-versions/${id}/activate`, ModelVersion, { method: "POST" }),
  retireModel: (id: string) =>
    request(`/admin/model-versions/${id}/retire`, ModelVersion, { method: "POST" }),
  downloadDiagnosticsCsv: (id: string, segment: string) =>
    downloadBinary(`/admin/model-versions/${id}/diagnostics.csv`, `diagnostics_${segment}_${id}.csv`),
  downloadDiagnosticsXlsx: (id: string, segment: string) =>
    downloadBinary(`/admin/model-versions/${id}/diagnostics.xlsx`, `diagnostics_${segment}_${id}.xlsx`),
};

// Re-export the old Country shape for any legacy consumer (in case a test references it).
export const Country = z.object({
  iso3: z.string().length(3),
  name: z.string(),
  region: z.string().nullable().optional(),
});
export type Country = z.infer<typeof Country>;
