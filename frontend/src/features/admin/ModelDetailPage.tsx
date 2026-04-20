import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";

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

export function ModelDetailPage() {
  const { id = "" } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState<string | null>(null);

  const modelQ = useQuery({
    queryKey: ["model-version", id],
    queryFn: () => api.getModel(id),
    enabled: !!id,
  });

  if (modelQ.isLoading) return <p className="text-sm text-slate-500">Loading model...</p>;
  if (modelQ.error) return <p role="alert" className="text-sm text-red-600">{(modelQ.error as Error).message}</p>;
  if (!modelQ.data) return null;

  const m = modelQ.data;

  async function runAction(action: () => Promise<unknown>, label: string) {
    setActionError(null);
    setActionPending(label);
    try {
      await action();
      await qc.invalidateQueries({ queryKey: ["model-version", id] });
      await qc.invalidateQueries({ queryKey: ["model-versions"] });
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setActionPending(null);
    }
  }

  const canApprove = m.status === "pending_review";
  const canActivate = m.status === "approved";
  const canRetire = m.status !== "retired";

  return (
    <div className="space-y-6">
      <div className="text-sm text-slate-500">
        <Link to="/admin/models" className="hover:underline">← Models</Link>
      </div>

      <header className="rounded-lg border border-slate-200 bg-white p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold text-slate-900">
              {m.segment} model <StatusBadge status={m.status} />
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              {m.training_notes || "No notes"} · trained {new Date(m.trained_at).toLocaleString()}
            </p>
            <p className="mt-1 font-mono text-xs text-slate-400">{m.id}</p>
          </div>
          <div className="grid grid-cols-3 gap-4 text-sm">
            <Metric label="R²" value={(m.fit_metrics_json["r2"] ?? 0).toFixed(3)} />
            <Metric label="RMSE" value={(m.fit_metrics_json["rmse"] ?? 0).toFixed(3)} />
            <Metric label="n rows" value={String(m.fit_metrics_json["n_training_rows"] ?? 0)} />
          </div>
        </div>
      </header>

      <section className="rounded-lg border border-slate-200 bg-white p-6">
        <h2 className="mb-3 text-base font-semibold text-slate-900">Validation against the prototype</h2>
        <p className="mb-3 text-sm text-slate-600">
          Download a per-country diagnostic of <strong>predicted vs target</strong> on the training data.
          Use this to compare against the original Excel prototype outputs before approving.
        </p>
        <div className="flex gap-3">
          <button
            onClick={() => api.downloadDiagnosticsCsv(m.id, m.segment)}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
          >
            Download CSV
          </button>
          <button
            onClick={() => api.downloadDiagnosticsXlsx(m.id, m.segment)}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
          >
            Download Excel
          </button>
        </div>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-6">
        <h2 className="mb-3 text-base font-semibold text-slate-900">Lifecycle actions</h2>
        {actionError && <p role="alert" className="mb-3 text-sm text-red-600">{actionError}</p>}
        <div className="flex flex-wrap gap-3">
          <button
            disabled={!canApprove || actionPending !== null}
            onClick={() => runAction(() => api.approveModel(m.id), "approve")}
            className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {actionPending === "approve" ? "Approving..." : "Approve"}
          </button>
          <button
            disabled={!canActivate || actionPending !== null}
            onClick={() => runAction(() => api.activateModel(m.id), "activate")}
            className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {actionPending === "activate" ? "Activating..." : "Activate"}
          </button>
          <button
            disabled={!canRetire || actionPending !== null}
            onClick={() => runAction(() => api.retireModel(m.id), "retire")}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50"
          >
            {actionPending === "retire" ? "Retiring..." : "Retire"}
          </button>
        </div>
        <p className="mt-3 text-xs text-slate-500">
          Activating this model auto-retires any other active model in segment <strong>{m.segment}</strong>.
          Snapshot compute will pick up the new active model on its next run.
        </p>
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-slate-200 px-3 py-2">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="font-mono text-sm text-slate-900">{value}</p>
    </div>
  );
}
