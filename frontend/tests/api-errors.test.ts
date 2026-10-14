import { describe, expect, it } from "vitest";
import { getErrorMessage } from "@/lib/backend";

describe("leitura do envelope de erro da API", () => {
  it("junta as mensagens de todos os erros", () => {
    const body = {
      success: false,
      errors: [
        { field: "email", code: "VALIDATION_ERROR", message: "Email inválido." },
        { field: null, code: "VALIDATION_ERROR", message: "Nota acima de 20." },
      ],
    };

    expect(getErrorMessage(body, 422)).toBe("Email inválido. Nota acima de 20.");
  });

  it("usa a mensagem do 429 do rate limit", () => {
    const body = {
      success: false,
      errors: [{ code: "TOO_MANY_REQUESTS", message: "Demasiados pedidos." }],
    };

    expect(getErrorMessage(body, 429)).toBe("Demasiados pedidos.");
  });

  it("cai para o status HTTP quando o corpo não é o envelope esperado", () => {
    expect(getErrorMessage(null, 502)).toBe("O backend respondeu com HTTP 502.");
    expect(getErrorMessage("<html>", 500)).toBe("O backend respondeu com HTTP 500.");
    expect(getErrorMessage({ errors: [] }, 503)).toBe("O backend respondeu com HTTP 503.");
  });
});
