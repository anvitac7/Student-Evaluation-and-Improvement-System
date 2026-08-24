"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Combobox } from "@/components/ui/combobox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PasswordInput } from "@/components/ui/password-input";
import { GoogleSignInButton } from "@/components/shared/google-sign-in-button";
import { apiClient } from "@/lib/api-client";
import { DEPARTMENTS } from "@/lib/departments";

type Role = "student" | "tpo";

const currentYear = new Date().getFullYear();

const studentSchema = z.object({
  name: z.string().min(1, "Name is required."),
  email: z.string().email("Enter a valid email address."),
  password: z.string().min(8, "Password must be at least 8 characters."),
  department: z.string().min(1, "Department is required."),
  batch_year: z.coerce
    .number({ invalid_type_error: "Graduation year is required." })
    .int("Graduation year must be a whole number.")
    .min(currentYear - 6, `Graduation year cannot be before ${currentYear - 6}.`)
    .max(currentYear + 6, `Graduation year cannot be after ${currentYear + 6}.`)
    .refine((val) => val >= 0, "Graduation year cannot be negative."),
});

const tpoSchema = z.object({
  name: z.string().min(1, "Name is required."),
  email: z.string().email("Enter a valid email address."),
  password: z.string().min(8, "Password must be at least 8 characters."),
  department_scope: z.string().optional(),
});

type StudentFormValues = z.infer<typeof studentSchema>;
type TPOFormValues = z.infer<typeof tpoSchema>;

function StudentRegisterForm() {
  const router = useRouter();
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<StudentFormValues>({ resolver: zodResolver(studentSchema) });

  const onSubmit = async (values: StudentFormValues) => {
    try {
      await apiClient.post("/auth/register/student", values);
      router.push("/login?registered=true");
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Registration failed. Please try again.";
      setError("root", { message: detail });
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="name">Full name</Label>
        <Input id="name" {...register("name")} />
        {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
      </div>
      <div className="space-y-2">
        <Label htmlFor="email">Email</Label>
        <Input id="email" type="email" placeholder="you@college.edu" {...register("email")} />
        {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
      </div>
      <div className="space-y-2">
        <Label htmlFor="password">Password</Label>
        <PasswordInput id="password" {...register("password")} />
        {errors.password && <p className="text-sm text-destructive">{errors.password.message}</p>}
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="department">Department</Label>
          <Combobox
            id="department"
            options={DEPARTMENTS}
            placeholder="Type or select a department"
            {...register("department")}
          />
          {errors.department && <p className="text-sm text-destructive">{errors.department.message}</p>}
        </div>
        <div className="space-y-2">
          <Label htmlFor="batch_year">Graduation year</Label>
          <Input
            id="batch_year"
            type="number"
            min={currentYear - 6}
            max={currentYear + 6}
            step={1}
            {...register("batch_year")}
          />
          {errors.batch_year && <p className="text-sm text-destructive">{errors.batch_year.message}</p>}
        </div>
      </div>
      {errors.root && <p className="text-sm text-destructive">{errors.root.message}</p>}
      <Button type="submit" className="w-full" disabled={isSubmitting}>
        {isSubmitting ? "Creating account…" : "Create account"}
      </Button>
    </form>
  );
}

function TPORegisterForm() {
  const router = useRouter();
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<TPOFormValues>({ resolver: zodResolver(tpoSchema) });

  const onSubmit = async (values: TPOFormValues) => {
    try {
      const department_scope = values.department_scope
        ? values.department_scope.split(",").map((d) => d.trim()).filter(Boolean)
        : [];
      await apiClient.post("/auth/register/tpo", { ...values, department_scope });
      router.push("/login?registered=true");
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Registration failed. Please try again.";
      setError("root", { message: detail });
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="tpo-name">Full name</Label>
        <Input id="tpo-name" {...register("name")} />
        {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
      </div>
      <div className="space-y-2">
        <Label htmlFor="tpo-email">Email</Label>
        <Input id="tpo-email" type="email" placeholder="you@college.edu" {...register("email")} />
        {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
      </div>
      <div className="space-y-2">
        <Label htmlFor="tpo-password">Password</Label>
        <PasswordInput id="tpo-password" {...register("password")} />
        {errors.password && <p className="text-sm text-destructive">{errors.password.message}</p>}
      </div>
      <div className="space-y-2">
        <Label htmlFor="department_scope">Departments you manage (comma-separated)</Label>
        <Input id="department_scope" placeholder="Computer Science, Electronics" {...register("department_scope")} />
      </div>
      {errors.root && <p className="text-sm text-destructive">{errors.root.message}</p>}
      <Button type="submit" className="w-full" disabled={isSubmitting}>
        {isSubmitting ? "Creating account…" : "Create account"}
      </Button>
    </form>
  );
}

export default function RegisterPage() {
  const [role, setRole] = useState<Role>("student");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Create your account</CardTitle>
        <CardDescription>Choose your role to get started.</CardDescription>
        <div className="mt-3 flex gap-2">
          <Button
            type="button"
            size="sm"
            variant={role === "student" ? "default" : "outline"}
            onClick={() => setRole("student")}
          >
            Student
          </Button>
          <Button
            type="button"
            size="sm"
            variant={role === "tpo" ? "default" : "outline"}
            onClick={() => setRole("tpo")}
          >
            TPO
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {role === "student" ? <StudentRegisterForm /> : <TPORegisterForm />}
        <div className="flex w-full items-center gap-3">
          <div className="h-px flex-1 bg-border" />
          <span className="text-xs text-muted-foreground">OR</span>
          <div className="h-px flex-1 bg-border" />
        </div>
        <GoogleSignInButton role={role} />
      </CardContent>
      <CardFooter>
        <p className="text-sm text-muted-foreground">
          Already have an account?{" "}
          <Link href="/login" className="text-primary underline underline-offset-4">
            Sign in
          </Link>
        </p>
      </CardFooter>
    </Card>
  );
}
