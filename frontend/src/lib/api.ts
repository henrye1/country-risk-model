import { z } from "zod";
import { supabase } from "./supabase";

const API_BASE = import.meta.env.VITE_API_BASE_URL;

export class ApiError extends Error {
  status: number;
  details?: unknown;
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

export const Country = z.object({
  iso3: z.string().length(3),
  name: z.string(),
  region: z.string().nullable().optional(),
});
export type Country = z.infer<typeof Country>;

export const Variable = z.object({
  code: z.string(),
  name: z.string(),
  category: z.string(),
  direction: z.string(),
  is_quantitative: z.boolean(),
  description: z.string().nullable().optional(),
});
export type Variable = z.infer<typeof Variable>;

export const api = {
  listCountries: () => request("/v1/countries", z.array(Country)),
  listVariables: () => request("/v1/variables", z.array(Variable)),
};
