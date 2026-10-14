"use client";

import { useState, type FormEvent } from "react";
import { Check, X } from "lucide-react";
import { Button, Input, Label } from "@heroui/react";
import {
  createStudent,
  updateStudent,
  type Student,
  type StudentPayload,
} from "@/lib/backend";
import { notifications } from "@/lib/notifications";

type StudentFormProps = {
  student?: Student | null;
  onCancel: () => void;
  onSaved: () => void;
};

export default function StudentForm({
  student,
  onCancel,
  onSaved,
}: StudentFormProps) {
  const [values, setValues] = useState({
    name: student?.name ?? "",
    email: student?.email ?? "",
    math_grade: student?.math_grade.toString() ?? "",
    history_grade: student?.history_grade.toString() ?? "",
  });
  const [reviewRequested, setReviewRequested] = useState(
    student?.review_requested ?? false
  );
  const [saving, setSaving] = useState(false);

  const updateField = (field: keyof typeof values, value: string) => {
    setValues((current) => ({ ...current, [field]: value }));
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    const payload: StudentPayload = {
      name: values.name.trim(),
      email: values.email.trim(),
      math_grade: Number(values.math_grade),
      history_grade: Number(values.history_grade),
    };

    try {
      if (student) {
        await updateStudent(student.student_id, {
          math_grade: payload.math_grade,
          history_grade: payload.history_grade,
          review_requested: reviewRequested,
        });
      } else {
        await createStudent(payload);
      }
      notifications.success(
        student ? "Estudante atualizado." : "Estudante criado."
      );
      onSaved();
    } catch (saveError) {
      notifications.error(saveError, "Não foi possível guardar o estudante.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="student-form" onSubmit={submit}>
      <div className="form-heading">
        <div>
          <p className="eyebrow">{student ? "EDITAR REGISTO" : "NOVO REGISTO"}</p>
          <h3>{student ? "Atualizar estudante" : "Adicionar estudante"}</h3>
          {student && (
            <p className="form-description">
              O backend permite atualizar as notas e o estado da revisão.
            </p>
          )}
        </div>
        <Button
          isIconOnly
          variant="tertiary"
          aria-label="Fechar formulário"
          onPress={onCancel}
        >
          <X size={18} aria-hidden="true" />
        </Button>
      </div>
      <div className="form-grid">
        <div className="field">
          <Label htmlFor="student-name">Nome completo</Label>
          <Input
            id="student-name"
            value={values.name}
            onChange={(event) => updateField("name", event.target.value)}
            readOnly={Boolean(student)}
            required
            placeholder="Nome do estudante"
          />
        </div>
        <div className="field field-wide">
          <Label htmlFor="student-email">Email</Label>
          <Input
            id="student-email"
            type="email"
            value={values.email}
            onChange={(event) => updateField("email", event.target.value)}
            readOnly={Boolean(student)}
            required
            placeholder="estudante@exemplo.com"
          />
        </div>
        <div className="field">
          <Label htmlFor="math-grade">Nota de Matemática</Label>
          <Input
            id="math-grade"
            type="number"
            min="0"
            max="20"
            step="any"
            value={values.math_grade}
            onChange={(event) => updateField("math_grade", event.target.value)}
            required
            placeholder="0,0"
          />
        </div>
        <div className="field">
          <Label htmlFor="history-grade">Nota de História</Label>
          <Input
            id="history-grade"
            type="number"
            min="0"
            max="20"
            step="any"
            value={values.history_grade}
            onChange={(event) => updateField("history_grade", event.target.value)}
            required
            placeholder="0,0"
          />
        </div>
        {student && (
          <div className="field field-wide">
            <label className="review-toggle" htmlFor="review-requested">
              <input
                id="review-requested"
                type="checkbox"
                checked={reviewRequested}
                onChange={(event) => setReviewRequested(event.target.checked)}
                disabled={saving}
              />
              <span>
                <strong>Revisão solicitada</strong>
                <small>
                  Atualizará o estado da revisão e notificará o estudante ao
                  ativar.
                </small>
              </span>
            </label>
          </div>
        )}
      </div>
      <div className="form-actions">
        <Button variant="secondary" onPress={onCancel}>
          Cancelar
        </Button>
        <Button type="submit" isPending={saving} className="primary-button">
          <Check size={17} aria-hidden="true" />
          {student ? "Guardar alterações" : "Criar estudante"}
        </Button>
      </div>
    </form>
  );
}
