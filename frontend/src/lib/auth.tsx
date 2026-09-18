"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import {
  STORAGE_KEYS,
  LEGACY_STORAGE_KEYS,
  clearCompatibleStorage,
  hasSeenOnboarding,
  readCompatibleStorage,
  writeCompatibleStorage,
} from "./storage";

export interface AuthUser {
  user_id: string;
  email: string;
  role: string;
  tenant_id: string | null;
  is_active: boolean;
}

interface AuthContextType {
  user: AuthUser | null;
  token: string | null;
  isLoading: boolean;
  login: (
    email: string,
    password: string,
    remember?: boolean,
  ) => Promise<AuthUser>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

/** Default landing route after login / auth redirects. */
export function getHomeRoute(user: Pick<AuthUser, "role" | "tenant_id">): string {
  if (user.role === "PLATFORM_ADMIN") return "/dashboard/admin";
  if (user.tenant_id) return `/dashboard/${user.tenant_id}`;
  return "/login";
}

export function getPostLoginRoute(
  user: Pick<AuthUser, "role" | "tenant_id">,
): string {
  return hasSeenOnboarding() ? getHomeRoute(user) : "/onboarding";
}

const TOKEN_KEY = STORAGE_KEYS.TOKEN;
const LEGACY_TOKEN_KEY = LEGACY_STORAGE_KEYS.TOKEN;
const API_BASE =
  process.env.NEXT_PUBLIC_TIERX_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "";

/**
 * "Remember me" picks the storage: localStorage survives a browser restart,
 * sessionStorage dies with the tab. Readers must check both.
 */
export function readToken(): string | null {
  if (typeof window === "undefined") return null;
  return (
    readCompatibleStorage(localStorage, TOKEN_KEY, LEGACY_TOKEN_KEY) ??
    readCompatibleStorage(sessionStorage, TOKEN_KEY, LEGACY_TOKEN_KEY)
  );
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  clearCompatibleStorage(localStorage, TOKEN_KEY, LEGACY_TOKEN_KEY);
  clearCompatibleStorage(sessionStorage, TOKEN_KEY, LEGACY_TOKEN_KEY);
}

function writeToken(accessToken: string, remember: boolean): void {
  clearToken();
  writeCompatibleStorage(
    remember ? localStorage : sessionStorage,
    TOKEN_KEY,
    LEGACY_TOKEN_KEY,
    accessToken,
  );
}

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

async function fetchMe(accessToken: string): Promise<AuthUser> {
  const res = await fetch(`${API_BASE}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) throw new Error("Session expired");
  return res.json();
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const stored = readToken();
    if (!stored) {
      setIsLoading(false);
      return;
    }
    setToken(stored);
    fetchMe(stored)
      .then((u) => setUser(u))
      .catch(() => clearToken())
      .finally(() => setIsLoading(false));
  }, []);

  const login = useCallback(
    async (
      email: string,
      password: string,
      remember = true,
    ): Promise<AuthUser> => {
      const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: "Login failed" }));
        throw new Error(body.detail ?? "Login failed");
      }
      const { access_token } = await res.json();
      writeToken(access_token, remember);
      setToken(access_token);
      const me = await fetchMe(access_token);
      setUser(me);
      return me;
    },
    [],
  );

  const logout = useCallback(() => {
    clearToken();
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
