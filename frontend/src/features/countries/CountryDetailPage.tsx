import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type DriverBreakdown, type HistoryPoint } from "../../lib/api";

export function CountryDetailPage() {
  const { iso3 = "" } = useParams<{ iso3: string }>();

  const summary = useQuery({
    queryKey: ["country", iso3],
    queryFn: () => api.getCountry(iso3),
    enabled: !!iso3,
  });

  const score = useQuery({
    queryKey: ["country-score", iso3],
    queryFn: () => api.getCountryScore(iso3),
    enabled: !!iso3,
    retry: false,
  });

  const drivers = useQuery({
    queryKey: ["country-drivers", iso3, score.data?.snapshot_id],
    queryFn: () => api.getCountryDrivers(iso3, score.data!.snapshot_id),
    enabled: !!score.data?.snapshot_id,
  });

  const history = useQuery({
    queryKey: ["country-history", iso3],
    queryFn: () => api.getCountryHistory(iso3),
    enabled: !!iso3,
  });

  if (summary.isLoading) return <p className="text-sm text-slate-500">Loading country...</p>;
  if (summary.error) return <p role="alert" className="text-sm text-red-600">{(summary.error as Error).message}</p>;
  if (!summary.data) return null;

  const c = summary.data;
  const scoreData = score.data;
  const noScore = score.isError || !scoreData;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <Link to="/countries" className="hover:underline">← Countries</Link>
      </div>

      <header className="rounded-lg border border-slate-200 bg-white p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">{c.name}</h1>
            <p className="mt-1 text-sm text-slate-500">
              {c.iso3} · {c.region ?? "—"}
              {scoreData && <> · Segment: <span className="font-mono">{scoreData.segment}</span></>}
            </p>
          </div>
          <div className="text-right">
            {noScore ? (
              <p className="text-sm text-slate-400">No published score</p>
            ) : (
              <>
                <p className="font-mono text-3xl font-semibold text-slate-900">
                  {scoreData!.final_score.toFixed(3)}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Snapshot: {scoreData!.snapshot_name} · as of {scoreData!.as_of_date}
                </p>
                <p className="text-xs text-slate-400">
                  Published {new Date(scoreData!.published_at).toLocaleDateString()}
                </p>
              </>
            )}
          </div>
        </div>
        {!noScore && (
          <div className="mt-4 flex gap-6 text-sm">
            <Metric label="Quant" value={scoreData!.quant_score.toFixed(3)} />
            <Metric label="Qual" value={scoreData!.qual_score.toFixed(3)} />
            {scoreData!.bucket_band && <Metric label="Band" value={scoreData!.bucket_band} />}
          </div>
        )}
      </header>

      <section className="rounded-lg border border-slate-200 bg-white p-6">
        <h2 className="mb-4 text-lg font-semibold text-slate-900">Driver breakdown</h2>
        {drivers.isLoading && <p className="text-sm text-slate-500">Loading drivers...</p>}
        {drivers.error && <p role="alert" className="text-sm text-red-600">{(drivers.error as Error).message}</p>}
        {drivers.data && <DriverChart drivers={drivers.data} />}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-6">
        <h2 className="mb-4 text-lg font-semibold text-slate-900">Score history</h2>
        {history.isLoading && <p className="text-sm text-slate-500">Loading history...</p>}
        {history.error && <p role="alert" className="text-sm text-red-600">{(history.error as Error).message}</p>}
        {history.data && history.data.length === 0 && (
          <p className="text-sm text-slate-500">No published history yet for this country.</p>
        )}
        {history.data && history.data.length > 0 && <HistoryChart history={history.data} />}
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="font-mono text-sm text-slate-900">{value}</p>
    </div>
  );
}

function DriverChart({ drivers }: { drivers: DriverBreakdown[] }) {
  const data = useMemo(
    () => drivers
      .slice()
      .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
      .map((d) => ({
        name: d.variable_name,
        contribution: d.contribution,
        category: d.category,
      })),
    [drivers],
  );
  return (
    <div className="h-80 w-full">
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ top: 5, right: 20, left: 120, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" />
          <YAxis type="category" dataKey="name" width={120} style={{ fontSize: "12px" }} />
          <Tooltip formatter={(v) => (typeof v === "number" ? v.toFixed(3) : v)} />
          <Bar dataKey="contribution" fill="#475569" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function HistoryChart({ history }: { history: HistoryPoint[] }) {
  const data = history.map((h) => ({
    date: h.as_of_date,
    final: h.final_score,
    quant: h.quant_score,
    qual: h.qual_score,
  }));
  return (
    <div className="h-80 w-full">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" style={{ fontSize: "12px" }} />
          <YAxis style={{ fontSize: "12px" }} />
          <Tooltip formatter={(v) => (typeof v === "number" ? v.toFixed(3) : v)} />
          <Line type="monotone" dataKey="final" stroke="#0f172a" strokeWidth={2} dot />
          <Line type="monotone" dataKey="quant" stroke="#64748b" strokeWidth={1} dot={false} />
          <Line type="monotone" dataKey="qual" stroke="#94a3b8" strokeWidth={1} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
