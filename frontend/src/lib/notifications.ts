"use client";

import { toast } from "@heroui/react";

function errorMessage(error: unknown, fallback: string): string {
  if (typeof error === "string" && error.trim()) return error;
  return error instanceof Error && error.message.trim()
    ? error.message
    : fallback;
}

export const notifications = {
  error(error: unknown, fallback = "Não foi possível concluir a operação.") {
    toast.danger(errorMessage(error, fallback), { timeout: 6000 });
  },

  warning(message: string, description?: string) {
    toast.warning(message, { description, timeout: 6000 });
  },

  success(message: string, description?: string) {
    toast.success(message, { description });
  },

  info(message: string, description?: string) {
    toast.info(message, { description });
  },
};
