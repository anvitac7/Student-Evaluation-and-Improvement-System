"use client";

import Link from "next/link";
import { Download, ListChecks, PlusCircle, Tags, Trash2, Upload } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/shared/empty-state";
import { QuestionForm } from "@/components/shared/question-form";
import { useToast } from "@/hooks/use-toast";
import {
  exportQuestions,
  useCategories,
  useCreateCategory,
  useDeleteQuestion,
  useImportQuestions,
  useQuestions,
  useUpdateQuestion,
} from "@/hooks/use-admin-questions";
import type { QuestionAdminResponse, QuestionCreateRequest } from "@/types/question";

function QuestionsTab() {
  const [categoryFilter, setCategoryFilter] = useState<string>("");
  const [difficultyFilter, setDifficultyFilter] = useState<string>("");
  const [editingQuestion, setEditingQuestion] = useState<QuestionAdminResponse | null>(null);
  const [importText, setImportText] = useState("");
  const [importDialogOpen, setImportDialogOpen] = useState(false);

  const { data: categories } = useCategories();
  const { data: questions, isLoading } = useQuestions(categoryFilter, difficultyFilter);
  const updateQuestion = useUpdateQuestion();
  const deleteQuestion = useDeleteQuestion();
  const importQuestions = useImportQuestions();
  const { toast } = useToast();

  const categoryName = (id: string) => categories?.find((c) => c.id === id)?.name ?? id;

  const handleUpdate = async (payload: QuestionCreateRequest) => {
    if (!editingQuestion) return;
    try {
      await updateQuestion.mutateAsync({ id: editingQuestion.id, payload });
      toast({ title: "Question updated" });
      setEditingQuestion(null);
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Couldn't save changes.";
      toast({ title: "Update failed", description: detail, variant: "destructive" });
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteQuestion.mutateAsync(id);
      toast({ title: "Question deleted" });
    } catch {
      toast({ title: "Couldn't delete this question", variant: "destructive" });
    }
  };

  const handleExport = async () => {
    try {
      const data = await exportQuestions(categoryFilter, difficultyFilter);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "questions-export.json";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch {
      toast({ title: "Export failed", variant: "destructive" });
    }
  };

  const handleImport = async () => {
    let parsed: QuestionCreateRequest[];
    try {
      parsed = JSON.parse(importText);
      if (!Array.isArray(parsed)) throw new Error("not an array");
    } catch {
      toast({ title: "Invalid JSON", description: "Paste a JSON array of question objects.", variant: "destructive" });
      return;
    }
    try {
      const created = await importQuestions.mutateAsync(parsed);
      toast({ title: `Imported ${created.length} question(s)` });
      setImportText("");
      setImportDialogOpen(false);
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Import failed — check the JSON shape and try again.";
      toast({ title: "Import failed", description: detail, variant: "destructive" });
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          <Select value={categoryFilter || "all"} onValueChange={(v) => setCategoryFilter(v === "all" ? "" : v)}>
            <SelectTrigger className="w-48">
              <SelectValue placeholder="All categories" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All categories</SelectItem>
              {categories?.map((c) => (
                <SelectItem key={c.id} value={c.id}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={difficultyFilter || "all"} onValueChange={(v) => setDifficultyFilter(v === "all" ? "" : v)}>
            <SelectTrigger className="w-36">
              <SelectValue placeholder="All difficulties" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All difficulties</SelectItem>
              <SelectItem value="easy">Easy</SelectItem>
              <SelectItem value="medium">Medium</SelectItem>
              <SelectItem value="hard">Hard</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={handleExport}>
            <Download className="mr-1.5 h-3.5 w-3.5" />
            Export
          </Button>
          <Dialog open={importDialogOpen} onOpenChange={setImportDialogOpen}>
            <DialogTrigger asChild>
              <Button size="sm" variant="outline">
                <Upload className="mr-1.5 h-3.5 w-3.5" />
                Bulk import
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Bulk import questions</DialogTitle>
                <DialogDescription>
                  Paste a JSON array of question objects (same shape as the export format).
                </DialogDescription>
              </DialogHeader>
              <Textarea
                rows={10}
                className="font-mono text-xs"
                value={importText}
                onChange={(e) => setImportText(e.target.value)}
                placeholder='[{"category_id": "...", "difficulty": "medium", "type": "mcq", "text": "...", "options": ["A", "B"], "correct_answer": "A", "skill_tags": [], "company_tags": []}]'
              />
              <DialogFooter>
                <Button variant="secondary" onClick={() => setImportDialogOpen(false)}>
                  Cancel
                </Button>
                <Button onClick={handleImport} disabled={importQuestions.isPending}>
                  {importQuestions.isPending ? "Importing…" : "Import"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
          <Button asChild size="sm">
            <Link href="/admin/dashboard/questions/new">
              <PlusCircle className="mr-1.5 h-3.5 w-3.5" />
              New question
            </Link>
          </Button>
        </div>
      </div>

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : !questions || questions.length === 0 ? (
        <EmptyState icon={ListChecks} title="No questions found" description="Create one or adjust your filters." />
      ) : (
        <div className="space-y-2">
          {questions.map((q) => (
            <Card key={q.id}>
              <CardContent className="flex items-start justify-between gap-4 p-4">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{q.text}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                    <Badge variant="outline">{categoryName(q.category_id)}</Badge>
                    <Badge variant="secondary" className="capitalize">
                      {q.difficulty}
                    </Badge>
                    <Badge variant="secondary" className="uppercase">
                      {q.type}
                    </Badge>
                    {q.type === "coding" && q.language && (
                      <Badge variant="outline" className="capitalize">
                        {q.language}
                      </Badge>
                    )}
                    {q.type === "coding" && (
                      <span>
                        {q.test_cases.length} test case{q.test_cases.length === 1 ? "" : "s"}
                      </span>
                    )}
                    <span>{q.marks} marks</span>
                  </div>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button size="sm" variant="outline" onClick={() => setEditingQuestion(q)}>
                    Edit
                  </Button>
                  <Button size="sm" variant="destructive" onClick={() => handleDelete(q.id)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={Boolean(editingQuestion)} onOpenChange={(open) => !open && setEditingQuestion(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Edit question</DialogTitle>
          </DialogHeader>
          {editingQuestion && (
            <QuestionForm
              categories={categories ?? []}
              initialValues={editingQuestion}
              onSubmit={handleUpdate}
              submitLabel="Save changes"
              isSubmitting={updateQuestion.isPending}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function CategoriesTab() {
  const { data: categories, isLoading } = useCategories();
  const createCategory = useCreateCategory();
  const { toast } = useToast();
  const [name, setName] = useState("");

  const handleCreate = async () => {
    if (!name.trim()) return;
    try {
      await createCategory.mutateAsync({ name: name.trim() });
      setName("");
      toast({ title: "Category created" });
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? "Couldn't create the category.";
      toast({ title: "Creation failed", description: detail, variant: "destructive" });
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Add category</CardTitle>
        </CardHeader>
        <CardContent className="flex gap-2">
          <div className="flex-1 space-y-2">
            <Label htmlFor="category-name" className="sr-only">
              Category name
            </Label>
            <Input
              id="category-name"
              placeholder="e.g. Data Structures & Algorithms"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
            />
          </div>
          <Button onClick={handleCreate} disabled={createCategory.isPending || !name.trim()}>
            Add
          </Button>
        </CardContent>
      </Card>

      {isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : !categories || categories.length === 0 ? (
        <EmptyState icon={Tags} title="No categories yet" description="Add one above to start building the question bank." />
      ) : (
        <div className="flex flex-wrap gap-2">
          {categories.map((c) => (
            <Badge key={c.id} variant="outline" className="px-3 py-1.5 text-sm">
              {c.name}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

export default function QuestionBankPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl font-semibold">Question bank</h1>
        <p className="text-sm text-muted-foreground">Manage categories and questions used by adaptive assessments.</p>
      </div>

      <Tabs defaultValue="questions">
        <TabsList>
          <TabsTrigger value="questions">Questions</TabsTrigger>
          <TabsTrigger value="categories">Categories</TabsTrigger>
        </TabsList>
        <TabsContent value="questions">
          <QuestionsTab />
        </TabsContent>
        <TabsContent value="categories">
          <CategoriesTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
