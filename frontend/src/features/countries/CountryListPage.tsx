import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type CountrySummary } from "../../lib/api";

type SortKey = "name" | "score";

export function CountryListPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ["countries"], queryFn: api.listCountries });
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [query, setQuery] = useState("");

  if (isLoading) return <p className="text-sm text-slate-500">Loading countries...</p>;
  if (error) return <p role="alert" className="text-sm text-red-600">{(error as Error).message}</p>;

  const countries = data ?? [];
  const filtered = countries.filter((c) =>
    !query.trim() || c.name.toLowerCase().includes(query.toLowerCase()) || c.iso3.toLowerCase().includes(query.toLowerCase())
  );
  const sorted = [...filtered].sort((a, b) => {
    if (sortKey === "name") return a.name.localeCompare(b.name);
    // score: nulls last; higher scores first
    const av = a.latest_final_score;
    const bv = b.latest_final_score;
    if (av === null && bv === null) return a.name.localeCompare(b.name);
    if (av === null) return 1;
    if (bv === null) return -1;
    return bv - av;
  });

  const scoredCount = countries.filter((c) => c.latest_final_score !== null).length;

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-900">
          Countries <span className="text-sm font-normal text-slate-500">({scoredCount} scored / {countries.length} total)</span>
        </h1>
        <div className="flex items-center gap-3">
          <input
            type="search"
            placeholder="Filter by name or ISO3"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <label className="text-xs text-slate-600">
            Sort:&nbsp;
            <select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
              className="rounded border border-slate-300 px-2 py-0.5 text-xs"
            >
              <option value="name">Name</option>
              <option value="score">Latest score</option>
            </select>
          </label>
        </div>
      </div>
      <ul className="divide-y divide-slate-200 rounded border border-slate-200 bg-white">
        {sorted.map((c: CountrySummary) => (
          <li key={c.iso3} className="flex items-center justify-between px-4 py-2 text-sm hover:bg-slate-50">
            <Link to={`/countries/${c.iso3}`} className="flex-1 text-slate-900 hover:underline">
              {c.name}
            </Link>
            <span className="mr-4 text-xs text-slate-500">{c.iso3}</span>
            <span className="w-32 text-right font-mono text-sm text-slate-800">
              {c.latest_final_score !== null ? c.latest_final_score.toFixed(3) : <span className="text-slate-300">—</span>}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
