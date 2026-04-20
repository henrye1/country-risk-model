import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type Variable } from "../../lib/api";

const SEGMENTS = ["HIGH", "LOW"] as const;

const DEFAULT_QUANT = ["gdp_capita", "cof", "debt_service_ratio"];
const DEFAULT_QUAL = ["rol", "pr"];

export function TrainModelPage() {
  const navigate = useNavigate();
  const variablesQ = useQuery({ queryKey: ["variables"], queryFn: api.listVariables });
  const [segment, setSegment] = useState<typeof SEGMENTS[number]>("HIGH");
  const [quant, setQuant] = useState<string[]>(DEFAULT_QUANT);
  const [qual, setQual] = useState<string[]>(DEFAULT_QUAL);
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allVars = variablesQ.data ?? [];
  const quantOpts = allVars.filter((v) => v.is_quantitative);
  const qualOpts = allVars.filter((v) => !v.is_quantitative);

  function toggle(set: string[], code: string, setter: (v: string[]) => void) {
    setter(set.includes(code) ? set.filter((c) => c !== code) : [...set, code]);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.trainModel({
        segment,
        quant_codes: quant,
        qual_codes: qual,
        notes: notes || undefined,
      });
      navigate(`/admin/models/${result.model_version_id}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="max-w-3xl space-y-6">
      <h1 className="text-lg font-semibold text-slate-900">Train new model</h1>
      <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
        Training uses the existing <code>supabase/seeds/training_*.csv</code> files (2011 EIU snapshot).
        Updating those targets requires a separate ingestion workflow — coming later. For now, retraining
        without changing inputs only updates <em>which variables</em> the model uses.
      </p>

      <form onSubmit={onSubmit} className="space-y-5 rounded-lg border border-slate-200 bg-white p-6">
        <label className="block text-sm">
          <span className="text-slate-700">Segment</span>
          <select
            value={segment}
            onChange={(e) => setSegment(e.target.value as typeof SEGMENTS[number])}
            className="mt-1 block w-full max-w-xs rounded border border-slate-300 px-2 py-1.5 text-sm"
          >
            {SEGMENTS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>

        <fieldset>
          <legend className="text-sm font-medium text-slate-700">Quantitative variables ({quant.length})</legend>
          <div className="mt-2 grid grid-cols-2 gap-2 rounded border border-slate-200 p-3 text-xs">
            {quantOpts.map((v: Variable) => (
              <label key={v.code} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={quant.includes(v.code)}
                  onChange={() => toggle(quant, v.code, setQuant)}
                />
                <span><code className="text-xs">{v.code}</code> — {v.name}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend className="text-sm font-medium text-slate-700">Qualitative variables ({qual.length})</legend>
          <div className="mt-2 grid grid-cols-2 gap-2 rounded border border-slate-200 p-3 text-xs">
            {qualOpts.map((v: Variable) => (
              <label key={v.code} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={qual.includes(v.code)}
                  onChange={() => toggle(qual, v.code, setQual)}
                />
                <span><code className="text-xs">{v.code}</code> — {v.name}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <label className="block text-sm">
          <span className="text-slate-700">Notes (optional)</span>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="What's different about this run?"
            className="mt-1 block w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
            rows={2}
          />
        </label>

        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={submitting || quant.length === 0 || qual.length === 0}
            className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {submitting ? "Training..." : "Train (5-10 sec)"}
          </button>
          <span className="text-xs text-slate-500">Will be created in <code>pending_review</code> status.</span>
        </div>
      </form>
    </section>
  );
}
