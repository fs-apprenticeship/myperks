"use client";

import { Loader2, Pencil, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { type PatchEmployeeBody, useApi } from "@/lib/api.client";

const DEPARTMENTS = [
  "engineering",
  "sales",
  "marketing",
  "hr",
  "finance",
  "operations",
  "other",
] as const;

const ROLES = [
  { label: "Employee", value: "employee" },
  { label: "HR Admin", value: "hr_admin" },
] as const;

type Props = {
  currentDepartment: string;
  currentRole: string;
  employeeId: number;
  employeeName: string;
};

export function EditEmployeeDialog({
  currentDepartment,
  currentRole,
  employeeId,
  employeeName,
}: Props) {
  const api = useApi();
  const router = useRouter();
  const dialogRef = useRef<HTMLDialogElement>(null);

  const [form, setForm] = useState<PatchEmployeeBody>({
    department: currentDepartment,
    role: currentRole,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<null | string>(null);

  function open() {
    setError(null);
    setForm({ department: currentDepartment, role: currentRole });
    dialogRef.current?.showModal();
  }

  function close() {
    dialogRef.current?.close();
  }

  async function handleSubmit() {
    setLoading(true);
    setError(null);
    try {
      await api.patchEmployee(employeeId, form);
      close();
      router.refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <button
        className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[12px] font-medium hover:bg-muted"
        onClick={open}
        type="button"
      >
        <Pencil className="h-3.5 w-3.5" />
        Edit
      </button>

      <dialog
        className="m-auto w-full max-w-sm rounded-xl border border-border bg-white p-6 shadow-xl backdrop:bg-black/40 dark:bg-card"
        ref={dialogRef}
      >
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-[15px] font-semibold">Edit {employeeName}</h2>
          <button
            className="rounded p-1 text-muted-foreground hover:text-foreground"
            onClick={close}
            type="button"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
              Department
            </label>
            <select
              className={inputCls}
              onChange={(e) =>
                setForm((p) => ({ ...p, department: e.target.value }))
              }
              value={form.department}
            >
              {DEPARTMENTS.map((d) => (
                <option key={d} value={d}>
                  {d.charAt(0).toUpperCase() + d.slice(1)}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
              Role
            </label>
            <select
              className={inputCls}
              onChange={(e) => setForm((p) => ({ ...p, role: e.target.value }))}
              value={form.role}
            >
              {ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>
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
            Save changes
          </button>
        </div>
      </dialog>
    </>
  );
}

const inputCls =
  "w-full rounded-lg border border-border bg-background px-3 py-1.5 text-[13px] focus:outline-none focus:ring-2 focus:ring-brand-purple-500";
