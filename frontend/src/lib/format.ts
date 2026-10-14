export const percent = (value: number) => `${(value * 100).toFixed(1)}%`;

export const ms = (value: number) =>
  value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${value.toFixed(0)} ms`;

export const usd = (value: number, digits = 4) => `US$ ${value.toFixed(digits)}`;

export const time = (value: string) =>
  new Date(value).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
