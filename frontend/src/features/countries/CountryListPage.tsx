import { useQuery } from "@tanstack/react-query";
import { api, type Country } from "../../lib/api";

export function CountryListPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ["countries"], queryFn: api.listCountries });

  if (isLoading) return <p className="text-sm text-slate-500">Loading countries...</p>;
  if (error) return <p role="alert" className="text-sm text-red-600">{(error as Error).message}</p>;

  const countries = data ?? [];
  return (
    <section>
      <h1 className="mb-4 text-lg font-semibold text-slate-900">Countries ({countries.length})</h1>
      <ul className="divide-y divide-slate-200 rounded border border-slate-200 bg-white">
        {countries.map((c: Country) => (
          <li key={c.iso3} className="flex items-center justify-between px-4 py-2 text-sm">
            <span className="text-slate-900">{c.name}</span>
            <span className="text-xs text-slate-500">{c.iso3}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
