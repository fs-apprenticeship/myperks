"use client";

import { Loader2, Plus, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { type PreCreateEmployeeBody, useApi } from "@/lib/api.client";

const DEPARTMENTS = [
  "engineering",
  "sales",
  "marketing",
  "hr",
  "finance",
  "operations",
  "other",
] as const;

export function PreCreateEmployeeDialog() {
  const api = useApi();
  const router = useRouter();
  const dialogRef = useRef<HTMLDialogElement>(null);

  const [form, setForm] = useState<PreCreateEmployeeBody>({
    benefits_year_reset: `${new Date().getFullYear() + 1}-01-01`,
    department: "engineering",
    email: "",
    joined_date: new Date().toISOString().slice(0, 10),
    name: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<null | string>(null);

  function open() {
    setError(null);
    dialogRef.current?.showModal();
  }

  function close() {
    dialogRef.current?.close();
  }

  function set(field: keyof PreCreateEmployeeBody, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit() {
    if (!form.name.trim() || !form.email.trim()) {
      setError("Name and email are required.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await api.preCreateEmployee(form);
      close();
      router.refresh();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Something went wrong.";
      const detail = msg.match(/^API error: \d+ – (.+)$/)?.[1];
      setError(detail ?? msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <button
        className="inline-flex items-center gap-1.5 rounded-lg bg-brand-purple-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-brand-purple-700"
        onClick={open}
        type="button"
      >
        <Plus className="h-3.5 w-3.5" />
        Add employee
      </button>

      <dialog
        className="m-auto w-full max-w-md rounded-xl border border-border bg-white p-6 shadow-xl backdrop:bg-black/40 dark:bg-card"
        ref={dialogRef}
      >
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-[15px] font-semibold">Add employee</h2>
          <button
            className="rounded p-1 text-muted-foreground hover:text-foreground"
            onClick={close}
            type="button"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3">
          <Field label="Full name">
            <input
              className={inputCls}
              onChange={(e) => set("name", e.target.value)}
              placeholder="Jane Smith"
              type="text"
              value={form.name}
            />
          </Field>

          <Field label="Email">
            <input
              className={inputCls}
              onChange={(e) => set("email", e.target.value)}
              placeholder="jane@company.com"
              type="email"
              value={form.email}
            />
          </Field>

          <Field label="Department">
            <select
              className={inputCls}
              onChange={(e) => set("department", e.target.value)}
              value={form.department}
            >
              {DEPARTMENTS.map((d) => (
                <option key={d} value={d}>
                  {d.charAt(0).toUpperCase() + d.slice(1)}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Join date">
            <input
              className={inputCls}
              onChange={(e) => set("joined_date", e.target.value)}
              type="date"
              value={form.joined_date}
            />
          </Field>

          <Field label="Benefits year reset">
            <input
              className={inputCls}
              onChange={(e) => set("benefits_year_reset", e.target.value)}
              type="date"
              value={form.benefits_year_reset}
            />
          </Field>
        </div>

        {error && <p className="mt-3 text-[12px] text-destructive">{error}</p>}

        <div className="mt-5 flex justify-end gap-2">
          <button
            className="rounded-lg border border-border px-3 py-1.5 text-[12px] font-medium hover:bg-muted"
            onClick={close}
            type="button"
          >
            Cancel
          </button>
          <button
            className="inline-flex items-center gap-1.5 rounded-lg bg-brand-purple-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-brand-purple-700 disabled:opacity-50"
            disabled={loading}
            onClick={() => void handleSubmit()}
            type="button"
          >
            {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Create employee
          </button>
        </div>
      </dialog>
    </>
  );
}

const inputCls =
  "w-full rounded-lg border border-border bg-background px-3 py-1.5 text-[13px] focus:outline-none focus:ring-2 focus:ring-brand-purple-500";

function Field({
  children,
  label,
}: {
  children: React.ReactNode;
  label: string;
}) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
        {label}
      </label>
      {children}
    </div>
  );
}
