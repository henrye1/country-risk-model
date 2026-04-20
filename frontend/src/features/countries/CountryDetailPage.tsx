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
import { api, type DriverBreakdown, type HistoryPoint, type PeerStat } from "../../lib/api";

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

  const peers = useQuery({
    queryKey: ["country-peers", iso3],
    queryFn: () => api.getCountryPeerAnalysis(iso3),
    enabled: !!iso3,
    retry: false,
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

      <section className="rounded-lg border border-slate-200 bg-white p-6">
        <h2 className="mb-1 text-lg font-semibold text-slate-900">Peer comparison</h2>
        <p className="mb-4 text-xs text-slate-500">
          Compares this country's drivers and predicted score against the training cohort
          for its segment. The peer set is the {scoreData?.segment ?? "—"}-segment training portfolio.
        </p>
        {peers.isLoading && <p className="text-sm text-slate-500">Loading peer comparison...</p>}
        {peers.error && <p role="alert" className="text-sm text-red-600">{(peers.error as Error).message}</p>}
        {peers.data && <PeerTable rows={peers.data.rows} />}
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


function fmt(n: number | null | undefined, digits = 3): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}


function DistributionBar({ row }: { row: PeerStat }) {
  // Range from peer_min to peer_max. Marker positions in % from left.
  const range = row.peer_max - row.peer_min;
  if (range <= 0) {
    return <div className="text-xs text-slate-400">—</div>;
  }
  const pos = (v: number) => Math.max(0, Math.min(100, ((v - row.peer_min) / range) * 100));
  const country_pct = row.country_value !== null ? pos(row.country_value) : null;
  const p25 = pos(row.peer_p25);
  const p50 = pos(row.peer_median);
  const p75 = pos(row.peer_p75);

  return (
    <div className="relative h-4 w-full">
      {/* Background range bar */}
      <div className="absolute inset-y-1.5 left-0 right-0 h-1 rounded bg-slate-200" />
      {/* Inter-quartile shaded box (p25 to p75) */}
      <div
        className="absolute inset-y-1 h-2 rounded bg-slate-300"
        style={{ left: `${p25}%`, width: `${p75 - p25}%` }}
      />
      {/* Median tick */}
      <div
        className="absolute inset-y-0 h-4 w-px bg-slate-500"
        style={{ left: `${p50}%` }}
        title={`median ${fmt(row.peer_median)}`}
      />
      {/* Country marker (filled circle) */}
      {country_pct !== null && (
        <div
          className="absolute -top-0.5 h-5 w-5 -translate-x-1/2 rounded-full border-2 border-white bg-emerald-600 shadow"
          style={{ left: `${country_pct}%` }}
          title={`this country: ${fmt(row.country_value)}`}
        />
      )}
    </div>
  );
}


function PeerTable({ rows }: { rows: PeerStat[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="pb-2 pr-3">Variable</th>
            <th className="pb-2 pr-3 text-right">Your value</th>
            <th className="pb-2 pr-3 text-right">Peer mean ± std</th>
            <th className="pb-2 pr-3 text-right">Range</th>
            <th className="pb-2 pr-3 text-right">Percentile</th>
            <th className="pb-2 pl-3" style={{ minWidth: "180px" }}>Distribution</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r) => {
            const isPredicted = r.variable_code === "_PREDICTED_SCORE";
            return (
              <tr key={r.variable_code} className={isPredicted ? "bg-slate-50 font-medium" : ""}>
                <td className="py-2 pr-3">
                  {isPredicted ? "Predicted score (vs training EIU)" : r.variable_name}
                  {!isPredicted && <span className="ml-1 font-mono text-xs text-slate-400">{r.variable_code}</span>}
                </td>
                <td className="py-2 pr-3 text-right font-mono text-xs">{fmt(r.country_value)}</td>
                <td className="py-2 pr-3 text-right font-mono text-xs text-slate-600">
                  {fmt(r.peer_mean)} ± {fmt(r.peer_std)}
                </td>
                <td className="py-2 pr-3 text-right font-mono text-xs text-slate-500">
                  [{fmt(r.peer_min)}, {fmt(r.peer_max)}]
                </td>
                <td className="py-2 pr-3 text-right font-mono text-xs">
                  {r.country_percentile === null ? "—" : `${r.country_percentile.toFixed(0)}th`}
                </td>
                <td className="py-2 pl-3"><DistributionBar row={r} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-slate-400">
        Distribution: shaded box = inter-quartile range (p25–p75) · vertical tick = median ·
        green dot = this country · n_peers = {rows[0]?.n_peers ?? 0}
      </p>
    </div>
  );
}
