import { NextRequest, NextResponse } from "next/server";
import {
  clearSessionCookies,
  hasSameOrigin,
  REFRESH_TOKEN_COOKIE,
  refreshBackendTokens,
  setSessionCookies,
} from "@/lib/auth-session";

export async function POST(request: NextRequest) {
  if (!hasSameOrigin(request)) {
    return NextResponse.json(
      { errors: [{ message: "Origem da solicitação inválida." }] },
      { status: 403 },
    );
  }

  const refreshToken = request.cookies.get(REFRESH_TOKEN_COOKIE)?.value;
  if (!refreshToken) {
    const response = NextResponse.json(
      { errors: [{ message: "A sessão expirou. Inicie sessão novamente." }] },
      { status: 401, headers: { "Cache-Control": "no-store" } },
    );
    clearSessionCookies(response);
    return response;
  }

  let tokens;
  try {
    tokens = await refreshBackendTokens(refreshToken);
  } catch {
    return NextResponse.json(
      { errors: [{ message: "Não foi possível contactar o backend." }] },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
  if (!tokens) {
    const response = NextResponse.json(
      { errors: [{ message: "A sessão expirou. Inicie sessão novamente." }] },
      { status: 401, headers: { "Cache-Control": "no-store" } },
    );
    clearSessionCookies(response);
    return response;
  }

  const response = NextResponse.json(
    { success: true },
    { headers: { "Cache-Control": "no-store" } },
  );
  setSessionCookies(response, tokens);
  return response;
}
