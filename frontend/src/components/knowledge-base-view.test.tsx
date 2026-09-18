import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  deleteKnowledgeBaseDocument,
  listKnowledgeBaseDocuments,
  uploadKnowledgeBaseDocument,
  searchKnowledgeBase,
} from "@/lib/api";
import { UserRole } from "@/lib/types";
import { KnowledgeBaseView } from "./knowledge-base-view";

let role: UserRole = UserRole.TENANT_ADMIN;

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    user: {
      user_id: "user-1",
      email: "user@example.com",
      role,
      tenant_id: role === UserRole.PLATFORM_ADMIN ? null : "tenant-1",
    },
  }),
}));

vi.mock("@/lib/api", async () => {
  class ApiError extends Error {
    status = 422;
    detail: string;
    constructor(detail = "failed") {
      super(detail);
      this.detail = detail;
    }
  }
  return {
    ApiError,
    listKnowledgeBaseDocuments: vi.fn(),
    uploadKnowledgeBaseDocument: vi.fn(),
    downloadKnowledgeBaseDocument: vi.fn(),
    deleteKnowledgeBaseDocument: vi.fn(),
    listKnowledgeBaseChunks: vi
      .fn()
      .mockResolvedValue({ items: [], total: 0, skip: 0, limit: 200 }),
    reprocessKnowledgeBaseDocument: vi.fn(),
    searchKnowledgeBase: vi.fn(),
  };
});

const documentRecord = {
  document_id: "document-1",
  tenant_id: "tenant-1",
  original_filename: "response-plan.md",
  file_format: "md" as const,
  content_type: "text/markdown; charset=utf-8",
  size_bytes: 2048,
  sha256: "a".repeat(64),
  status: "INDEXED" as const,
  processing_supported: true,
  document_version: 1,
  chunk_count: 2,
  uploaded_by: { user_id: "admin-1", email: "admin@example.com" },
  uploaded_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-01T10:00:00Z",
};

function page(items = [documentRecord]) {
  return { items, total: items.length, skip: 0, limit: 25 };
}

