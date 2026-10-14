import { NextRequest, NextResponse } from "next/server";
import {
  BackendAuthError,
  requestBackendTokens,
  setSessionCookies,
} from "@/lib/auth-session";
import type { DemoProfile } from "@/lib/auth-types";

function isDemoProfile(value: unknown): value is DemoProfile {
  return (
    typeof value === "string" &&
    (value === "professor" || value === "aluno_1" || value === "aluno_2")
  );
}

export async function POST(request: NextRequest) {
  if (request.headers.get("origin") !== request.nextUrl.origin) {
    return NextResponse.json(
      { errors: [{ message: "Origem da solicitação inválida." }] },
      { status: 403 },
    );
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { errors: [{ message: "Dados de autenticação inválidos." }] },
      { status: 400 },
    );
  }
  if (
    typeof body !== "object" ||
    body === null ||
    !("profile" in body) ||
    Object.keys(body).length !== 1 ||
    !isDemoProfile(body.profile)
  ) {
    return NextResponse.json(
      { errors: [{ message: "Selecione um perfil válido." }] },
      { status: 400 },
    );
  }

  try {
    const tokens = await requestBackendTokens("/auth/login", {
      profile: body.profile,
    });
    const response = NextResponse.json(
      { user: tokens.user },
      { headers: { "Cache-Control": "no-store" } },
    );
    setSessionCookies(response, tokens);
    return response;
  } catch (error) {
    const statusCode =
      error instanceof BackendAuthError && error.statusCode < 500
        ? error.statusCode
        : 502;
    const message =
      error instanceof BackendAuthError && error.statusCode < 500
        ? error.message
        : "Não foi possível autenticar com o backend.";
    return NextResponse.json(
      { errors: [{ message }] },
      { status: statusCode, headers: { "Cache-Control": "no-store" } },
    );
  }
}
