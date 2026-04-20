"""Persist / load TrainedModel via Supabase. Uses service_client (bypasses RLS).
Only called from the internal admin path."""
from __future__ import annotations
from uuid import UUID

from supabase import Client

from app.domain.types import (
    Bucket,
    ModelCoefficient,
    StandardisationParam,
    TrainedModel,
)

# Special variable_code values used to encode the second-stage blending Ridge
# (intercept + weights for combining quant_score and qual_score). These rows live
# in model_coefficients alongside the regular qual-Ridge coefs but are deserialised
# into TrainedModel.final_intercept / final_w_quant / final_w_qual.
_BLEND_INTERCEPT_CODE = "_FINAL_INTERCEPT"
_BLEND_W_QUANT_CODE = "_FINAL_W_QUANT"
_BLEND_W_QUAL_CODE = "_FINAL_W_QUAL"
_BLEND_CODES = {_BLEND_INTERCEPT_CODE, _BLEND_W_QUANT_CODE, _BLEND_W_QUAL_CODE}


class ModelVersionRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    def save(self, trained: TrainedModel, training_notes: str | None = None) -> UUID:
        """Insert a new model_versions row + its coefficients/standardisation/buckets.
        Returns the new model_version_id."""
        inserted = self._client.table("model_versions").insert({
            "segment": trained.segment,
            "training_notes": training_notes,
            "training_data_hash": trained.training_data_hash,
            "fit_metrics_json": trained.fit_metrics,
            "status": "pending_review",
        }).execute()
        version_id = inserted.data[0]["id"]

        coef_rows = [
            {
                "model_version_id": version_id,
                "variable_code": c.variable_code,
                "coefficient": c.coefficient,
                "is_intercept": c.is_intercept,
            }
            for c in trained.coefficients
        ]
        # Append blending rows (second-stage Ridge) when present.
        if trained.final_intercept is not None:
            coef_rows.append({
                "model_version_id": version_id,
                "variable_code": _BLEND_INTERCEPT_CODE,
                "coefficient": trained.final_intercept,
                "is_intercept": False,
            })
        if trained.final_w_quant is not None:
            coef_rows.append({
                "model_version_id": version_id,
                "variable_code": _BLEND_W_QUANT_CODE,
                "coefficient": trained.final_w_quant,
                "is_intercept": False,
            })
        if trained.final_w_qual is not None:
            coef_rows.append({
                "model_version_id": version_id,
                "variable_code": _BLEND_W_QUAL_CODE,
                "coefficient": trained.final_w_qual,
                "is_intercept": False,
            })
        if coef_rows:
            self._client.table("model_coefficients").insert(coef_rows).execute()

        std_rows = [
            {
                "model_version_id": version_id,
                "variable_code": p.variable_code,
                "mean": p.mean,
                "std": p.std,
            }
            for p in trained.standardisation
        ]
        if std_rows:
            self._client.table("model_standardisation").insert(std_rows).execute()

        bucket_rows = [
            {
                "model_version_id": version_id,
                "variable_code": b.variable_code,
                "bucket_order": b.bucket_order,
                "lower_bound": b.lower_bound,
                "upper_bound": b.upper_bound,
                "score": b.score,
            }
            for b in trained.buckets
        ]
        if bucket_rows:
            self._client.table("model_buckets").insert(bucket_rows).execute()

        return UUID(version_id)

    def load(self, model_version_id: UUID) -> TrainedModel:
        mv = self._client.table("model_versions").select("*").eq("id", str(model_version_id)).single().execute()
        mv_row = mv.data

        coefs = self._client.table("model_coefficients").select("*").eq("model_version_id", str(model_version_id)).execute().data
        stds = self._client.table("model_standardisation").select("*").eq("model_version_id", str(model_version_id)).execute().data
        bkts = self._client.table("model_buckets").select("*").eq("model_version_id", str(model_version_id)).order("variable_code").order("bucket_order").execute().data

        # Split out the blending coefs from the regular qual-Ridge coefficients.
        regular_coefs: list[ModelCoefficient] = []
        final_intercept = final_w_quant = final_w_qual = None
        for c in coefs:
            code = c["variable_code"]
            if code == _BLEND_INTERCEPT_CODE:
                final_intercept = float(c["coefficient"])
            elif code == _BLEND_W_QUANT_CODE:
                final_w_quant = float(c["coefficient"])
            elif code == _BLEND_W_QUAL_CODE:
                final_w_qual = float(c["coefficient"])
            else:
                regular_coefs.append(ModelCoefficient(
                    variable_code=code,
                    coefficient=float(c["coefficient"]),
                    is_intercept=c["is_intercept"],
                ))

        qual_codes = tuple(c.variable_code for c in regular_coefs if not c.is_intercept and c.variable_code is not None)
        quant_codes = tuple(sorted({s["variable_code"] for s in stds}))

        return TrainedModel(
            segment=mv_row["segment"],
            coefficients=tuple(regular_coefs),
            standardisation=tuple(
                StandardisationParam(
                    variable_code=s["variable_code"],
                    mean=float(s["mean"]),
                    std=float(s["std"]),
                )
                for s in stds
            ),
            buckets=tuple(
                Bucket(
                    variable_code=b["variable_code"],
                    bucket_order=b["bucket_order"],
                    lower_bound=float(b["lower_bound"]) if b["lower_bound"] is not None else None,
                    upper_bound=float(b["upper_bound"]) if b["upper_bound"] is not None else None,
                    score=float(b["score"]),
                )
                for b in bkts
            ),
            quant_variable_codes=quant_codes,
            qual_variable_codes=qual_codes,
            training_data_hash=mv_row["training_data_hash"],
            fit_metrics=mv_row.get("fit_metrics_json") or {},
            final_intercept=final_intercept,
            final_w_quant=final_w_quant,
            final_w_qual=final_w_qual,
        )
