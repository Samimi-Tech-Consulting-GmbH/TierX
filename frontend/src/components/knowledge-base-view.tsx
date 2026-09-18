"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Download,
  FileUp,
  Eye,
  Loader2,
  RefreshCw,
  Search,
  Trash2,
  UploadCloud,
} from "lucide-react";
import { toast } from "sonner";

import {
  ApiError,
  deleteKnowledgeBaseDocument,
  downloadKnowledgeBaseDocument,
  listKnowledgeBaseDocuments,
  listKnowledgeBaseChunks,
  reprocessKnowledgeBaseDocument,
  searchKnowledgeBase,
  uploadKnowledgeBaseDocument,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatLocaleDateTime } from "@/lib/datetime";
import type {
  KnowledgeBaseChunk,
  KnowledgeBaseDocument,
  KnowledgeBaseSearchResponse,
} from "@/lib/types";
import { UserRole } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const PAGE_SIZE = 25;
const MAX_FILES_PER_BATCH = 10;
const MAX_FILE_BYTES = 50 * 1024 * 1024;
const ALLOWED_EXTENSIONS = [".md", ".txt"];

type UploadState = "QUEUED" | "UPLOADING" | "UPLOADED" | "FAILED";

interface QueuedUpload {
  id: string;
  file: File;
  state: UploadState;
  error?: string;
}

function errorMessage(error: unknown): string {
  return error instanceof ApiError
    ? error.detail
    : "The request could not be completed.";
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}

function clientValidation(file: File): string | null {
  const dot = file.name.lastIndexOf(".");
  const extension = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  if (!ALLOWED_EXTENSIONS.includes(extension)) {
    return "Unsupported type. Use MD or TXT.";
  }
  if (file.size === 0) return "Empty files are not allowed.";
  if (file.size > MAX_FILE_BYTES) return "File exceeds the 50 MiB limit.";
  return null;
}