describe("KnowledgeBaseView", () => {
  afterEach(cleanup);

  beforeEach(() => {
    role = UserRole.TENANT_ADMIN;
    vi.mocked(listKnowledgeBaseDocuments).mockReset();
    vi.mocked(listKnowledgeBaseDocuments).mockResolvedValue(page());
    vi.mocked(uploadKnowledgeBaseDocument).mockReset();
    vi.mocked(deleteKnowledgeBaseDocument).mockReset();
    vi.mocked(deleteKnowledgeBaseDocument).mockResolvedValue(undefined);
  });

  it("shows indexed files, uploader metadata, and the evidence warning", async () => {
    render(<KnowledgeBaseView tenantId="tenant-1" />);

    expect(await screen.findByText("response-plan.md")).toBeVisible();
    expect(screen.getByText("indexed")).toBeVisible();
    expect(screen.getByText("admin@example.com")).toBeVisible();
    expect(screen.getByText(/untrusted analysis evidence/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Choose files" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Delete" })).toBeVisible();
  });

  it("keeps successful sequential uploads when a later file fails", async () => {
    vi.mocked(uploadKnowledgeBaseDocument)
      .mockResolvedValueOnce(documentRecord)
      .mockRejectedValueOnce(new Error("server rejected file"));
    render(<KnowledgeBaseView tenantId="tenant-1" />);
    await screen.findByText("response-plan.md");

    const first = new File(["first"], "first.txt", { type: "text/plain" });
    const second = new File(["second"], "second.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("Choose Knowledge Base files"), {
      target: { files: [first, second] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Upload selected" }));

    await waitFor(() =>
      expect(uploadKnowledgeBaseDocument).toHaveBeenCalledTimes(2),
    );
    expect(vi.mocked(uploadKnowledgeBaseDocument).mock.calls[0][1]).toBe(first);
    expect(vi.mocked(uploadKnowledgeBaseDocument).mock.calls[1][1]).toBe(
      second,
    );
    expect(await screen.findByText("uploaded")).toBeVisible();
    expect(await screen.findByText("failed")).toBeVisible();
    expect(listKnowledgeBaseDocuments).toHaveBeenCalledTimes(2);
  });

  it("rejects a selection containing more than ten files", async () => {
    render(<KnowledgeBaseView tenantId="tenant-1" />);
    await screen.findByText("response-plan.md");
    const files = Array.from(
      { length: 11 },
      (_, index) => new File(["x"], `file-${index}.txt`),
    );

    fireEvent.change(screen.getByLabelText("Choose Knowledge Base files"), {
      target: { files },
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Select at most 10 files",
    );
    expect(
      screen.queryByRole("button", { name: "Upload selected" }),
    ).not.toBeInTheDocument();
  });

  it("lets operators list and download but hides upload and delete", async () => {
    role = UserRole.TENANT_OPERATOR;
    render(<KnowledgeBaseView tenantId="tenant-1" />);

    expect(await screen.findByText("response-plan.md")).toBeVisible();
    expect(screen.getByRole("button", { name: "Download" })).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Choose files" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();
  });

  it("requires confirmation before deleting and reloads the list", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<KnowledgeBaseView tenantId="tenant-1" />);
    await screen.findByText("response-plan.md");

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(deleteKnowledgeBaseDocument).toHaveBeenCalledWith(
        "tenant-1",
        "document-1",
      ),
    );
    expect(confirm).toHaveBeenCalled();
    expect(listKnowledgeBaseDocuments).toHaveBeenCalledTimes(2);
    confirm.mockRestore();
  });

  it("requests hybrid retrieval and explains deterministic fallback", async () => {
    vi.mocked(searchKnowledgeBase).mockResolvedValue({query_sha256: "x", retrieval_version: "kb-hybrid-v1",
      status: "NO_MATCH", items: [], degraded: true, semantic_status: "UNAVAILABLE"});
    render(<KnowledgeBaseView tenantId="tenant-1" />);
    await screen.findByText("response-plan.md");
    fireEvent.change(screen.getByLabelText("Retrieval mode"), {target: {value: "hybrid"}});
    fireEvent.change(screen.getByPlaceholderText(/Try EXAMPLE-DB01/), {target: {value: "EXAMPLE-DB01"}});
    fireEvent.click(screen.getByRole("button", {name: "Search"}));
    await screen.findByText(/Showing deterministic evidence only/);
    expect(searchKnowledgeBase).toHaveBeenCalledWith("tenant-1", "EXAMPLE-DB01", 5, "hybrid");
  });

  it("shows deterministic manual search matches", async () => {
    vi.mocked(searchKnowledgeBase).mockResolvedValue({
      query_sha256: "b".repeat(64),
      retrieval_version: "kb-retrieval-v1",
      status: "OK",
      items: [
        {
          chunk_id: "chunk-1",
          document_id: "document-1",
          document_version: 1,
          chunk_index: 0,
          source_start_line: 1,
          source_end_line: 3,
          heading_path: ["Production"],
          text: "EXAMPLE-DB01 is in the production network.",
          text_sha256: "c".repeat(64),
          parser_version: "commonmark-v1",
          index_version: "lexical-v1",
          filename: "response-plan.md",
          score: 130,
          matched_by: [{ method: "EXACT_ENTITY" }],
        },
      ],
    });
    render(<KnowledgeBaseView tenantId="tenant-1" />);
    await screen.findByText("response-plan.md");
    fireEvent.change(screen.getByPlaceholderText(/Try EXAMPLE-DB01/), {
      target: { value: "EXAMPLE-DB01" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(
      await screen.findByText("EXAMPLE-DB01 is in the production network."),
    ).toBeVisible();
    expect(screen.getByText(/EXACT_ENTITY/)).toBeVisible();
  });
});
