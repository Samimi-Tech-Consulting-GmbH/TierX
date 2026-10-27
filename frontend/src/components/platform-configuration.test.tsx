import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import InstallationPage from "@/app/installation/page";
import PlatformSettingsPage from "@/app/dashboard/admin/settings/platform/page";
import { PlatformConfigurationForm, initialPlatformValues } from "./platform-configuration-form";

const mocks = vi.hoisted(() => {
  const replace = vi.fn();
  return { replace, router: { replace }, role: "PLATFORM_ADMIN" };
});
vi.mock("next/navigation", () => ({ useRouter: () => mocks.router }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { role: mocks.role } }), readToken: () => "synthetic-auth-token" }));

function response(data: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } }));
}
const pending = { installed: false, wizard_available: true, defaults: initialPlatformValues, locked_fields: [] };
const configuration = { values: initialPlatformValues, locked_fields: [], revision: 1, services: [] };

beforeEach(() => { mocks.role = "PLATFORM_ADMIN"; mocks.replace.mockClear(); localStorage.clear(); sessionStorage.clear(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("first-run installation", () => {
  it("hides completed/disabled setup", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response({ installed: true, wizard_available: false })));
    render(<InstallationPage />);
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByLabelText("Installation token")).not.toBeInTheDocument();
  });

  it("reviews before completion, sends token only in header, and never stores secrets", async () => {
    const fetcher = vi.fn((url: string) => response(url.endsWith("/status") ? pending : { installed: true }));
    vi.stubGlobal("fetch", fetcher);
    render(<InstallationPage />);
    await screen.findByLabelText("Installation token");
    fireEvent.change(screen.getByLabelText("Installation token"), { target: { value: "synthetic-setup-token" } });
    fireEvent.change(screen.getByLabelText("Platform admin email"), { target: { value: "admin@example.com" } });
    fireEvent.change(screen.getByLabelText("Platform admin password"), { target: { value: "synthetic-password-only" } });
    fireEvent.click(screen.getByRole("button", { name: "Review installation" }));
    expect(screen.getByText("Administrator: admin@example.com")).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Complete installation" }));
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/login"));
    const call = fetcher.mock.calls.at(-1) as unknown as [string, RequestInit];
    expect(call[0]).toBe("/api/v1/installation/complete");
    expect(call[1].headers).toMatchObject({ "X-TierX-Installation-Token": "synthetic-setup-token" });
    expect(call[1].body).not.toContain("synthetic-setup-token");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("shows safe connection errors without completing installation", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => response(url.endsWith("/status") ? pending : { detail: "Model unavailable" }, url.endsWith("/status") ? 200 : 422)));
    render(<InstallationPage />);
    await screen.findByLabelText("Installation token");
    fireEvent.click(screen.getByRole("button", { name: "Test Ollama connection" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Model unavailable");
    expect(mocks.replace).not.toHaveBeenCalled();
  });
});

describe("platform settings", () => {
  it("rejects tenant users in the UI without loading platform configuration", () => {
    mocks.role = "TENANT_ADMIN";
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    render(<PlatformSettingsPage />);
    expect(screen.getByText("Platform administrator access required.")).toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("locks environment overrides and saves with expected revision", async () => {
    const fetcher = vi.fn(() => response({ ...configuration, locked_fields: ["ollama_model"] }));
    vi.stubGlobal("fetch", fetcher);
    render(<PlatformSettingsPage />);
    expect(await screen.findByLabelText("Ollama model (managed by environment)")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Public TierX URL"), { target: { value: "https://tierx.example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    const call = fetcher.mock.calls[1] as unknown as [string, RequestInit];
    expect(call[1].method).toBe("PUT");
    expect(JSON.parse(call[1].body as string)).toMatchObject({ expected_revision: 1, values: { public_url: "https://tierx.example.com" } });
  });

  it("enabling analysis selects correlation in the same update", () => {
    const changed = vi.fn();
    render(<PlatformConfigurationForm values={initialPlatformValues} locked={[]} onChange={changed} />);
    fireEvent.click(screen.getByLabelText("Enable analysis"));
    expect(changed).toHaveBeenCalledWith(expect.objectContaining({ llm_analysis_enabled: true, correlation_enabled: true }));
  });
});
