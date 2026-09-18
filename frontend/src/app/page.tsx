"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth, getPostLoginRoute } from "@/lib/auth";

export default function Home() {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isLoading) return;
    if (!user) {
      router.replace("/login");
    } else {
      // Restored sessions get the onboarding gate too: a user who closed the
      // tab on the tour without dismissing it never returns via /login.
      router.replace(getPostLoginRoute(user));
    }
  }, [user, isLoading, router]);

  return null;
}