export function KnowledgeBaseView({ tenantId }: { tenantId: string }) {
  const { user } = useAuth();
  const inputRef = useRef<HTMLInputElement>(null);
  const [documents, setDocuments] = useState<KnowledgeBaseDocument[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [queue, setQueue] = useState<QueuedUpload[]>([]);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [reprocessing, setReprocessing] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [retrievalMode, setRetrievalMode] = useState<"deterministic" | "hybrid">("deterministic");
  const [searchResult, setSearchResult] =
    useState<KnowledgeBaseSearchResponse | null>(null);
  const [inspecting, setInspecting] = useState<string | null>(null);
  const [visibleChunks, setVisibleChunks] = useState<KnowledgeBaseChunk[]>([]);

  const canWrite =
    user?.role === UserRole.PLATFORM_ADMIN ||
    user?.role === UserRole.TENANT_ADMIN;
  const accessDenied =
    !user ||
    (user.role !== UserRole.PLATFORM_ADMIN && user.tenant_id !== tenantId);

  const load = useCallback(async () => {
    const response = await listKnowledgeBaseDocuments(tenantId, {
      skip: page * PAGE_SIZE,
      limit: PAGE_SIZE,
    });
    setDocuments(response.items);
    setTotal(response.total);
  }, [page, tenantId]);

  useEffect(() => {
    if (accessDenied) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    load()
      .catch((error) => {
        if (!cancelled) toast.error(errorMessage(error));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [accessDenied, load]);

  function selectFiles(files: File[]) {
    setSelectionError(null);
    if (files.length > MAX_FILES_PER_BATCH) {
      setQueue([]);
      setSelectionError("Select at most 10 files per upload batch.");
      return;
    }
    setQueue(
      files.map((file, index) => {
        const validation = clientValidation(file);
        return {
          id: `${file.name}-${file.size}-${file.lastModified}-${index}`,
          file,
          state: validation ? "FAILED" : "QUEUED",
          error: validation ?? undefined,
        };
      }),
    );
  }

  async function uploadSelected() {
    const pending = queue.filter((item) => item.state === "QUEUED");
    if (pending.length === 0) return;
    setUploading(true);
    for (const item of pending) {
      setQueue((current) =>
        current.map((entry) =>
          entry.id === item.id
            ? { ...entry, state: "UPLOADING", error: undefined }
            : entry,
        ),
      );
      try {
        await uploadKnowledgeBaseDocument(tenantId, item.file);
        setQueue((current) =>
          current.map((entry) =>
            entry.id === item.id ? { ...entry, state: "UPLOADED" } : entry,
          ),
        );
        await load();
      } catch (error) {
        setQueue((current) =>
          current.map((entry) =>
            entry.id === item.id
              ? { ...entry, state: "FAILED", error: errorMessage(error) }
              : entry,
          ),
        );
      }
    }
    setUploading(false);
  }

  async function download(document: KnowledgeBaseDocument) {
    setDownloading(document.document_id);
    try {
      const blob = await downloadKnowledgeBaseDocument(
        tenantId,
        document.document_id,
      );
      const url = URL.createObjectURL(blob);
      const anchor = window.document.createElement("a");
      anchor.href = url;
      anchor.download = document.original_filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setDownloading(null);
    }
  }

  async function remove(document: KnowledgeBaseDocument) {
    if (
      !window.confirm(
        `Delete ${document.original_filename}? The stored file bytes will be removed.`,
      )
    ) {
      return;
    }
    setDeleting(document.document_id);
    try {
      await deleteKnowledgeBaseDocument(tenantId, document.document_id);
      toast.success("Knowledge Base file deleted");
      if (documents.length === 1 && page > 0) setPage((value) => value - 1);
      else await load();
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setDeleting(null);
    }
  }

  async function reprocess(document: KnowledgeBaseDocument) {
    setReprocessing(document.document_id);
    try {
      await reprocessKnowledgeBaseDocument(tenantId, document.document_id);
      toast.success("Knowledge Base document queued for processing");
      await load();
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setReprocessing(null);
    }
  }

  async function inspect(document: KnowledgeBaseDocument) {
    if (inspecting === document.document_id) {
      setInspecting(null);
      setVisibleChunks([]);
      return;
    }
    try {
      const response = await listKnowledgeBaseChunks(
        tenantId,
        document.document_id,
      );
      setInspecting(document.document_id);
      setVisibleChunks(response.items);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  async function runSearch() {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      setSearchResult(await searchKnowledgeBase(tenantId, searchQuery.trim(), 5, retrievalMode));
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setSearching(false);
    }
  }

  if (accessDenied) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Access denied</CardTitle>
        </CardHeader>
        <CardContent>
          You can only view your own tenant&apos;s Knowledge Base.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Knowledge Base</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Index tenant Markdown and text documents for playbook-enabled alert
          enrichment.
        </p>
      </div>

      <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
        Documents are indexed as untrusted analysis evidence. Uploads are not
        malware-scanned, and Knowledge Base text never changes alert status or
        verdict directly.
      </div>

      {canWrite && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <UploadCloud className="size-5 text-primary" /> Upload files
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div
              className={`rounded-lg border-2 border-dashed p-8 text-center transition-colors ${dragging ? "border-primary bg-primary/10" : "border-border"}`}
              onDragEnter={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                selectFiles(Array.from(event.dataTransfer.files));
              }}
            >
              <FileUp className="mx-auto mb-3 size-8 text-muted-foreground" />
              <p className="font-medium">Drop up to 10 files here</p>
              <p className="mt-1 text-sm text-muted-foreground">
                MD or TXT · UTF-8 · 50 MiB per file
              </p>
              <input
                ref={inputRef}
                className="sr-only"
                type="file"
                aria-label="Choose Knowledge Base files"
                accept=".md,.txt"
                multiple
                disabled={uploading}
                onChange={(event) =>
                  selectFiles(Array.from(event.target.files ?? []))
                }
              />
              <Button
                className="mt-4"
                variant="outline"
                disabled={uploading}
                onClick={() => inputRef.current?.click()}
              >
                Choose files
              </Button>
            </div>

            {selectionError && (
              <p role="alert" className="text-sm text-destructive">
                {selectionError}
              </p>
            )}

            {queue.length > 0 && (
              <div className="space-y-2" aria-label="Selected files">
                {queue.map((item) => (
                  <div
                    key={item.id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-medium">{item.file.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {formatBytes(item.file.size)}
                        {item.error ? ` · ${item.error}` : ""}
                      </p>
                    </div>
                    <Badge
                      variant={
                        item.state === "FAILED"
                          ? "destructive"
                          : item.state === "UPLOADED"
                            ? "success"
                            : "secondary"
                      }
                    >
                      {item.state === "UPLOADING" && (
                        <Loader2 className="size-3 animate-spin" />
                      )}
                      {item.state.toLowerCase()}
                    </Badge>
                  </div>
                ))}
                <div className="flex gap-2 pt-2">
                  <Button
                    onClick={() => void uploadSelected()}
                    disabled={
                      uploading ||
                      !queue.some((item) => item.state === "QUEUED")
                    }
                  >
                    {uploading && <Loader2 className="size-4 animate-spin" />}
                    Upload selected
                  </Button>
                  <Button
                    variant="ghost"
                    disabled={uploading}
                    onClick={() => setQueue([])}
                  >
                    Clear
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="size-5 text-primary" /> Test search
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <label className="flex items-center gap-2 text-sm">
            Retrieval mode
            <select aria-label="Retrieval mode" value={retrievalMode}
              className="rounded border bg-background p-2"
              onChange={(event) => setRetrievalMode(event.target.value as "deterministic" | "hybrid")}>
              <option value="deterministic">Deterministic</option>
              <option value="hybrid">Hybrid (Mem0 + deterministic)</option>
            </select>
          </label>
          {searchResult?.degraded && <p role="status" className="text-sm text-amber-500">
            Semantic retrieval {searchResult.semantic_status?.toLowerCase()}. Showing deterministic evidence only.
          </p>}
          <div className="flex gap-2">
            <Input
              value={searchQuery}
              placeholder="Try EXAMPLE-DB01, suspicious PowerShell, or 203.0.113.10"
              onChange={(event) => setSearchQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void runSearch();
              }}
            />
            <Button
              disabled={searching || !searchQuery.trim()}
              onClick={() => void runSearch()}
            >
              {searching ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Search className="size-4" />
              )}
              Search
            </Button>
          </div>
          {searchResult && (
            <div
              className="space-y-3"
              aria-label="Knowledge Base search results"
            >
              <p className="text-sm text-muted-foreground">
                {searchResult.status} · {searchResult.items.length} relevant
                chunks · {searchResult.retrieval_version}
              </p>
              {searchResult.items.map((match) => (
                <div
                  key={match.chunk_id}
                  className="rounded-md border p-3 text-sm"
                >
                  <div className="flex justify-between gap-3">
                    <strong>{match.filename}</strong>
                    <Badge variant="secondary">
                      Deterministic {match.score.toFixed(1)}
                      {match.semantic_score != null ? ` · Semantic ${match.semantic_score.toFixed(3)}` : ""}
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {match.heading_path.join(" › ") || "Unsectioned text"} ·
                    lines {match.source_start_line}–{match.source_end_line}
                  </p>
                  <p className="mt-2 whitespace-pre-wrap">{match.text}</p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    Matched by{" "}
                    {match.matched_by
                      .map((reason) => String(reason.method))
                      .join(", ")}
                  </p>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle>Files</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              {total} stored {total === 1 ? "file" : "files"}
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            disabled={loading}
            onClick={() => void load()}
          >
            <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </CardHeader>
        <CardContent>
          {loading && documents.length === 0 ? (
            <div className="flex h-32 items-center justify-center gap-2 text-muted-foreground">
              <Loader2 className="size-5 animate-spin" /> Loading files…
            </div>
          ) : documents.length === 0 ? (
            <div className="py-12 text-center text-sm text-muted-foreground">
              No Knowledge Base files have been uploaded.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Filename</TableHead>
                  <TableHead>Format</TableHead>
                  <TableHead>Size</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Uploader</TableHead>
                  <TableHead>Uploaded</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.map((document) => (
                  <TableRow key={document.document_id}>
                    <TableCell className="max-w-72 truncate font-medium">
                      {document.original_filename}
                    </TableCell>
                    <TableCell className="uppercase">
                      {document.file_format}
                    </TableCell>
                    <TableCell>{formatBytes(document.size_bytes)}</TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          document.status === "FAILED"
                            ? "destructive"
                            : document.status === "INDEXED"
                              ? "success"
                              : "secondary"
                        }
                      >
                        {document.processing_supported
                          ? document.status.toLowerCase()
                          : "legacy stored only"}
                      </Badge>
                      {document.processing_error?.detail && (
                        <p className="mt-1 text-xs text-destructive">
                          {document.processing_error.detail}
                        </p>
                      )}
                      <p className="mt-1 text-xs text-muted-foreground">
                        Semantic: {document.semantic_index?.status.toLowerCase() ?? "not indexed"}
                        {document.semantic_index?.error ? ` · ${document.semantic_index.error}` : ""}
                      </p>
                    </TableCell>
                    <TableCell>{document.uploaded_by.email}</TableCell>
                    <TableCell>
                      {formatLocaleDateTime(document.uploaded_at)}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-2">
                        {document.status === "INDEXED" && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => void inspect(document)}
                          >
                            <Eye className="size-4" /> {document.chunk_count}{" "}
                            chunks
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={downloading === document.document_id}
                          onClick={() => void download(document)}
                        >
                          {downloading === document.document_id ? (
                            <Loader2 className="size-4 animate-spin" />
                          ) : (
                            <Download className="size-4" />
                          )}
                          Download
                        </Button>
                        {canWrite &&
                          (document.processing_supported &&
                          (document.status === "FAILED" ||
                            document.status === "INDEXED") ? (
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={reprocessing === document.document_id}
                              onClick={() => void reprocess(document)}
                            >
                              {reprocessing === document.document_id ? (
                                <Loader2 className="size-4 animate-spin" />
                              ) : (
                                <RefreshCw className="size-4" />
                              )}
                              Reprocess
                            </Button>
                          ) : null)}
                        {canWrite && (
                          <Button
                            size="sm"
                            variant="destructive"
                            disabled={deleting === document.document_id}
                            onClick={() => void remove(document)}
                          >
                            {deleting === document.document_id ? (
                              <Loader2 className="size-4 animate-spin" />
                            ) : (
                              <Trash2 className="size-4" />
                            )}
                            Delete
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          {inspecting && (
            <div
              className="mt-4 space-y-3 border-t pt-4"
              aria-label="Indexed chunks"
            >
              <h3 className="font-semibold">Indexed chunks</h3>
              {visibleChunks.map((chunk) => (
                <div
                  key={chunk.chunk_id}
                  className="rounded-md border p-3 text-sm"
                >
                  <p className="text-xs text-muted-foreground">
                    #{chunk.chunk_index + 1} ·{" "}
                    {chunk.heading_path.join(" › ") || "Unsectioned text"} ·
                    lines {chunk.source_start_line}–{chunk.source_end_line}
                  </p>
                  <p className="mt-2 whitespace-pre-wrap">{chunk.text}</p>
                </div>
              ))}
            </div>
          )}

          {total > PAGE_SIZE && (
            <div className="mt-4 flex items-center justify-between border-t pt-4 text-sm">
              <span className="text-muted-foreground">
                Showing {page * PAGE_SIZE + 1}–
                {Math.min((page + 1) * PAGE_SIZE, total)} of {total}
              </span>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={page === 0}
                  onClick={() => setPage((value) => Math.max(0, value - 1))}
                >
                  Previous
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={(page + 1) * PAGE_SIZE >= total}
                  onClick={() => setPage((value) => value + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
