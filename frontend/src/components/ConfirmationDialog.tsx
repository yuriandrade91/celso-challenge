"use client";

import type { ReactNode } from "react";
import { ShieldCheck } from "lucide-react";
import { Button, Modal, useOverlayState } from "@heroui/react";

export default function ConfirmationDialog({
  title,
  description,
  confirmLabel,
  isPending,
  destructive = false,
  onCancel,
  onConfirm,
}: {
  title: string;
  description: ReactNode;
  confirmLabel: string;
  isPending: boolean;
  destructive?: boolean;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}) {
  const modalState = useOverlayState({
    isOpen: true,
    onOpenChange: (isOpen) => {
      if (!isOpen && !isPending) onCancel();
    },
  });

  return (
    <Modal.Root state={modalState}>
      <Modal.Backdrop
        className="confirmation-modal-backdrop"
        isDismissable={!isPending}
      >
        <Modal.Container
          className="confirmation-modal-container"
          placement="center"
          size="sm"
        >
          <Modal.Dialog className="confirmation-modal">
            <Modal.Header className="confirmation-modal-header">
              <Modal.Icon className="confirmation-dialog-icon">
                <ShieldCheck size={20} aria-hidden="true" />
              </Modal.Icon>
              <Modal.Heading className="confirmation-dialog-title">
                {title}
              </Modal.Heading>
            </Modal.Header>
            <Modal.Body className="confirmation-dialog-description">
              {description}
            </Modal.Body>
            <Modal.Footer className="confirmation-dialog-actions">
              <Button
                type="button"
                variant="tertiary"
                isDisabled={isPending}
                onPress={onCancel}
              >
                Voltar
              </Button>
              <Button
                type="button"
                className={`primary-button${destructive ? " confirmation-destructive" : ""}`}
                isPending={isPending}
                isDisabled={isPending}
                onPress={() => void onConfirm()}
              >
                {confirmLabel}
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal.Root>
  );
}
