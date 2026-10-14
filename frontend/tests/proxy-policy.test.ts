import { describe, expect, it } from "vitest";
import { isAllowedRequest } from "@/lib/proxy-policy";

const path = (value: string) => value.split("/").filter(Boolean);

describe("allowlist do proxy /api/backend", () => {
  it.each([
    ["GET", "metrics"],
    ["POST", "upload"],
    ["GET", "executions"],
    ["GET", "executions/abc123"],
    ["GET", "students"],
    ["POST", "students"],
    ["GET", "students/me"],
    ["GET", "students/under-review"],
    ["PUT", "students/0d2ccf31-8ed0-43a4-8554-18813dbdd001"],
    ["DELETE", "students/0d2ccf31-8ed0-43a4-8554-18813dbdd001"],
    ["GET", "reviews"],
    ["POST", "reviews"],
    ["GET", "reviews/me"],
    ["PATCH", "reviews/12/decision"],
    ["DELETE", "reviews/12"],
    ["GET", "terms"],
    ["POST", "terms/3/close"],
    ["GET", "terms/3/notifications"],
    ["GET", "notifications/me"],
    ["POST", "notifications/me/read-all"],
    ["PATCH", "notifications/7/read"],
  ])("permite %s /%s", (method, route) => {
    expect(isAllowedRequest(path(route), method)).toBe(true);
  });

  it.each([
    ["GET", "upload", "método errado para o upload"],
    ["DELETE", "metrics", "métricas são só leitura"],
    ["POST", "executions", "histórico é só leitura"],
    ["GET", "executions/a/b", "profundidade extra"],
    ["DELETE", "students/me", "aluno não apaga o próprio registo"],
    ["PUT", "students/me", "aluno não edita as próprias notas"],
    ["PATCH", "reviews/abc/decision", "ID de revisão não numérico"],
    ["DELETE", "reviews/me", "rota 'me' não é um ID"],
    ["PUT", "terms/x", "ID de período não numérico"],
    ["GET", "auth/login", "auth tem rotas próprias, fora do proxy"],
    ["GET", "docs", "documentação da API não é exposta"],
    ["GET", "openapi.json", "schema da API não é exposto"],
    ["GET", "", "raiz"],
    ["GET", "../metrics", "path traversal"],
  ])("bloqueia %s /%s (%s)", (method, route, reason) => {
    expect(isAllowedRequest(path(route), method), reason).toBe(false);
  });
});
