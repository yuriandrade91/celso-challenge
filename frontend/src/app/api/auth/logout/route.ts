import { NextRequest, NextResponse } from "next/server";
import {
  clearSessionCookies,
  hasSameOrigin,
  REFRESH_TOKEN_COOKIE,
} from "@/lib/auth-session";
import { backendEndpoint } from "@/lib/backend";

export async function POST(request: NextRequest) {
  if (!hasSameOrigin(request)) {
    return NextResponse.json(
      { errors: [{ message: "Origem da solicitação inválida." }] },
      { status: 403 },
    );
  }

  const refreshToken = request.cookies.get(REFRESH_TOKEN_COOKIE)?.value;
  let status = 200;
  let message: string | null = null;
  if (refreshToken) {
    try {
      const response = await fetch(backendEndpoint("/auth/logout"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refreshToken }),
        cache: "no-store",
      });
      if (!response.ok) {
        status = 502;
        message = "Não foi possível invalidar a sessão no backend.";
      }
    } catch {
      status = 502;
      message = "Não foi possível contactar o backend para encerrar a sessão.";
    }
  }

  const response = NextResponse.json(
    message ? { errors: [{ message }] } : { success: true },
    { status, headers: { "Cache-Control": "no-store" } },
  );
  clearSessionCookies(response);
  return response;
}
