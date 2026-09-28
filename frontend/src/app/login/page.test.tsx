import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LoginPage from "./page";

const { login, push } = vi.hoisted(() => ({ login: vi.fn(), push: vi.fn() }));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ login, user: null }),
  getPostLoginRoute: () => "/dashboard",
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));
vi.mock("next/image", () => ({ default: () => null }));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
beforeEach(() => {
  vi.stubGlobal("PointerEvent", MouseEvent);
  login.mockResolvedValue({});
});

describe("login password-manager support", () => {
  it("exposes stable credential names and standard autocomplete hints", () => {
    render(<LoginPage />);
    expect(screen.getByLabelText("Benutzername")).toHaveAttribute("name", "email");
    expect(screen.getByLabelText("Benutzername")).toHaveAttribute("autocomplete", "username");
    expect(screen.getByLabelText("Passwort")).toHaveAttribute("name", "password");
    expect(screen.getByLabelText("Passwort")).toHaveAttribute("autocomplete", "current-password");
    expect(screen.getByLabelText("Passwort").closest("form")).toHaveAttribute("method", "post");
  });

  it("submits DOM-filled credentials without requiring change events", async () => {
    render(<LoginPage />);
    const email = screen.getByLabelText("Benutzername") as HTMLInputElement;
    const password = screen.getByLabelText("Passwort") as HTMLInputElement;
    email.value = "person@example.com";
    password.value = " synthetic password with spaces ";
    fireEvent.click(screen.getByRole("button", { name: "Passwort anzeigen" }));
    expect(password).toHaveValue(" synthetic password with spaces ");
    fireEvent.submit(email.form!);
    await waitFor(() => expect(login).toHaveBeenCalledWith(
      "person@example.com", " synthetic password with spaces ", true,
    ));
    expect(push).toHaveBeenCalledWith("/dashboard");
  });

  it("still submits typed credentials and remembers the checkbox choice", async () => {
    render(<LoginPage />);
    const email = screen.getByLabelText("Benutzername") as HTMLInputElement;
    fireEvent.change(email, { target: { value: "person@example.com" } });
    fireEvent.change(screen.getByLabelText("Passwort"), { target: { value: "synthetic-only" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.submit(email.form!);
    await waitFor(() => expect(login).toHaveBeenCalledWith("person@example.com", "synthetic-only", false));
  });
});
