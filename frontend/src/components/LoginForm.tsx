"use client";

import { useState, type FormEvent } from "react";
import { GraduationCap, LockKeyhole } from "lucide-react";
import { Button, Label } from "@heroui/react";
import Link from "next/link";
import { login, type AuthUser, type DemoProfile } from "@/lib/backend";
import { notifications } from "@/lib/notifications";

function isDemoProfile(value: string): value is DemoProfile {
  return value === "professor" || value === "aluno_1" || value === "aluno_2";
}

export default function LoginForm({
  onLoggedIn,
}: {
  onLoggedIn: (user: AuthUser) => void;
}) {
  const [profile, setProfile] = useState<DemoProfile>("professor");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      onLoggedIn(await login(profile));
    } catch (loginError) {
      notifications.error(loginError, "Não foi possível iniciar sessão.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-shell">
      <section className="login-card">
        <Link className="brand-lockup login-brand" href="/" aria-label="Educa, início">
          <span className="brand-mark">
            <GraduationCap size={22} aria-hidden="true" />
          </span>
          <span className="brand-name">
            educa<span>.</span>
            <small>ACOMPANHAMENTO ACADÉMICO</small>
          </span>
        </Link>
        <div className="login-heading">
          <span className="login-icon">
            <LockKeyhole size={20} aria-hidden="true" />
          </span>
          <h1>Bem-vindo de volta</h1>
          <p>Inicie sessão como professor ou estudante.</p>
        </div>
        <form onSubmit={submit} className="login-form">
          <div className="field">
            <Label htmlFor="login-profile">Perfil</Label>
            <select
              id="login-profile"
              required
              disabled={submitting}
              value={profile}
              onChange={(event) => {
                if (isDemoProfile(event.target.value)) {
                  setProfile(event.target.value);
                }
              }}
            >
              <option value="professor">Professor (padrão)</option>
              <option value="aluno_1">Aluno 1</option>
              <option value="aluno_2">Aluno 2</option>
            </select>
          </div>
          <Button type="submit" className="primary-button login-submit" isPending={submitting}>
            Iniciar sessão
          </Button>
        </form>
      </section>
    </main>
  );
}
