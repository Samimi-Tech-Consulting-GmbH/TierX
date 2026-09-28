"use client";

import { useState, useEffect } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { Eye, EyeOff, TriangleAlert } from "lucide-react";
import { useAuth, getPostLoginRoute } from "@/lib/auth";
import { TierXLogo } from "@/components/tierx-logo";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function notProvisioned(message: string) {
  toast.info(message);
}

const LOGIN_ERRORS: Record<string, string> = {
  "Invalid email or password": "E-Mail-Adresse oder Passwort ist ungültig.",
};

function translateLoginError(err: unknown): string {
  const detail = err instanceof Error ? err.message : "";
  return LOGIN_ERRORS[detail] ?? "Anmeldung fehlgeschlagen. Bitte erneut versuchen.";
}

export default function LoginPage() {
  const { login, user } = useAuth();
  const router = useRouter();

  const [remember, setRemember] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (user) router.replace(getPostLoginRoute(user));
  }, [user, router]);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    // Read the displayed values, including autofill without React change events.
    const fields = new FormData(e.currentTarget);
    const email = String(fields.get("email") ?? "");
    const password = String(fields.get("password") ?? "");
    setError("");
    setSubmitting(true);
    try {
      const loggedIn = await login(email, password, remember);
      router.push(getPostLoginRoute(loggedIn));
    } catch (err) {
      setError(translateLoginError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div lang="de" className="dark brand-dark grid min-h-screen w-full bg-background text-foreground lg:grid-cols-2">
      {/* Artwork panel — 720x900 half of the 1440 design frame */}
      <div className="relative hidden overflow-hidden bg-black lg:block">
        <Image
          src="/login-hero.png"
          alt=""
          fill
          priority
          sizes="50vw"
          className="object-cover"
        />
      </div>

      {/* Form panel */}
      <div className="flex items-center justify-center px-6 py-16">
        <div className="w-full max-w-[336px]">
          <div className="flex items-center justify-center gap-3">
            <TierXLogo className="size-9 text-primary" />
            <span className="text-3xl font-bold tracking-tight">TierX</span>
          </div>

          <h1 className="mt-[51px] text-center text-2xl font-bold">
            Willkommen zurück
          </h1>
          <p className="mt-4 text-center text-base text-muted-foreground">
            Melden Sie sich bei Ihrem Konto an
          </p>

          <form id="login-form" method="post" onSubmit={handleSubmit} className="mt-10">
            {error && (
              <div
                role="alert"
                className="mb-6 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-sm text-destructive"
              >
                <TriangleAlert className="mt-0.5 size-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <Label htmlFor="email" className="text-sm font-normal text-[#d4d4d4]">
              Benutzername
            </Label>
            <Input
              id="email"
              name="email"
              type="email"
              placeholder="Geben Sie Ihren Benutzernamen ein"
              className="mt-3 h-[50px] bg-white/5 px-4 text-sm"
              required
              autoFocus
              autoComplete="username"
            />

            <Label
              htmlFor="password"
              className="mt-6 text-sm font-normal text-[#d4d4d4]"
            >
              Passwort
            </Label>
            <div className="relative mt-3">
              <Input
                id="password"
                name="password"
                type={showPassword ? "text" : "password"}
                placeholder="Geben Sie Ihr Passwort ein"
                className="h-[50px] bg-white/5 px-4 pr-11 text-sm"
                required
                autoComplete="current-password"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-4 top-1/2 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground"
                aria-label={showPassword ? "Passwort verbergen" : "Passwort anzeigen"}
                tabIndex={-1}
              >
                {showPassword ? (
                  <EyeOff className="size-4" />
                ) : (
                  <Eye className="size-4" />
                )}
              </button>
            </div>

            <div className="mt-6 flex items-center justify-between gap-3">
              <Label
                htmlFor="remember"
                className="gap-2 text-sm font-normal text-[#d4d4d4]"
              >
                <Checkbox
                  id="remember"
                  checked={remember}
                  onCheckedChange={(value) => setRemember(Boolean(value))}
                />
                Angemeldet bleiben
              </Label>
              <button
                type="button"
                onClick={() =>
                  notProvisioned(
                    "Passwörter werden von Ihrer Plattform-Administration zurückgesetzt.",
                  )
                }
                className="text-sm text-primary transition-colors hover:text-primary/80"
              >
                Passwort vergessen?
              </button>
            </div>

            <Button
              type="submit"
              className="mt-6 h-[50px] w-full rounded-md text-base"
              disabled={submitting}
            >
              {submitting ? (
                <>
                  <div className="size-4 animate-spin rounded-full border-2 border-primary-foreground border-t-transparent" />
                  Anmeldung läuft...
                </>
              ) : (
                "Anmelden"
              )}
            </Button>
          </form>

          <p className="mt-10 text-center text-base text-muted-foreground">
            Noch kein Konto?{" "}
            <button
              type="button"
              onClick={() =>
                notProvisioned(
                  "Konten werden von Ihrer Plattform- oder Mandanten-Administration angelegt.",
                )
              }
              className="text-primary transition-colors hover:text-primary/80"
            >
              Jetzt registrieren
            </button>
          </p>

          <div className="mt-14 flex items-center justify-center gap-4 text-xs text-[#737373]">
            <span>Datenschutz</span>
            <span aria-hidden="true" className="text-base text-[#525252]">
              •
            </span>
            <span>Impressum</span>
            <span aria-hidden="true" className="text-base text-[#525252]">
              •
            </span>
            <Link href="/legal/source" className="underline">AGPL-Quellcode</Link>
          </div>
        </div>
      </div>
    </div>
  );
}
