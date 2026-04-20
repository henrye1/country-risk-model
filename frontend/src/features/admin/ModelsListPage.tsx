import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type ModelVersion } from "../../lib/api";

const STATUS_STYLES: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-800",
  approved: "bg-blue-100 text-blue-800",
  pending_review: "bg-amber-100 text-amber-800",
  retired: "bg-slate-100 text-slate-500",
};

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLES[status] ?? "bg-slate-100 text-slate-700";
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${cls}`}>{status}</span>;
}

export function ModelsListPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["model-versions"],
    queryFn: api.listModels,
  });

  if (isLoading) return <p className="text-sm text-slate-500">Loading models...</p>;
  if (error) return <p role="alert" className="text-sm text-red-600">{(error as Error).message}</p>;

  const models = data ?? [];

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-900">Models <span className="text-sm font-normal text-slate-500">({models.length})</span></h1>
        <Link to="/admin/models/train" className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800">
          Train new model
        </Link>
      </div>
      <div className="overflow-x-auto rounded border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2">Segment</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Trained at</th>
              <th className="px-3 py-2">R²</th>
              <th className="px-3 py-2">RMSE</th>
              <th className="px-3 py-2">n</th>
              <th className="px-3 py-2">Notes</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {models.map((m: ModelVersion) => (
              <tr key={m.id} className="hover:bg-slate-50">
                <td className="px-3 py-2 font-mono text-xs">{m.segment}</td>
                <td className="px-3 py-2"><StatusBadge status={m.status} /></td>
                <td className="px-3 py-2 text-xs text-slate-500">{new Date(m.trained_at).toLocaleString()}</td>
                <td className="px-3 py-2 font-mono text-xs">{(m.fit_metrics_json["r2"] ?? 0).toFixed(3)}</td>
                <td className="px-3 py-2 font-mono text-xs">{(m.fit_metrics_json["rmse"] ?? 0).toFixed(3)}</td>
                <td className="px-3 py-2 font-mono text-xs">{m.fit_metrics_json["n_training_rows"] ?? 0}</td>
                <td className="px-3 py-2 text-xs text-slate-500">{m.training_notes ?? "—"}</td>
                <td className="px-3 py-2 text-right">
                  <Link to={`/admin/models/${m.id}`} className="text-xs text-slate-700 hover:underline">View</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
