import { useAuth } from "@clerk/nextjs";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NotificationItem } from "@/lib/api.client";

import { useApi } from "@/lib/api.client";

import {
  triggerNotificationsRefresh,
  useNotifications,
} from "./use-notifications";

vi.mock("@/lib/api.client", () => ({
  useApi: vi.fn(),
}));

vi.mock("@clerk/nextjs", () => ({
  useAuth: vi.fn(),
}));

function makeNotification(
  overrides: Partial<NotificationItem> = {},
): NotificationItem {
  return {
    created_at: "2026-01-01T00:00:00Z",
    id: 1,
    message: "Your pto request was approved",
    payload: null,
    read_at: null,
    related_request_id: 10,
    type: "request_status_changed",
    ...overrides,
  };
}

const listNotifications = vi.fn();
const markNotificationRead = vi.fn();
const markAllNotificationsRead = vi.fn();

function mockListResponse(
  items: NotificationItem[],
  unreadCount = items.filter((i) => !i.read_at).length,
) {
  listNotifications.mockResolvedValue({
    items,
    meta: { unread_count: unreadCount },
    page: 1,
    page_size: 20,
    total: items.length,
  });
}

describe("useNotifications", () => {
  beforeEach(() => {
    listNotifications.mockReset();
    markNotificationRead.mockReset().mockResolvedValue({
      id: 1,
      read_at: "2026-01-01T00:00:00Z",
    });
    markAllNotificationsRead.mockReset().mockResolvedValue({ updated: 0 });
    mockListResponse([]);

    vi.mocked(useApi).mockReturnValue({
      listNotifications,
      markAllNotificationsRead,
      markNotificationRead,
    } as unknown as ReturnType<typeof useApi>);

    vi.mocked(useAuth).mockReturnValue({
      isSignedIn: true,
    } as unknown as ReturnType<typeof useAuth>);
  });

  it("fetches notifications on mount and exposes items + unread count", async () => {
    const item = makeNotification();
    mockListResponse([item], 1);

    const { result } = renderHook(() => useNotifications());
    await act(async () => {});

    expect(listNotifications).toHaveBeenCalledTimes(1);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.items).toEqual([item]);
    expect(result.current.unreadCount).toBe(1);
  });

  it("does not fetch when the user is not signed in", async () => {
    vi.mocked(useAuth).mockReturnValue({
      isSignedIn: false,
    } as unknown as ReturnType<typeof useAuth>);

    renderHook(() => useNotifications());
    await act(async () => {});

    expect(listNotifications).not.toHaveBeenCalled();
  });

  it("surfaces an error message when the fetch fails", async () => {
    listNotifications.mockReset().mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => useNotifications());
    await act(async () => {});

    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBe("boom");
  });

  it("polls again after the interval elapses", async () => {
    vi.useFakeTimers();
    try {
      renderHook(() => useNotifications());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(listNotifications).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(50_000);
      });
      expect(listNotifications).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("refetches when the window regains focus", async () => {
    renderHook(() => useNotifications());
    await act(async () => {});
    expect(listNotifications).toHaveBeenCalledTimes(1);

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(listNotifications).toHaveBeenCalledTimes(2);
  });

  it("refetches when triggerNotificationsRefresh() is called", async () => {
    renderHook(() => useNotifications());
    await act(async () => {});
    expect(listNotifications).toHaveBeenCalledTimes(1);

    await act(async () => {
      triggerNotificationsRefresh();
    });
    expect(listNotifications).toHaveBeenCalledTimes(2);
  });

  it("marks a single notification read optimistically", async () => {
    const item = makeNotification();
    mockListResponse([item], 1);

    const { result } = renderHook(() => useNotifications());
    await act(async () => {});

    await act(async () => {
      await result.current.markAsRead(item.id);
    });

    expect(markNotificationRead).toHaveBeenCalledWith(item.id);
    expect(result.current.unreadCount).toBe(0);
    expect(result.current.items[0]?.read_at).not.toBeNull();
  });

  it("does nothing when marking an already-read notification as read", async () => {
    const item = makeNotification({ read_at: "2026-01-01T00:00:00Z" });
    mockListResponse([item], 0);

    const { result } = renderHook(() => useNotifications());
    await act(async () => {});

    await act(async () => {
      await result.current.markAsRead(item.id);
    });

    expect(markNotificationRead).not.toHaveBeenCalled();
  });

  it("refetches to reconcile state when marking read fails", async () => {
    const item = makeNotification();
    mockListResponse([item], 1);
    markNotificationRead.mockRejectedValue(new Error("network error"));

    const { result } = renderHook(() => useNotifications());
    await act(async () => {});
    expect(listNotifications).toHaveBeenCalledTimes(1);

    await act(async () => {
      await result.current.markAsRead(item.id);
    });

    expect(listNotifications).toHaveBeenCalledTimes(2);
  });

  it("marks all notifications read and zeroes the unread count", async () => {
    const items = [
      makeNotification({ id: 1 }),
      makeNotification({ id: 2, read_at: "2026-01-01T00:00:00Z" }),
      makeNotification({ id: 3 }),
    ];
    mockListResponse(items, 2);

    const { result } = renderHook(() => useNotifications());
    await act(async () => {});
    expect(result.current.unreadCount).toBe(2);

    await act(async () => {
      await result.current.markAllAsRead();
    });

    expect(markAllNotificationsRead).toHaveBeenCalledTimes(1);
    expect(result.current.unreadCount).toBe(0);
    expect(result.current.items.every((i) => i.read_at !== null)).toBe(true);
  });

  it("does not call the API when marking all read with nothing unread", async () => {
    mockListResponse(
      [makeNotification({ read_at: "2026-01-01T00:00:00Z" })],
      0,
    );

    const { result } = renderHook(() => useNotifications());
    await act(async () => {});

    await act(async () => {
      await result.current.markAllAsRead();
    });

    expect(markAllNotificationsRead).not.toHaveBeenCalled();
  });
});
