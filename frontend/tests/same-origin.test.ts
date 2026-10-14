import { describe, expect, it } from "vitest";
import { hasSameOrigin } from "@/lib/auth-session";

const request = (origin?: string) =>
  new Request("http://localhost:3000/api/backend/upload", {
    method: "POST",
    headers: origin ? { origin } : {},
  });

describe("proteção CSRF por origem", () => {
  it("aceita pedidos do próprio painel", () => {
    expect(hasSameOrigin(request("http://localhost:3000"))).toBe(true);
  });

  it.each([
    [undefined, "sem cabeçalho Origin"],
    ["http://evil.example", "outro site"],
    ["http://localhost:3001", "outra porta"],
    ["https://localhost:3000", "outro esquema"],
  ])("rejeita %s (%s)", (origin, reason) => {
    expect(hasSameOrigin(request(origin)), reason).toBe(false);
  });
});
