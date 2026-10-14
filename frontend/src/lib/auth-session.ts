import { createHash } from "node:crypto";
import { NextResponse } from "next/server";
import type { AuthUser, DemoProfile } from "@/lib/auth-types";
import { backendEndpoint } from "@/lib/backend";

export const ACCESS_TOKEN_COOKIE =
  process.env.NODE_ENV === "production"
    ? "__Host-educa_access_token"
    : "educa_access_token";
export const REFRESH_TOKEN_COOKIE =
  process.env.NODE_ENV === "production"
    ? "__Host-educa_refresh_token"
    : "educa_refresh_token";

export type SessionTokens = {
  accessToken: string;
  refreshToken: string;
  tokenType: string;
  expiresIn: number;
  user: AuthUser;
};

type ApiEnvelope<T> = {
  success: boolean;
  data: T;
  errors?: { message: string }[] | null;
};

export class BackendAuthError extends Error {
  constructor(
    message: string,
    readonly statusCode: number,
  ) {
    super(message);
  }
}

const refreshRequests = new Map<string, Promise<SessionTokens | null>>();

function isAuthUser(value: unknown): value is AuthUser {
  if (typeof value !== "object" || value === null) return false;
  const user = value as Record<string, unknown>;
  return (
    typeof user.email === "string" &&
    (user.role === "teacher" || user.role === "student") &&
    (typeof user.studentId === "string" || user.studentId === null)
  );
}

function isSessionTokens(value: unknown): value is SessionTokens {
  if (typeof value !== "object" || value === null) return false;
  const tokens = value as Record<string, unknown>;
  return (
    typeof tokens.accessToken === "string" &&
    typeof tokens.refreshToken === "string" &&
    typeof tokens.tokenType === "string" &&
    typeof tokens.expiresIn === "number" &&
    isAuthUser(tokens.user)
  );
}

async function parseEnvelope<T>(
  response: Response,
): Promise<ApiEnvelope<T>> {
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const errors =
      typeof body === "object" && body !== null && "errors" in body
        ? body.errors
        : null;
    const message =
      Array.isArray(errors) &&
      errors
        .map((error) =>
          typeof error === "object" &&
          error !== null &&
          "message" in error &&
          typeof error.message === "string"
            ? error.message
            : "",
        )
        .filter(Boolean)
        .join(" ");
    throw new BackendAuthError(
      message || `O backend respondeu com HTTP ${response.status}.`,
      response.status,
    );
  }

  if (
    typeof body !== "object" ||
    body === null ||
    !("success" in body) ||
    !("data" in body)
  ) {
    throw new Error("O backend devolveu uma resposta de autenticação inválida.");
  }
  const envelope = body as ApiEnvelope<T>;
  if (envelope.success !== true) {
    throw new Error("O backend não autorizou a autenticação.");
  }
  return envelope;
}

export async function requestBackendTokens(
  path: "/auth/login" | "/auth/refresh",
  payload:
    | { profile: DemoProfile }
    | { refreshToken: string },
): Promise<SessionTokens> {
  const response = await fetch(backendEndpoint(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  const { data } = await parseEnvelope<unknown>(response);
  if (!isSessionTokens(data)) {
    throw new Error("O backend devolveu tokens num formato inválido.");
  }
  return data;
}

export async function refreshBackendTokens(
  refreshToken: string,
): Promise<SessionTokens | null> {
  const key = createHash("sha256").update(refreshToken).digest("hex");
  let refreshRequest = refreshRequests.get(key);
  if (!refreshRequest) {
    refreshRequest = requestBackendTokens("/auth/refresh", { refreshToken })
      .catch((error: unknown) => {
        if (
          error instanceof BackendAuthError &&
          (error.statusCode === 401 || error.statusCode === 403)
        ) {
          return null;
        }
        throw error;
      })
      .finally(() => refreshRequests.delete(key));
    refreshRequests.set(key, refreshRequest);
  }
  return refreshRequest;
}

export async function getBackendUser(
  accessToken: string,
): Promise<AuthUser | null> {
  const response = await fetch(backendEndpoint("/auth/me"), {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  if (response.status === 401) return null;
  const { data } = await parseEnvelope<unknown>(response);
  if (!isAuthUser(data)) {
    throw new Error("O backend devolveu um utilizador num formato inválido.");
  }
  return data;
}

export function setSessionCookies(
  response: NextResponse,
  tokens: SessionTokens,
): void {
  const options = {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
  };
  response.cookies.set(ACCESS_TOKEN_COOKIE, tokens.accessToken, options);
  response.cookies.set(REFRESH_TOKEN_COOKIE, tokens.refreshToken, options);
}

export function clearSessionCookies(response: NextResponse): void {
  const options = {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge: 0,
  };
  response.cookies.set(ACCESS_TOKEN_COOKIE, "", options);
  response.cookies.set(REFRESH_TOKEN_COOKIE, "", options);
}

export function hasSameOrigin(request: Request): boolean {
  return request.headers.get("origin") === new URL(request.url).origin;
}

export function unauthorizedResponse(): NextResponse {
  return NextResponse.json(
    { errors: [{ message: "A sessão expirou. Inicie sessão novamente." }] },
    { status: 401, headers: { "Cache-Control": "no-store" } },
  );
}
