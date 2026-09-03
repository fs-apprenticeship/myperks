"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { AdminRequestListItem } from "@/lib/api.server";

import { RequestDetailDialog } from "@/components/admin/request-detail-dialog";
import { ConfirmDialog } from "@/components/history/confirm-dialog";
import { StatusBadge } from "@/components/shared/status-badge";
import { triggerNotificationsRefresh } from "@/hooks/use-notifications";
import { useApi } from "@/lib/api.client";
import {
  formatRequestType,
  getRequestDate,
  getRequestDescription,
} from "@/lib/format";

type ConfirmTarget = {
  action: "approved" | "rejected";
  item: AdminRequestListItem;
};

export function RequestQueueClient({
  initialItems,
  removeOnAction,
}: {
  initialItems: AdminRequestListItem[];
  removeOnAction: boolean;
}) {
  const api = useApi();
  const router = useRouter();

  const [items, setItems] = useState(initialItems);
  const [detailItem, setDetailItem] = useState<AdminRequestListItem | null>(
    null,
  );
  const [confirmTarget, setConfirmTarget] = useState<ConfirmTarget | null>(
    null,
  );
  const [rejectionReason, setRejectionReason] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<null | string>(null);

  function openConfirm(
    item: AdminRequestListItem,
    action: "approved" | "rejected",
  ) {
    setError(null);
    setRejectionReason("");
    setConfirmTarget({ action, item });
  }

  function closeConfirm() {
    if (isPending) return;
    setConfirmTarget(null);
    setRejectionReason("");
  }

  async function handleConfirm() {
    if (!confirmTarget) return;
    setIsPending(true);
    setError(null);

    try {
      await api.approveOrRejectRequest(confirmTarget.item.id, {
        rejection_reason:
          confirmTarget.action === "rejected"
            ? rejectionReason.trim() || undefined
            : undefined,
        status: confirmTarget.action,
      });

      if (removeOnAction) {
        setItems((prev) => prev.filter((i) => i.id !== confirmTarget.item.id));
      } else {
        setItems((prev) =>
          prev.map((i) =>
            i.id === confirmTarget.item.id
              ? { ...i, status: confirmTarget.action }
              : i,
          ),
        );
      }

      setConfirmTarget(null);
      setRejectionReason("");
      triggerNotificationsRefresh();
      router.refresh();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not update this request.",
      );
    } finally {
      setIsPending(false);
    }
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-16 text-center">
        <p className="text-sm font-medium">No requests</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Nothing to review here right now.
        </p>
      </div>
    );
  }

  return (
    <>
      {error && (
        <p className="mb-3 text-sm text-destructive" role="alert">
          {error}
        </p>
      )}

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border bg-muted/40">
              <th className="py-3 pl-4 pr-4 text-left text-[10px] font-semibold uppercase tracking-[0.07em] text-muted-foreground">
                Employee
              </th>
              <th className="py-3 pr-4 text-center text-[10px] font-semibold uppercase tracking-[0.07em] text-muted-foreground">
                Type
              </th>
              <th className="py-3 pr-4 text-center text-[10px] font-semibold uppercase tracking-[0.07em] text-muted-foreground">
                Dates
              </th>
              <th className="py-3 pr-4 text-center text-[10px] font-semibold uppercase tracking-[0.07em] text-muted-foreground">
                Description
              </th>
              <th className="py-3 pr-4 text-center text-[10px] font-semibold uppercase tracking-[0.07em] text-muted-foreground">
                Status
              </th>
              <th className="py-3 pr-4 text-center text-[10px] font-semibold uppercase tracking-[0.07em] text-muted-foreground">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {items.map((item) => (
              <tr
                className="border-b border-border last:border-0"
                key={item.id}
              >
                <td className="py-3 pl-4 pr-4 text-sm font-medium">
                  <button
                    className="hover:underline"
                    onClick={() => setDetailItem(item)}
                    type="button"
                  >
                    {item.employee_name}
                  </button>
                </td>
                <td className="py-3 pr-4 text-center text-sm">
                  {formatRequestType(item.type)}
                </td>
                <td className="py-3 pr-4 text-center text-sm text-muted-foreground">
                  {getRequestDate(item)}
                </td>
                <td className="py-3 pr-4 text-center text-sm text-muted-foreground">
                  {getRequestDescription(item.body)}
                </td>
                <td className="py-3 pr-4 text-center">
                  <StatusBadge status={item.status} />
                </td>
                <td className="py-3 pr-4 text-center">
                  {item.status === "pending" ? (
                    <div className="flex justify-center gap-2">
                      <button
                        className="rounded-md border border-border px-2.5 py-1 text-xs font-medium text-green-700 transition-colors hover:bg-green-50 dark:text-green-400 dark:hover:bg-green-900/20"
                        onClick={() => openConfirm(item, "approved")}
                        type="button"
                      >
                        Approve
                      </button>
                      <button
                        className="rounded-md border border-border px-2.5 py-1 text-xs font-medium text-destructive transition-colors hover:bg-destructive/10"
                        onClick={() => openConfirm(item, "rejected")}
                        type="button"
                      >
                        Reject
                      </button>
                    </div>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ConfirmDialog
        confirmLabel={
          confirmTarget?.action === "approved" ? "Approve" : "Reject"
        }
        description={
          confirmTarget && (
            <div className="space-y-3">
              <p>
                {confirmTarget.action === "approved" ? "Approve" : "Reject"} the{" "}
                {formatRequestType(confirmTarget.item.type).toLowerCase()}{" "}
                request from <strong>{confirmTarget.item.employee_name}</strong>
                ?
              </p>
              {confirmTarget.action === "rejected" && (
                <textarea
                  className="w-full rounded-md border border-border bg-background p-2 text-sm outline-none placeholder:text-muted-foreground focus:border-brand-purple-400"
                  onChange={(e) => setRejectionReason(e.target.value)}
                  placeholder="Reason for rejection (optional)"
                  rows={3}
                  value={rejectionReason}
                />
              )}
            </div>
          )
        }
        isOpen={confirmTarget !== null}
        isPending={isPending}
        onCancel={closeConfirm}
        onConfirm={handleConfirm}
        title={
          confirmTarget?.action === "approved"
            ? "Approve request?"
            : "Reject request?"
        }
        variant={
          confirmTarget?.action === "rejected" ? "destructive" : "default"
        }
      />

      <RequestDetailDialog
        item={detailItem}
        onApprove={() => {
          if (!detailItem) return;
          openConfirm(detailItem, "approved");
          setDetailItem(null);
        }}
        onClose={() => setDetailItem(null)}
        onReject={() => {
          if (!detailItem) return;
          openConfirm(detailItem, "rejected");
          setDetailItem(null);
        }}
      />
    </>
  );
}
