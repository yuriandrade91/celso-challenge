"use client";

import { Toast } from "@heroui/react";

export default function NotificationCenter() {
  return (
    <Toast.Provider
      placement="top end"
      maxVisibleToasts={4}
      width="min(460px, calc(100vw - 32px))"
    />
  );
}
