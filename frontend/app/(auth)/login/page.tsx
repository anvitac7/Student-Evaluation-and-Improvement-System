"use client";

import { Suspense } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { GoogleSignInButton } from "@/components/shared/google-sign-in-button";
import { apiClient } from "@/lib/api-client";
import { setAccessToken } from "@/lib/token-store";
import { useAuth } from "@/providers/auth-provider";
import type { LoginResponse } from "@/types/auth";

const loginSchema = z.object({
  email: z.string().email("Enter a valid email address."),
  password: z.string().min(8, "Password must be at least 8 characters."),
});

type LoginFormValues = z.infer<typeof loginSchema>;

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setUser } = useAuth();

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({ resolver: zodResolver(loginSchema) });

  const onSubmit = async (values: LoginFormValues) => {
    try {
      const { data } = await apiClient.post<LoginResponse>("/auth/login", values);
      setAccessToken(data.access_token);
      setUser(data.user);
      document.cookie = `placer_role=${data.user.role}; path=/; SameSite=Strict`;

      const redirectTo = searchParams.get("redirect");
      const roleHome =
        data.user.role === "admin" ? "/admin/dashboard" : data.user.role === "tpo" ? "/tpo/dashboard" : "/dashboard";
      router.push(redirectTo ?? roleHome);
    } catch (err: any) {
      if (err?.response?.status === 401) {
        setError("root", { message: "Invalid email or password. Please try again." });
      } else if (err?.response) {
        // Backend reached but returned something else (validation error, 500, etc.)
        const detail = err.response.data?.detail;
        setError("root", { message: typeof detail === "string" ? detail : "Something went wrong. Please try again." });
      } else {
        // No response at all — request never reached the backend (proxy/network/CORS issue).
        setError("root", {
          message: "Couldn't reach the server. Check that the backend is running and try again.",
        });
      }
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sign in to PLACER</CardTitle>
        <CardDescription>Access your placement dashboard.</CardDescription>
      </CardHeader>
      <form onSubmit={handleSubmit(onSubmit)}>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" placeholder="you@college.edu" {...register("email")} />
            {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" placeholder="••••••••" {...register("password")} />
            {errors.password && <p className="text-sm text-destructive">{errors.password.message}</p>}
          </div>
          {errors.root && <p className="text-sm text-destructive">{errors.root.message}</p>}
        </CardContent>
        <CardFooter className="flex flex-col gap-4">
          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? "Signing in…" : "Sign in"}
          </Button>
          <div className="flex w-full items-center gap-3">
            <div className="h-px flex-1 bg-border" />
            <span className="text-xs text-muted-foreground">OR</span>
            <div className="h-px flex-1 bg-border" />
          </div>
          <GoogleSignInButton />
          <p className="text-sm text-muted-foreground">
            Don&apos;t have an account?{" "}
            <Link href="/register" className="text-primary underline underline-offset-4">
              Register
            </Link>
          </p>
        </CardFooter>
      </form>
    </Card>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
