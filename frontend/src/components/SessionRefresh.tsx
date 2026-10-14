"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Spinner } from "@heroui/react";
import { useRouter } from "next/navigation";
import { notifications } from "@/lib/notifications";

export default function SessionRefresh() {
  const router = useRouter();
  const started = useRef(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const response = await fetch("/api/auth/refresh", { method: "POST" });
      if (!response.ok && response.status !== 401) {
        const message = "Não foi possível contactar o servidor. Tente novamente.";
        setError(message);
        notifications.error(message);
        return;
      }
      router.refresh();
    } catch {
      const message = "Não foi possível validar a sessão. Tente novamente.";
      setError(message);
      notifications.error(message);
    }
  }, [router]);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void refresh();
  }, [refresh]);

  return (
    <main className="login-shell">
      <section className="login-card">
        <div className="loading-panel" role="status">
          <Spinner size="md" />
          <span>{error ?? "A validar a sessão…"}</span>
          {error && (
            <button type="button" className="primary-button" onClick={() => void refresh()}>
              Tentar novamente
            </button>
          )}
        </div>
      </section>
    </main>
  );
}
