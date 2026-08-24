"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Award, Briefcase, ClipboardList, FileText, LayoutDashboard, User } from "lucide-react";
import { Suspense, useEffect } from "react";

import { DashboardShell, initialsFrom, type DashboardNavItem } from "@/components/shared/dashboard-shell";
import { useStudentProfile } from "@/hooks/use-student-profile";
import { useAuth } from "@/providers/auth-provider";

const NAV_ITEMS: DashboardNavItem[] = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard, exact: true },
  { href: "/dashboard/resume", label: "Resume", icon: FileText },
  { href: "/dashboard/drives", label: "Drives", icon: Briefcase },
  { href: "/dashboard/applications", label: "Applications", icon: ClipboardList },
  { href: "/dashboard/assessments", label: "Assessments", icon: Award },
  { href: "/dashboard/profile", label: "Profile", icon: User },
];

function GoogleProfileCompletionRedirect() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (pathname === "/dashboard" && searchParams.get("complete_profile") === "true") {
      router.replace("/dashboard/profile");
    }
  }, [pathname, searchParams, router]);

  return null;
}

/**
 * middleware.ts already redirects unauthenticated/wrong-role requests away
 * from /dashboard before this even renders — this is a client-side backstop
 * for the case the middleware's cookie says "student" but the actual
 * session (the httpOnly refresh cookie) turned out to be invalid or
 * expired, which AuthProvider's bootstrap discovers a moment after mount.
 */
export default function StudentDashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoading, logout } = useAuth();
  const { data: profile } = useStudentProfile();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && (!user || user.role !== "student")) {
      router.replace("/login");
    }
  }, [isLoading, user, router]);

  const handleLogout = async () => {
    await logout();
    router.push("/login");
  };

  if (isLoading || !user || user.role !== "student") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="text-sm text-muted-foreground">Loading your dashboard…</div>
      </div>
    );
  }

  return (
    <DashboardShell
      navItems={NAV_ITEMS}
      displayName={profile?.name ?? user.email}
      initials={initialsFrom(profile?.name, user.email)}
      profileHref="/dashboard/profile"
      onLogout={handleLogout}
    >
      <Suspense fallback={null}>
        <GoogleProfileCompletionRedirect />
      </Suspense>
      {children}
    </DashboardShell>
  );
}
