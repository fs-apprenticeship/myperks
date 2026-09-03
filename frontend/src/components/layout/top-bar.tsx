"use client";

import { UserButton } from "@clerk/nextjs";

import { NotificationsMenu } from "./notifications-menu";
import { ThemeToggle } from "./theme-toggle";

export function TopBar() {
  return (
    <header className="flex shrink-0 items-center justify-between border-b border-border bg-white px-5 py-3 dark:bg-card">
      <span className="text-[15px] font-semibold tracking-tight">
        My<span className="text-brand-purple-600">Perks</span>
      </span>
      <div className="flex items-center gap-3">
        <ThemeToggle />
        <NotificationsMenu />
        <UserButton afterSignOutUrl="/sign-in" />
      </div>
    </header>
  );
}
