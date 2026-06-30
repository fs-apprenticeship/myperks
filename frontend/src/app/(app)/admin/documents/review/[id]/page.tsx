"use client";

import {
  ArrowLeft,
  CheckCircle,
  FileText,
  Loader2,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import type {
  ApproveExtractionResponse,
  DocumentExtractionResponse,
  ExtractionData,
} from "@/lib/api.client";

import { useApi } from "@/lib/api.client";

const CURRENT_YEAR = new Date().getFullYear();

type Field = {
  key: keyof ExtractionData;
  label: string;
  unit: string;
};

const FIELDS: Field[] = [
  { key: "vacation_days", label: "Annual Vacation Days", unit: "days" },
  { key: "sick_days", label: "Annual Sick Leave Days", unit: "days" },
  { key: "pto_days", label: "Annual PTO Days", unit: "days" },
];

export default function DocumentReviewPage() {
  const { id } = useParams<{ id: string }>();
  const documentId = Number(id);
  const api = useApi();

  const [extraction, setExtraction] =
    useState<DocumentExtractionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<null | string>(null);
  const [success, setSuccess] = useState<ApproveExtractionResponse | null>(
    null,
  );

  // Form state — populated from extracted data
  const [form, setForm] = useState({
    carryover_cap_days: "" as number | string,
    notes: "",
    proration_method: "monthly" as "monthly" | "none",
    pto_days: "" as number | string,
    sick_days: "" as number | string,
    vacation_days: "" as number | string,
    year: CURRENT_YEAR,
  });

  const loadExtraction = useCallback(async () => {
    try {
      const data = await api.getDocumentExtraction(documentId);
      setExtraction(data);
      // Prefer approved_data (HR's final values) over extracted_data (raw AI output)
      const source = data?.approved_data ?? data?.extracted_data;
      if (source) {
        setForm((prev) => ({
          ...prev,
          carryover_cap_days: source.carryover_cap_days ?? "",
          notes: source.notes ?? "",
          proration_method: source.proration_method ?? "monthly",
          pto_days: source.pto_days ?? "",
          sick_days: source.sick_days ?? "",
          vacation_days: source.vacation_days ?? "",
        }));
      }
    } catch (err) {
      // The backend returns a null body (not an error) when no extraction
      // exists yet, so reaching here means a real failure (network, auth, a
      // missing document) — surface it instead of treating it as "no data".
      setError(
        err instanceof Error ? err.message : "Failed to load extraction.",
      );
    } finally {
      setLoading(false);
    }
  }, [api, documentId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadExtraction();
  }, [loadExtraction]);

  async function handleExtract() {
    setExtracting(true);
    setError(null);
    try {
      const data = await api.triggerExtraction(documentId);
      setExtraction(data);
      if (data.extracted_data) {
        const d = data.extracted_data;
        setForm((prev) => ({
          ...prev,
          carryover_cap_days: d.carryover_cap_days ?? "",
          notes: d.notes ?? "",
          proration_method: d.proration_method ?? "monthly",
          pto_days: d.pto_days ?? "",
          sick_days: d.sick_days ?? "",
          vacation_days: d.vacation_days ?? "",
        }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Extraction failed.");
    } finally {
      setExtracting(false);
    }
  }

  async function handleApprove(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await api.approveExtraction(documentId, {
        carryover_cap_days:
          form.carryover_cap_days !== ""
            ? Number(form.carryover_cap_days)
            : null,
        notes: form.notes,
        proration_method: form.proration_method,
        pto_days: form.pto_days !== "" ? Number(form.pto_days) : null,
        sick_days: form.sick_days !== "" ? Number(form.sick_days) : null,
        vacation_days:
          form.vacation_days !== "" ? Number(form.vacation_days) : null,
        year: form.year,
      });
      setSuccess(result);
      void loadExtraction();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Approval failed.");
    } finally {
      setSubmitting(false);
    }
  }

  const canExtract = !extracting && extraction?.status !== "extracting";
  const canApprove =
    extraction?.status === "extracted" || extraction?.status === "approved";

  const missingFields = FIELDS.filter(
    ({ key }) =>
      form[key] === "" || form[key] === null || form[key] === undefined,
  ).map(({ label }) => label);
  const canSubmit = canApprove && missingFields.length === 0 && !submitting;

  if (loading) {
    return (
      <div className="flex h-48 items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-2xl space-y-8 p-6">
        {/* Header */}
        <div>
          <Link
            className="mb-4 flex items-center gap-1.5 text-[12px] text-muted-foreground hover:text-foreground"
            href="/admin/documents"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to Documents
          </Link>
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="text-lg font-semibold text-foreground">
                Document Policy Review
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Extract HR policy data from this document, review and edit the
                values, then apply them to the department.
              </p>
            </div>
            {extraction && <StatusBadge status={extraction.status} />}
          </div>
        </div>

        {/* Document info */}
        <section className="flex items-center gap-3 rounded-xl border border-border bg-muted/30 p-4">
          <FileText className="h-5 w-5 shrink-0 text-brand-purple-600 dark:text-brand-purple-400" />
          <div>
            <p className="text-[13px] font-medium text-foreground">
              Document #{documentId}
            </p>
            <p className="text-[11px] text-muted-foreground">
              Click &quot;Extract Policy&quot; to analyse this document with AI.
            </p>
          </div>
        </section>

        {/* Extract button */}
        <section>
          <div className="flex items-center justify-between">
            <h2 className="text-[13px] font-semibold text-foreground">
              Step 1 — Extract Policy Data
            </h2>
            <button
              className="flex items-center gap-1.5 rounded-lg bg-brand-purple-600 px-3 py-1.5 text-[12px] font-medium text-white hover:bg-brand-purple-700 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={!canExtract}
              onClick={() => void handleExtract()}
            >
              {extracting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              {extraction ? "Re-extract" : "Extract Policy"}
            </button>
          </div>

          {extraction?.status === "failed" && (
            <p className="mt-2 rounded-lg border border-red-200 bg-red-50 p-3 text-[12px] text-red-600 dark:border-red-900 dark:bg-red-900/20 dark:text-red-400">
              Extraction failed: {extraction.error_message ?? "Unknown error"}
            </p>
          )}

          {extraction?.status === "extracting" && (
            <p className="mt-2 text-[12px] text-muted-foreground">
              Analysing document with AI…
            </p>
          )}
        </section>

        {/* Review form */}
        {canApprove && (
          <form className="space-y-6" onSubmit={(e) => void handleApprove(e)}>
            <div>
              <h2 className="mb-4 text-[13px] font-semibold text-foreground">
                Step 2 — Review &amp; Edit Extracted Values
              </h2>

              <div className="space-y-4">
                {FIELDS.map(({ key, label, unit }) => (
                  <div key={key}>
                    <label className="mb-1.5 block text-[12px] font-medium text-foreground">
                      {label}
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        className={`w-32 rounded-lg border bg-background px-3 py-1.5 text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-brand-purple-500 ${
                          form[key] === "" || form[key] === null
                            ? "border-amber-400 dark:border-amber-600"
                            : "border-border"
                        }`}
                        max="365"
                        min="0"
                        onChange={(e) =>
                          setForm((prev) => ({
                            ...prev,
                            [key]: e.target.value,
                          }))
                        }
                        placeholder="—"
                        step="0.5"
                        type="number"
                        value={form[key] as number | string}
                      />
                      <span className="text-[12px] text-muted-foreground">
                        {unit}
                      </span>
                    </div>
                  </div>
                ))}

                <div>
                  <label className="mb-1.5 block text-[12px] font-medium text-foreground">
                    Vacation Carryover Cap
                  </label>
                  <div className="flex items-center gap-2">
                    <input
                      className="w-32 rounded-lg border border-border bg-background px-3 py-1.5 text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-brand-purple-500"
                      max="365"
                      min="0"
                      onChange={(e) =>
                        setForm((prev) => ({
                          ...prev,
                          carryover_cap_days: e.target.value,
                        }))
                      }
                      placeholder="Uncapped"
                      step="0.5"
                      type="number"
                      value={form.carryover_cap_days}
                    />
                    <span className="text-[12px] text-muted-foreground">
                      days (blank = uncapped, 0 = no carryover)
                    </span>
                  </div>
                </div>

                <div>
                  <label className="mb-1.5 block text-[12px] font-medium text-foreground">
                    New-Hire Proration
                  </label>
                  <select
                    className="w-48 rounded-lg border border-border bg-background px-3 py-1.5 text-[13px] text-foreground focus:outline-none focus:ring-2 focus:ring-brand-purple-500"
                    onChange={(e) =>
                      setForm((prev) => ({
                        ...prev,
                        proration_method: e.target.value as "monthly" | "none",
                      }))
                    }
                    value={form.proration_method}
                  >
                    <option value="monthly">Monthly (by months worked)</option>
                    <option value="none">None (full allotment)</option>
                  </select>
                </div>

                <div>
                  <label className="mb-1.5 block text-[12px] font-medium text-foreground">
                    Additional Notes
                  </label>
                  <textarea
                    className="w-full rounded-lg border border-border bg-background px-3 py-2 text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-brand-purple-500"
                    onChange={(e) =>
                      setForm((prev) => ({ ...prev, notes: e.target.value }))
                    }
                    placeholder="Any other HR policy details from the document…"
                    rows={3}
                    value={form.notes}
                  />
                </div>

                <div>
                  <label className="mb-1.5 block text-[12px] font-medium text-foreground">
                    Apply for Year
                  </label>
                  <input
                    className="w-32 rounded-lg border border-border bg-background px-3 py-1.5 text-[13px] text-foreground focus:outline-none focus:ring-2 focus:ring-brand-purple-500"
                    max={CURRENT_YEAR + 1}
                    min={CURRENT_YEAR}
                    onChange={(e) =>
                      setForm((prev) => ({
                        ...prev,
                        year: Number(e.target.value),
                      }))
                    }
                    type="number"
                    value={form.year}
                  />
                </div>
              </div>
            </div>

            {missingFields.length > 0 && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-900 dark:bg-amber-900/20">
                <p className="text-[12px] font-medium text-amber-700 dark:text-amber-300">
                  Fill in the following before approving:
                </p>
                <ul className="mt-1 list-inside list-disc space-y-0.5">
                  {missingFields.map((f) => (
                    <li
                      className="text-[12px] text-amber-600 dark:text-amber-400"
                      key={f}
                    >
                      {f}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {error && (
              <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-[12px] text-red-600 dark:border-red-900 dark:bg-red-900/20 dark:text-red-400">
                {error}
              </p>
            )}

            {success && (
              <div className="flex items-start gap-2 rounded-lg border border-green-200 bg-green-50 p-3 dark:border-green-900 dark:bg-green-900/20">
                <CheckCircle className="mt-0.5 h-4 w-4 shrink-0 text-green-600 dark:text-green-400" />
                <p className="text-[12px] text-green-700 dark:text-green-300">
                  Policy applied to{" "}
                  <strong>{success.employees_updated} employee(s)</strong> in
                  the <strong>{success.department}</strong> department for{" "}
                  <strong>{success.year}</strong>.
                </p>
              </div>
            )}

            {success?.warning && (
              <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-[12px] text-amber-700 dark:border-amber-900 dark:bg-amber-900/20 dark:text-amber-400">
                {success.warning}
              </p>
            )}

            <button
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-brand-purple-600 py-2.5 text-[13px] font-semibold text-white hover:bg-brand-purple-700 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={!canSubmit}
              type="submit"
            >
              {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
              Approve &amp; Apply to Department
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    approved:
      "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
    extracted:
      "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
    extracting:
      "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300",
    failed: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
    pending: "bg-muted text-muted-foreground",
  };
  const labels: Record<string, string> = {
    approved: "Approved",
    extracted: "Ready to Review",
    extracting: "Extracting…",
    failed: "Extraction Failed",
    pending: "Not Extracted",
  };
  return (
    <span
      className={`rounded-full px-2.5 py-0.5 text-[12px] font-medium ${styles[status] ?? styles.pending}`}
    >
      {labels[status] ?? status}
    </span>
  );
}
