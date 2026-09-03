"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useRef, useState } from "react";

import type { NotificationItem } from "@/lib/api.client";

import { useApi } from "@/lib/api.client";

const POLL_INTERVAL_MS = 50_000; // ~45-60s
const REFRESH_EVENT = "myperks:notifications-refresh";

/** Ask any mounted `useNotifications()` hooks to refetch now. */
export function triggerNotificationsRefresh() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(REFRESH_EVENT));
}

export function useNotifications() {
  const api = useApi();
  const { isSignedIn } = useAuth();

  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<null | string>(null);

  // Avoids clobbering newer state with a stale in-flight response.
  const requestIdRef = useRef(0);

  const refetch = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    try {
      const data = await api.listNotifications();
      if (requestIdRef.current !== requestId) return;
      setItems(data.items);
      setUnreadCount(data.meta.unread_count);
      setError(null);
    } catch (err) {
      if (requestIdRef.current !== requestId) return;
      setError(
        err instanceof Error ? err.message : "Could not load notifications.",
      );
    } finally {
      if (requestIdRef.current === requestId) setIsLoading(false);
    }
  }, [api]);

  useEffect(() => {
    if (!isSignedIn) return;

    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refetch();
    const interval = setInterval(() => void refetch(), POLL_INTERVAL_MS);

    function handleFocus() {
      void refetch();
    }
    function handleVisibility() {
      if (document.visibilityState === "visible") void refetch();
    }
    function handleExternalRefresh() {
      void refetch();
    }

    window.addEventListener("focus", handleFocus);
    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener(REFRESH_EVENT, handleExternalRefresh);

    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", handleFocus);
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener(REFRESH_EVENT, handleExternalRefresh);
    };
  }, [isSignedIn, refetch]);

  const markAsRead = useCallback(
    async (id: number) => {
      const target = items.find((item) => item.id === id);
      if (!target || target.read_at) return;

      // Optimistic update; reconciled by the next poll if this fails.
      setItems((prev) =>
        prev.map((item) =>
          item.id === id
            ? { ...item, read_at: new Date().toISOString() }
            : item,
        ),
      );
      setUnreadCount((prev) => Math.max(0, prev - 1));

      try {
        await api.markNotificationRead(id);
      } catch (err) {
        console.error("[MyPerks] Failed to mark notification read:", err);
        void refetch();
      }
    },
    [api, items, refetch],
  );

  const markAllAsRead = useCallback(async () => {
    if (unreadCount === 0) return;

    const now = new Date().toISOString();
    setItems((prev) =>
      prev.map((item) => ({ ...item, read_at: item.read_at ?? now })),
    );
    setUnreadCount(0);

    try {
      await api.markAllNotificationsRead();
    } catch (err) {
      console.error("[MyPerks] Failed to mark all notifications read:", err);
      void refetch();
    }
  }, [api, unreadCount, refetch]);

  return {
    error,
    isLoading,
    items,
    markAllAsRead,
    markAsRead,
    refetch,
    unreadCount,
  };
}
