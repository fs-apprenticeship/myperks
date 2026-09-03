"use client";

import { Bell } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import type { NotificationItem } from "@/lib/api.client";

import { useNotifications } from "@/hooks/use-notifications";
import { cn } from "@/lib/cn";
import { formatRelativeTime } from "@/lib/format";

export function NotificationsMenu() {
  const router = useRouter();
  const { error, isLoading, items, markAllAsRead, markAsRead, unreadCount } =
    useNotifications();

  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const close = useCallback(() => setIsOpen(false), []);

  useEffect(() => {
    if (!isOpen) return;

    function handlePointerDown(event: PointerEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        close();
      }
    }
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") close();
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKey);
    };
  }, [isOpen, close]);

  function handleItemClick(notification: NotificationItem) {
    if (!notification.read_at) void markAsRead(notification.id);
    close();
    router.push(getNotificationHref(notification));
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        aria-expanded={isOpen}
        aria-haspopup="menu"
        aria-label="Notifications"
        className="relative text-muted-foreground transition-colors hover:text-foreground"
        onClick={() => setIsOpen((prev) => !prev)}
        type="button"
      >
        <Bell className="h-[17px] w-[17px]" />
        {unreadCount > 0 && (
          <span
            aria-hidden="true"
            className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full border-[1.5px] border-white bg-brand-amber-400 dark:border-card"
          />
        )}
      </button>

      {isOpen && (
        <div
          className="absolute right-0 top-full z-20 mt-2 w-80 overflow-hidden rounded-lg border border-border bg-card shadow-md"
          role="menu"
        >
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-[12px] font-semibold">Notifications</span>
            {unreadCount > 0 && (
              <button
                className="text-[11px] font-medium text-brand-purple-600 hover:underline dark:text-brand-purple-400"
                onClick={() => void markAllAsRead()}
                type="button"
              >
                Mark all as read
              </button>
            )}
          </div>

          <div className="max-h-80 overflow-y-auto">
            {isLoading && items.length === 0 ? (
              <p className="px-3 py-6 text-center text-[12px] text-muted-foreground">
                Loading…
              </p>
            ) : error && items.length === 0 ? (
              <p className="px-3 py-6 text-center text-[12px] text-destructive">
                {error}
              </p>
            ) : items.length === 0 ? (
              <p className="px-3 py-6 text-center text-[12px] text-muted-foreground">
                You&apos;re all caught up.
              </p>
            ) : (
              <ul>
                {items.map((notification) => (
                  <li key={notification.id}>
                    <button
                      className={cn(
                        "block w-full border-b border-border px-3 py-2.5 text-left last:border-0 transition-colors hover:bg-surface-2",
                        !notification.read_at &&
                          "bg-brand-purple-50 dark:bg-brand-purple-900/20",
                      )}
                      onClick={() => handleItemClick(notification)}
                      role="menuitem"
                      type="button"
                    >
                      <div className="flex items-start gap-2">
                        {!notification.read_at && (
                          <span
                            aria-hidden="true"
                            className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-purple-600 dark:bg-brand-purple-400"
                          />
                        )}
                        <div
                          className={cn(
                            "min-w-0",
                            notification.read_at && "pl-3.5",
                          )}
                        >
                          <p className="text-[12.5px] leading-snug text-foreground">
                            {notification.message}
                          </p>
                          <p className="mt-0.5 text-[11px] text-muted-foreground">
                            {formatRelativeTime(notification.created_at)}
                          </p>
                        </div>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** Where a notification's "view request" link should go, derived from its type. */
function getNotificationHref(notification: NotificationItem): string {
  const base =
    notification.type === "request_submitted" ? "/admin/requests" : "/requests";
  return `${base}?requestId=${notification.related_request_id}`;
}
