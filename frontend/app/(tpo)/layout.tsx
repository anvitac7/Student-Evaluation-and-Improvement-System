"use client";

import { useRouter } from "next/navigation";
import { BarChart3, Briefcase, LayoutDashboard, Target, TrendingUp } from "lucide-react";
import { useEffect } from "react";

import { DashboardShell, initialsFrom, type DashboardNavItem } from "@/components/shared/dashboard-shell";
import { useAuth } from "@/providers/auth-provider";

const NAV_ITEMS: DashboardNavItem[] = [
  { href: "/tpo/dashboard", label: "Overview", icon: LayoutDashboard, exact: true },
  { href: "/tpo/dashboard/drives", label: "Drives", icon: Briefcase },
  // Exact match so the trending (Market Insights) sub-route doesn't also
  // highlight "Analytics".
  { href: "/tpo/dashboard/analytics", label: "Analytics", icon: BarChart3, exact: true },
  { href: "/tpo/dashboard/analytics/trending", label: "Market Insights", icon: TrendingUp },
  { href: "/tpo/dashboard/analytics/skill-gaps", label: "Skill Gaps", icon: Target },
];

/**
 * middleware.ts already redirects unauthenticated/wrong-role requests away
 * from /tpo before this even renders — this is a client-side backstop, same
 * reasoning as the student layout's guard.
 */
export default function TpoDashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoading, logout } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && (!user || user.role !== "tpo")) {
      router.replace("/login");
    }
  }, [isLoading, user, router]);

  const handleLogout = async () => {
    await logout();
    router.push("/login");
  };

  if (isLoading || !user || user.role !== "tpo") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="text-sm text-muted-foreground">Loading your dashboard…</div>
      </div>
    );
  }

  return (
    <DashboardShell
      navItems={NAV_ITEMS}
      displayName={user.email}
      initials={initialsFrom(undefined, user.email)}
      onLogout={handleLogout}
    >
      {children}
    </DashboardShell>
  );
}
