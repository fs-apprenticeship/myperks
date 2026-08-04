"use client";

import { useAuth } from "@clerk/nextjs";
import { useMemo } from "react";

const BACKEND_PREFIX = "/api/backend";

export interface AdminEmployeeDetail {
  balances: AdminBalanceSnapshot[];
  benefits_year_reset: string;
  department: string;
  email: string;
  id: number;
  joined_date: string;
  linked: boolean;
  name: string;
  request_history: RequestHistoryItem[];
  role: string;
}

export interface ApproveExtractionBody {
  carryover_cap_days?: null | number;
  notes?: string;
  proration_method?: "monthly" | "none" | null;
  pto_days?: null | number;
  sick_days?: null | number;
  vacation_days?: null | number;
  year: number;
}

export interface ApproveExtractionResponse {
  department: string;
  document_id: number;
  employees_updated: number;
  extraction_id: number;
  warning: null | string;
  year: number;
}

export interface ApproveRejectBody {
  rejection_reason?: string;
  status: "approved" | "rejected";
}

export interface ApproveRejectResponse {
  employee_email: string;
  employee_name: string;
  new_status: string;
  rejection_reason: null | string;
  request_id: number;
  request_type: string;
}

export interface CreateRequestPayload {
  body: Record<string, unknown>;
  type: string;
}

export interface DocumentExtractionResponse {
  approved_data: ExtractionData | null;
  document_id: number;
  error_message: null | string;
  extracted_data: ExtractionData | null;
  id: number;
  reviewed_at: null | string;
  status: "approved" | "extracted" | "extracting" | "failed" | "pending";
}

export interface DocumentListResponse {
  documents: DocumentItem[];
}

export interface ExtractionData {
  carryover_cap_days: null | number;
  notes: string;
  proration_method: "monthly" | "none" | null;
  pto_days: null | number;
  sick_days: null | number;
  vacation_days: null | number;
}
export interface MarkAllReadResponse {
  updated: number;
}

export interface Notification {
  created_at: string;
  id: number;
  message: string;
  payload: null | string;
  read_at: null | string;
  related_request_id: number;
  type: string;
}

export interface NotificationListResponse {
  items: Notification[];
  meta: NotificationsMeta;
  page: number;
  page_size: number;
  total: number;
}
export interface OnboardRequest {
  email: string;
}

export interface OnboardResponse {
  benefits_year_reset: string;
  clerk_user_id: string;
  department: null | string;
  email: null | string;
  id: number;
  joined_date: string;
  name: null | string;
  role: "employee" | "hr_admin";
}

export interface PatchEmployeeBody {
  department?: string;
  role?: string;
}

export interface PreCreateEmployeeBody {
  benefits_year_reset: string; // ISO date e.g. "2026-01-01"
  department: string;
  email: string;
  joined_date: string; // ISO date e.g. "2025-06-27"
  name: string;
}

export interface RequestHistoryItem {
  body: null | string;
  created_at: string;
  id: number;
  status: string;
  type: string;
}

interface AdminBalanceSnapshot {
  leave_type: string;
  remaining_days: number;
  total_days: number;
  used_days: number;
}

interface DocumentItem {
  department: string;
  extraction_status: null | string;
  filename: string;
  id: number;
  uploaded_at: string;
}

interface NotificationsMeta {
  unread_count: number;
}

export function useApi() {
  const { getToken } = useAuth();

  return useMemo(() => {
    async function apiGet<T>(path: string): Promise<T> {
      const token = await getToken();
      const response = await fetch(`${BACKEND_PREFIX}${path}`, {
        cache: "no-store",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      });
      if (!response.ok) {
        throw new Error(`API error: ${response.status} ${response.statusText}`);
      }
      return response.json() as Promise<T>;
    }

    async function apiPost<T>(path: string, body: unknown): Promise<T> {
      const token = await getToken();
      const response = await fetch(`${BACKEND_PREFIX}${path}`, {
        body: JSON.stringify(body),
        cache: "no-store",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        method: "POST",
      });
      if (!response.ok) {
        const detail = await response
          .json()
          .then((j: { detail?: string }) => j.detail)
          .catch(() => undefined);
        throw new Error(
          `API error: ${response.status}${detail ? ` – ${detail}` : ` ${response.statusText}`}`,
        );
      }
      return response.json() as Promise<T>;
    }

    async function apiPatch<T>(path: string, body: unknown): Promise<T> {
      const token = await getToken();
      const response = await fetch(`${BACKEND_PREFIX}${path}`, {
        body: JSON.stringify(body),
        cache: "no-store",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        method: "PATCH",
      });
      if (!response.ok) {
        const detail = await response
          .json()
          .then((j: { detail?: string }) => j.detail)
          .catch(() => undefined);
        throw new Error(
          `API error: ${response.status}${detail ? ` – ${detail}` : ` ${response.statusText}`}`,
        );
      }
      return response.json() as Promise<T>;
    }

    return {
      approveExtraction: (documentId: number, body: ApproveExtractionBody) =>
        apiPost<ApproveExtractionResponse>(
          `/admin/documents/${documentId}/extraction/approve`,
          body,
        ),
      approveOrRejectRequest: (requestId: number, body: ApproveRejectBody) =>
        apiPatch<ApproveRejectResponse>(`/admin/requests/${requestId}`, body),
      createRequest: (payload: CreateRequestPayload) =>
        apiPost<RequestHistoryItem>("/me/requests", payload),
      getAdminEmployeeDetail: (id: number) =>
        apiGet<AdminEmployeeDetail>(`/admin/employees/${id}`),
      getDocumentExtraction: (documentId: number) =>
        apiGet<DocumentExtractionResponse | null>(
          `/admin/documents/${documentId}/extraction`,
        ),
      getDocuments: () => apiGet<DocumentListResponse>("/upload/documents"),
      getMe: () => apiGet<OnboardResponse>("/employees/me"),
      listNotifications: (page: number) =>
        apiGet<NotificationListResponse>(`/me/notifications?page=${page}`),
      markAllNotificationsRead: () =>
        apiPatch<MarkAllReadResponse>("/me/notifications/read-all", {}),
      markNotificationRead: (id: number) =>
        apiPatch<Notification>(`/me/notifications/${id}/read`, {}),
      onboard: (body: OnboardRequest) =>
        apiPost<OnboardResponse>("/employees/me", body),
      patchEmployee: (id: number, body: PatchEmployeeBody) =>
        apiPatch<AdminEmployeeDetail>(`/admin/employees/${id}`, body),
      preCreateEmployee: (body: PreCreateEmployeeBody) =>
        apiPost<AdminEmployeeDetail>("/admin/employees", body),
      triggerExtraction: (documentId: number) =>
        apiPost<DocumentExtractionResponse>(
          `/admin/documents/${documentId}/extract`,
          {},
        ),
    };
  }, [getToken]);
}
