import { fireEvent, render, screen } from "@testing-library/react";
import { useRouter } from "next/navigation";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NotificationItem } from "@/lib/api.client";

import { useNotifications } from "@/hooks/use-notifications";

import { NotificationsMenu } from "./notifications-menu";

vi.mock("@/hooks/use-notifications", () => ({
  useNotifications: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
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
    related_request_id: 42,
    type: "request_status_changed",
    ...overrides,
  };
}

const markAsRead = vi.fn();
const markAllAsRead = vi.fn();
const push = vi.fn();

function mockNotifications(
  overrides: Partial<ReturnType<typeof useNotifications>> = {},
) {
  vi.mocked(useNotifications).mockReturnValue({
    error: null,
    isLoading: false,
    items: [],
    markAllAsRead,
    markAsRead,
    refetch: vi.fn(),
    unreadCount: 0,
    ...overrides,
  });
}

describe("NotificationsMenu", () => {
  beforeEach(() => {
    markAsRead.mockReset();
    markAllAsRead.mockReset();
    push.mockReset();
    vi.mocked(useRouter).mockReturnValue({
      push,
    } as unknown as ReturnType<typeof useRouter>);
    mockNotifications();
  });

  it("hides the badge when there are no unread notifications", () => {
    mockNotifications({ unreadCount: 0 });
    render(<NotificationsMenu />);

    expect(
      screen
        .getByRole("button", { name: "Notifications" })
        .querySelector("span"),
    ).not.toBeInTheDocument();
  });

  it("shows the badge when there are unread notifications", () => {
    mockNotifications({ unreadCount: 3 });
    render(<NotificationsMenu />);

    expect(
      screen
        .getByRole("button", { name: "Notifications" })
        .querySelector("span"),
    ).toBeInTheDocument();
  });

  it("keeps the dropdown closed until the bell is clicked", () => {
    mockNotifications({ items: [makeNotification()] });
    render(<NotificationsMenu />);

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("shows an empty state when there are no notifications", () => {
    mockNotifications({ items: [] });
    render(<NotificationsMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));

    expect(screen.getByText("You're all caught up.")).toBeInTheDocument();
  });

  it("lists notifications in the order the hook returns them", () => {
    const items = [
      makeNotification({ id: 1, message: "Newest" }),
      makeNotification({ id: 2, message: "Oldest" }),
    ];
    mockNotifications({ items, unreadCount: 1 });
    render(<NotificationsMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));

    const rendered = screen
      .getAllByRole("menuitem")
      .map((el) => el.textContent);
    expect(rendered[0]).toContain("Newest");
    expect(rendered[1]).toContain("Oldest");
  });

  it("marks an unread notification read and deep-links admins to the request queue", () => {
    const item = makeNotification({
      related_request_id: 77,
      type: "request_submitted",
    });
    mockNotifications({ items: [item], unreadCount: 1 });
    render(<NotificationsMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    fireEvent.click(screen.getByRole("menuitem"));

    expect(markAsRead).toHaveBeenCalledWith(item.id);
    expect(push).toHaveBeenCalledWith("/admin/requests?requestId=77");
  });

  it("deep-links employees to their request history for status-change notifications", () => {
    const item = makeNotification({
      related_request_id: 5,
      type: "request_status_changed",
    });
    mockNotifications({ items: [item], unreadCount: 1 });
    render(<NotificationsMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    fireEvent.click(screen.getByRole("menuitem"));

    expect(push).toHaveBeenCalledWith("/requests?requestId=5");
  });

  it("does not re-mark an already-read notification as read on click", () => {
    const item = makeNotification({ read_at: "2026-01-01T00:00:00Z" });
    mockNotifications({ items: [item], unreadCount: 0 });
    render(<NotificationsMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    fireEvent.click(screen.getByRole("menuitem"));

    expect(markAsRead).not.toHaveBeenCalled();
    expect(push).toHaveBeenCalled();
  });

  it("closes the dropdown after clicking a notification", () => {
    mockNotifications({ items: [makeNotification()], unreadCount: 1 });
    render(<NotificationsMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    fireEvent.click(screen.getByRole("menuitem"));

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it('only shows "Mark all as read" when something is unread', () => {
    mockNotifications({ items: [makeNotification()], unreadCount: 0 });
    render(<NotificationsMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));

    expect(
      screen.queryByRole("button", { name: "Mark all as read" }),
    ).not.toBeInTheDocument();
  });

  it('calls markAllAsRead when "Mark all as read" is clicked', () => {
    mockNotifications({ items: [makeNotification()], unreadCount: 1 });
    render(<NotificationsMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    fireEvent.click(screen.getByRole("button", { name: "Mark all as read" }));

    expect(markAllAsRead).toHaveBeenCalledTimes(1);
  });

  it("closes the dropdown when Escape is pressed", () => {
    mockNotifications({ items: [makeNotification()] });
    render(<NotificationsMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    expect(screen.getByRole("menu")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("closes the dropdown on an outside click", () => {
    mockNotifications({ items: [makeNotification()] });
    render(<NotificationsMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    expect(screen.getByRole("menu")).toBeInTheDocument();

    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("shows the loading state before the first response arrives", () => {
    mockNotifications({ isLoading: true, items: [] });
    render(<NotificationsMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));

    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("shows an error message when the fetch failed", () => {
    mockNotifications({ error: "Could not load notifications.", items: [] });
    render(<NotificationsMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));

    expect(
      screen.getByText("Could not load notifications."),
    ).toBeInTheDocument();
  });
});
