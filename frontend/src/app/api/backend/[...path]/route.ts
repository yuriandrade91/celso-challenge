import { NextRequest, NextResponse } from "next/server";
import {
  ACCESS_TOKEN_COOKIE,
  clearSessionCookies,
  hasSameOrigin,
  REFRESH_TOKEN_COOKIE,
  refreshBackendTokens,
  setSessionCookies,
  type SessionTokens,
  unauthorizedResponse,
} from "@/lib/auth-session";
import { backendEndpoint } from "@/lib/backend";
import { isAllowedRequest } from "@/lib/proxy-policy";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

async function forward(
  request: NextRequest,
  path: string[],
  accessToken: string,
  body?: ArrayBuffer,
): Promise<Response> {
  const encodedPath = path.map((segment) => encodeURIComponent(segment)).join("/");
  const backendPath =
    path.length === 1 && path[0] === "students"
      ? "/students/"
      : path.length === 1 && path[0] === "reviews"
        ? "/reviews/"
      : `/${encodedPath}`;
  const url = `${backendEndpoint(backendPath)}${request.nextUrl.search}`;
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);
  const requestId = request.headers.get("x-request-id");
  if (requestId) headers.set("X-Request-ID", requestId);
  headers.set("Authorization", `Bearer ${accessToken}`);

  return fetch(url, {
    method: request.method,
    headers,
    body,
    cache: "no-store",
  });
}

async function handle(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const method = request.method.toUpperCase();
  if (!isAllowedRequest(path, method)) {
    return NextResponse.json(
      { errors: [{ message: "Endpoint ou método não disponível." }] },
      { status: 404 },
    );
  }
  if (
    method !== "GET" &&
    method !== "HEAD" &&
    !hasSameOrigin(request)
  ) {
    return NextResponse.json(
      { errors: [{ message: "Origem da solicitação inválida." }] },
      { status: 403 },
    );
  }

  let body: ArrayBuffer | undefined;
  if (method !== "GET" && method !== "HEAD") {
    try {
      body = await request.arrayBuffer();
    } catch {
      return NextResponse.json(
        { errors: [{ message: "Não foi possível ler o corpo da solicitação." }] },
        { status: 400 },
      );
    }
  }

  let accessToken = request.cookies.get(ACCESS_TOKEN_COOKIE)?.value;
  let refreshToken = request.cookies.get(REFRESH_TOKEN_COOKIE)?.value;
  let rotatedTokens: SessionTokens | null = null;

  if (!accessToken && refreshToken) {
    try {
      rotatedTokens = await refreshBackendTokens(refreshToken);
    } catch {
      return NextResponse.json(
        { errors: [{ message: "Não foi possível contactar o backend." }] },
        { status: 502, headers: { "Cache-Control": "no-store" } },
      );
    }
    accessToken = rotatedTokens?.accessToken;
    refreshToken = rotatedTokens?.refreshToken;
  }
  if (!accessToken) {
    const response = unauthorizedResponse();
    clearSessionCookies(response);
    return response;
  }

  let upstream: Response;
  try {
    upstream = await forward(request, path, accessToken, body);
  } catch {
    return NextResponse.json(
      { errors: [{ message: "Não foi possível contactar o backend." }] },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }

  if (upstream.status === 401 && refreshToken && !rotatedTokens) {
    try {
      rotatedTokens = await refreshBackendTokens(refreshToken);
    } catch {
      return NextResponse.json(
        { errors: [{ message: "Não foi possível contactar o backend." }] },
        { status: 502, headers: { "Cache-Control": "no-store" } },
      );
    }
    if (rotatedTokens) {
      try {
        upstream = await forward(request, path, rotatedTokens.accessToken, body);
      } catch {
        return NextResponse.json(
          { errors: [{ message: "Não foi possível contactar o backend." }] },
          { status: 502, headers: { "Cache-Control": "no-store" } },
        );
      }
    }
  }

  const response = new NextResponse(upstream.body, {
    status: upstream.status,
    headers: {
      "Cache-Control": "no-store",
      ...(upstream.headers.get("content-type")
        ? { "Content-Type": upstream.headers.get("content-type")! }
        : {}),
    },
  });
  if (upstream.status === 401) {
    clearSessionCookies(response);
  } else if (rotatedTokens) {
    setSessionCookies(response, rotatedTokens);
  }
  return response;
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
