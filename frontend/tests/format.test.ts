import { describe, expect, it } from "vitest";
import { ms, percent, usd } from "@/lib/format";

describe("formatadores do painel de métricas", () => {
  it("formata taxas como percentagem com uma casa", () => {
    expect(percent(0)).toBe("0.0%");
    expect(percent(0.5)).toBe("50.0%");
    expect(percent(0.12345)).toBe("12.3%");
  });

  it("mostra milissegundos abaixo de 1 s e segundos acima", () => {
    expect(ms(12.4)).toBe("12 ms");
    expect(ms(999)).toBe("999 ms");
    expect(ms(1000)).toBe("1.00 s");
    expect(ms(23636.31)).toBe("23.64 s");
  });

  it("formata custo em dólares com precisão configurável", () => {
    expect(usd(0.00017055)).toBe("US$ 0.0002");
    expect(usd(0.00017055, 6)).toBe("US$ 0.000171");
  });
});
