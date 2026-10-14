"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  CalendarCheck,
  CalendarRange,
  Check,
  Eye,
  MailWarning,
  Pencil,
  Plus,
  Send,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { Button, Card, Chip, ProgressBar, Spinner, Table } from "@heroui/react";
import ConfirmationDialog from "@/components/ConfirmationDialog";
import {
  closeTerm,
  createTerm,
  deleteTerm,
  fetchTermDeliveries,
  fetchTerms,
  updateTerm,
  type AcademicTerm,
  type TermCloseReport,
  type TermDelivery,
  type TermPayload,
} from "@/lib/backend";
import { notifications } from "@/lib/notifications";

const PASSING_GRADE = 10;

const statusChips: Record<
  AcademicTerm["status"],
  { label: string; color: "accent" | "warning" | "success" }
> = {
  open: { label: "Aberto", color: "accent" },
  closing: { label: "A fechar", color: "warning" },
  closed: { label: "Fechado", color: "success" },
};

const sourceChips: Record<
  TermDelivery["summarySource"],
  { label: string; color: "accent" | "warning" | "default" }
> = {
  llm: { label: "LLM", color: "accent" },
  template: { label: "Template", color: "warning" },
  cache: { label: "Reaproveitado", color: "default" },
};

const emailChips: Record<
  TermDelivery["emailStatus"],
  { label: string; color: "success" | "danger" | "warning" }
> = {
  sent: { label: "Enviado", color: "success" },
  failed: { label: "Falhou", color: "danger" },
  pending: { label: "Pendente", color: "warning" },
};

const emptyForm: TermPayload = { code: "", name: "", startDate: "", endDate: "" };

function formatDate(value: string): string {
  // Datas puras (AAAA-MM-DD): sem fuso, para não recuar um dia.
  const [year, month, day] = value.slice(0, 10).split("-");
  return `${day}/${month}/${year}`;
}

function formatGrade(grade: number): string {
  return new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 }).format(grade);
}

function todayIso(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 10);
}

function initials(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

function percent(part: number, whole: number): number {
  return whole ? Math.round((part / whole) * 100) : 0;
}

type PendingAction =
  | { type: "close"; term: AcademicTerm }
  | { type: "delete"; term: AcademicTerm };

function Kpi({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "danger" | "warning";
}) {
  return (
    <div className={`metrics-kpi${tone ? ` metrics-kpi-${tone}` : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </div>
  );
}

function TermsTable({
  terms,
  selectedId,
  onClose,
  onDetails,
  onEdit,
  onDelete,
}: {
  terms: AcademicTerm[];
  selectedId: number | null;
  onClose: (term: AcademicTerm) => void;
  onDetails: (term: AcademicTerm) => void;
  onEdit: (term: AcademicTerm) => void;
  onDelete: (term: AcademicTerm) => void;
}) {
  return (
    <Table className="student-table term-table">
      <Table.ScrollContainer>
        <Table.Content aria-label="Semestres" className="min-w-[860px]">
          <Table.Header>
            <Table.Column isRowHeader>SEMESTRE</Table.Column>
            <Table.Column>PERÍODO</Table.Column>
            <Table.Column>ESTADO</Table.Column>
            <Table.Column>LEITURA</Table.Column>
            <Table.Column className="text-right">AÇÕES</Table.Column>
          </Table.Header>
          <Table.Body>
            {terms.map((term) => {
              const { alunosNotificados, notificacoesLidas, emailsPendentes } =
                term.entregas;
              const status = statusChips[term.status];
              const isOpen = term.status === "open";
              const readPercent = percent(notificacoesLidas, alunosNotificados);
              return (
                <Table.Row
                  key={term.id}
                  className={selectedId === term.id ? "term-row-selected" : undefined}
                >
                  <Table.Cell>
                    <div className="term-identity">
                      <span className="term-code">{term.code}</span>
                      <strong>{term.name}</strong>
                    </div>
                  </Table.Cell>
                  <Table.Cell>
                    <div className="term-cell-stack">
                      <span>{formatDate(term.startDate)} – {formatDate(term.endDate)}</span>
                      <small>Fecho a {formatDate(term.endDate)}</small>
                    </div>
                  </Table.Cell>
                  <Table.Cell>
                    <div className="term-cell-stack">
                      <Chip size="sm" color={status.color}>
                        {status.label}
                      </Chip>
                      {term.closedAt && (
                        <small>
                          em {new Date(term.closedAt).toLocaleDateString("pt-BR")}
                        </small>
                      )}
                    </div>
                  </Table.Cell>
                  <Table.Cell>
                    {alunosNotificados === 0 ? (
                      <span className="term-muted">Ainda sem envios</span>
                    ) : (
                      <div className="term-progress">
                        <div className="term-progress-label">
                          <span>
                            <strong>{notificacoesLidas}</strong> de {alunosNotificados} lidas
                          </span>
                          <span>{readPercent}%</span>
                        </div>
                        <ProgressBar
                          aria-label={`Notificações lidas de ${term.code}`}
                          value={readPercent}
                          size="sm"
                          color="success"
                        >
                          <ProgressBar.Track>
                            <ProgressBar.Fill />
                          </ProgressBar.Track>
                        </ProgressBar>
                        {emailsPendentes > 0 && (
                          <span className="term-warning">
                            <MailWarning size={12} aria-hidden="true" />
                            {emailsPendentes} email(s) por entregar
                          </span>
                        )}
                      </div>
                    )}
                  </Table.Cell>
                  <Table.Cell>
                    <div className="term-actions">
                      {term.status !== "closing" && (isOpen || emailsPendentes > 0) && (
                        <Button
                          size="sm"
                          className={isOpen ? "primary-button" : undefined}
                          variant={isOpen ? undefined : "secondary"}
                          onPress={() => onClose(term)}
                        >
                          <Send size={14} aria-hidden="true" />
                          {isOpen ? "Fechar e notificar" : "Reenviar pendentes"}
                        </Button>
                      )}
                      {!isOpen && (
                        <Button
                          size="sm"
                          variant="secondary"
                          onPress={() => onDetails(term)}
                        >
                          <Eye size={14} aria-hidden="true" />
                          Entregas
                        </Button>
                      )}
                      {isOpen && alunosNotificados === 0 && (
                        <>
                          <Button
                            isIconOnly
                            size="sm"
                            variant="tertiary"
                            aria-label={`Editar ${term.code}`}
                            onPress={() => onEdit(term)}
                          >
                            <Pencil size={15} aria-hidden="true" />
                          </Button>
                          <Button
                            isIconOnly
                            size="sm"
                            variant="tertiary"
                            className="delete-icon-button"
                            aria-label={`Excluir ${term.code}`}
                            onPress={() => onDelete(term)}
                          >
                            <Trash2 size={15} aria-hidden="true" />
                          </Button>
                        </>
                      )}
                    </div>
                  </Table.Cell>
                </Table.Row>
              );
            })}
          </Table.Body>
        </Table.Content>
      </Table.ScrollContainer>
    </Table>
  );
}

function DeliveriesTable({ deliveries }: { deliveries: TermDelivery[] }) {
  return (
    <Table className="student-table">
      <Table.ScrollContainer>
        <Table.Content aria-label="Entregas por estudante" className="min-w-[820px]">
          <Table.Header>
            <Table.Column isRowHeader>ESTUDANTE</Table.Column>
            <Table.Column>MATEMÁTICA</Table.Column>
            <Table.Column>HISTÓRIA</Table.Column>
            <Table.Column>RESUMO</Table.Column>
            <Table.Column>EMAIL</Table.Column>
            <Table.Column>NA APP</Table.Column>
          </Table.Header>
          <Table.Body>
            {deliveries.map((item) => {
              const source = sourceChips[item.summarySource];
              const email = emailChips[item.emailStatus];
              return (
                <Table.Row key={item.notificationId}>
                  <Table.Cell>
                    <div className="student-identity">
                      <span className="student-avatar">{initials(item.studentName)}</span>
                      <span>
                        <strong>{item.studentName}</strong>
                        <small>{item.studentEmail}</small>
                      </span>
                    </div>
                  </Table.Cell>
                  {[item.mathGrade, item.historyGrade].map((grade, index) => (
                    <Table.Cell key={index}>
                      <span
                        className={`grade-value${grade < PASSING_GRADE ? " grade-value-low" : ""}`}
                      >
                        {formatGrade(grade)}
                      </span>
                    </Table.Cell>
                  ))}
                  <Table.Cell>
                    <Chip size="sm" color={source.color}>
                      {source.label}
                    </Chip>
                  </Table.Cell>
                  <Table.Cell>
                    <Chip size="sm" color={email.color}>
                      {email.label}
                    </Chip>
                  </Table.Cell>
                  <Table.Cell>
                    {item.readAt ? (
                      <div className="term-cell-stack">
                        <Chip size="sm" color="success">
                          Lida
                        </Chip>
                        <small>{new Date(item.readAt).toLocaleDateString("pt-BR")}</small>
                      </div>
                    ) : (
                      <Chip size="sm">Não lida</Chip>
                    )}
                  </Table.Cell>
                </Table.Row>
              );
            })}
          </Table.Body>
        </Table.Content>
      </Table.ScrollContainer>
    </Table>
  );
}

function TermDetails({
  term,
  deliveries,
  report,
  onDismiss,
}: {
  term: AcademicTerm;
  deliveries: TermDelivery[] | null;
  report: TermCloseReport | null;
  onDismiss: () => void;
}) {
  const stats = useMemo(() => {
    const items = deliveries ?? [];
    const count = (predicate: (item: TermDelivery) => boolean) =>
      items.filter(predicate).length;
    return {
      total: items.length,
      read: count((item) => item.readAt !== null),
      emailFailed: count((item) => item.emailStatus !== "sent"),
      llm: count((item) => item.summarySource === "llm"),
      template: count((item) => item.summarySource === "template"),
      cache: count((item) => item.summarySource === "cache"),
    };
  }, [deliveries]);

  return (
    <Card className="content-card list-card">
      <Card.Header className="term-card-header">
        <div className="term-card-title">
          <span className="term-card-icon">
            <CalendarRange size={18} aria-hidden="true" />
          </span>
          <div>
            <Card.Title>
              Entregas de {term.code} · {term.name}
            </Card.Title>
            <Card.Description>
              {term.closedAt
                ? `Fechado em ${new Date(term.closedAt).toLocaleString("pt-BR")}${term.closedBy ? ` por ${term.closedBy}` : ""}`
                : "Ainda não fechado"}
            </Card.Description>
          </div>
        </div>
        <Button
          isIconOnly
          size="sm"
          variant="tertiary"
          aria-label="Fechar entregas"
          onPress={onDismiss}
        >
          <X size={16} aria-hidden="true" />
        </Button>
      </Card.Header>

      {deliveries === null ? (
        <div className="loading-panel" role="status">
          <Spinner size="md" />
          <span>A carregar entregas…</span>
        </div>
      ) : (
        <>
          <div className="term-kpis metrics-grid">
            <Kpi label="Estudantes notificados" value={stats.total} />
            <Kpi
              label="Leram na app"
              value={`${percent(stats.read, stats.total)}%`}
              hint={`${stats.read} de ${stats.total}`}
            />
            <Kpi
              label="Emails por entregar"
              value={stats.emailFailed}
              tone={stats.emailFailed > 0 ? "danger" : undefined}
            />
            <Kpi
              label="Origem dos resumos"
              value={`${stats.llm} LLM`}
              hint={`${stats.template} template · ${stats.cache} reaproveitados`}
              tone={stats.template > 0 ? "warning" : undefined}
            />
          </div>

          {report && report.termId === term.id && (
            <div className="term-report" role="status">
              <Sparkles size={15} aria-hidden="true" />
              <span>
                <strong>Último fecho:</strong> {report.notificados} notificado(s)
                {report.jaNotificados > 0 && `, ${report.jaNotificados} já tinham recebido`}
                {report.falhas > 0 && `, ${report.falhas} falha(s)`} ·{" "}
                {report.tokensGastos} tokens · US$ {report.custoEstimadoUsd.toFixed(5)} ·{" "}
                {(report.tempoTotalMs / 1000).toFixed(1)} s
                {report.orcamentoExcedido && " · teto de custo atingido"}
              </span>
            </div>
          )}
          {report && report.termId === term.id && report.erros.length > 0 && (
            <ul className="upload-errors term-errors">
              {report.erros.map((item, index) => (
                <li key={`${item.mensagem}-${index}`}>{item.mensagem}</li>
              ))}
            </ul>
          )}

          <Card.Content className="table-content">
            {deliveries.length === 0 ? (
              <p className="term-muted term-empty-deliveries">
                Nenhuma notificação foi gerada para este semestre.
              </p>
            ) : (
              <DeliveriesTable deliveries={deliveries} />
            )}
          </Card.Content>
        </>
      )}
    </Card>
  );
}

export default function TermManager() {
  const [terms, setTerms] = useState<AcademicTerm[] | null>(null);
  const [form, setForm] = useState<TermPayload>(emptyForm);
  const [editing, setEditing] = useState<AcademicTerm | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<TermCloseReport | null>(null);
  const [selected, setSelected] = useState<AcademicTerm | null>(null);
  const [deliveries, setDeliveries] = useState<TermDelivery[] | null>(null);

  const loadTerms = useCallback(async () => {
    try {
      const next = await fetchTerms();
      setTerms(next);
      // Mantém o detalhe aberto com os números atualizados.
      setSelected((current) =>
        current ? next.find((term) => term.id === current.id) ?? null : null
      );
    } catch (error) {
      notifications.error(error, "Não foi possível carregar os semestres.");
      setTerms((current) => current ?? []);
    }
  }, []);

  const loadDeliveries = useCallback(async (term: AcademicTerm) => {
    setSelected(term);
    setDeliveries(null);
    try {
      setDeliveries(await fetchTermDeliveries(term.id));
    } catch (error) {
      notifications.error(error, "Não foi possível carregar as entregas.");
      setDeliveries([]);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadTerms(), 0);
    return () => window.clearTimeout(timer);
  }, [loadTerms]);

  const openForm = (term: AcademicTerm | null) => {
    setEditing(term);
    setForm(
      term
        ? {
            code: term.code,
            name: term.name,
            startDate: term.startDate,
            endDate: term.endDate,
          }
        : emptyForm
    );
    setShowForm(true);
  };

  const closeForm = () => {
    setShowForm(false);
    setEditing(null);
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (form.endDate < form.startDate) {
      notifications.warning("A data de fecho deve ser igual ou posterior ao início.");
      return;
    }
    setSaving(true);
    try {
      const name = form.name.trim();
      if (editing) {
        await updateTerm(editing.id, {
          name,
          startDate: form.startDate,
          endDate: form.endDate,
        });
        notifications.success("Semestre atualizado.");
      } else {
        await createTerm({ ...form, code: form.code.trim(), name });
        notifications.success("Semestre criado.");
      }
      closeForm();
      await loadTerms();
    } catch (error) {
      notifications.error(error, "Não foi possível guardar o semestre.");
    } finally {
      setSaving(false);
    }
  };

  const confirmAction = async () => {
    if (!pendingAction) return;
    const { term } = pendingAction;
    setRunning(true);
    try {
      if (pendingAction.type === "delete") {
        await deleteTerm(term.id);
        notifications.success("Semestre excluído.");
        if (selected?.id === term.id) setSelected(null);
      } else {
        const result = await closeTerm(term.id);
        setReport(result);
        if (result.falhas > 0) {
          notifications.warning(
            "Semestre fechado com falhas de entrega.",
            `${result.falhas} estudante(s) não receberam o email; use "Reenviar pendentes".`
          );
        } else {
          notifications.success(
            `${term.code} fechado.`,
            `${result.notificados} estudante(s) notificado(s).`
          );
        }
        await loadDeliveries(term);
      }
      setPendingAction(null);
      await loadTerms();
    } catch (error) {
      notifications.error(error, "Não foi possível concluir esta ação.");
    } finally {
      setRunning(false);
    }
  };

  if (terms === null) {
    return (
      <div className="loading-panel" role="status">
        <Spinner size="md" />
        <span>A carregar semestres…</span>
      </div>
    );
  }

  const today = todayIso();

  return (
    <div className="term-page">
      <Card className="content-card list-card">
        <Card.Header className="term-card-header">
          <div className="term-card-title">
            <span className="term-card-icon">
              <CalendarCheck size={18} aria-hidden="true" />
            </span>
            <div>
              <Card.Title>Períodos letivos</Card.Title>
              <Card.Description>
                Ao fechar um semestre, cada estudante recebe o boletim com um resumo
                personalizado na app e por email.
              </Card.Description>
            </div>
          </div>
          {!showForm && (
            <Button className="primary-button" onPress={() => openForm(null)}>
              <Plus size={17} aria-hidden="true" />
              Novo semestre
            </Button>
          )}
        </Card.Header>

        {showForm && (
          <div className="form-container">
            <form className="student-form" onSubmit={submit}>
              <div className="form-heading">
                <div>
                  <p className="eyebrow">{editing ? "EDITAR" : "NOVO"} SEMESTRE</p>
                  <h3>{editing ? `${editing.code} · ${editing.name}` : "Período letivo"}</h3>
                  <p className="form-description">
                    A data de fecho indica quando as notas deste período ficam definitivas.
                  </p>
                </div>
              </div>
              <div className="form-grid term-form-grid">
                <div className="field">
                  <label htmlFor="term-code">Código</label>
                  <input
                    id="term-code"
                    required
                    maxLength={20}
                    pattern="[A-Za-z0-9._/\-]+"
                    placeholder="2026.1"
                    value={form.code}
                    readOnly={editing !== null}
                    onChange={(event) => setForm({ ...form, code: event.target.value })}
                  />
                </div>
                <div className="field">
                  <label htmlFor="term-name">Nome</label>
                  <input
                    id="term-name"
                    required
                    maxLength={120}
                    placeholder="1.º semestre de 2026"
                    value={form.name}
                    onChange={(event) => setForm({ ...form, name: event.target.value })}
                  />
                </div>
                <div className="field">
                  <label htmlFor="term-start">Início</label>
                  <input
                    id="term-start"
                    type="date"
                    required
                    value={form.startDate}
                    onChange={(event) => setForm({ ...form, startDate: event.target.value })}
                  />
                </div>
                <div className="field">
                  <label htmlFor="term-end">Data de fecho</label>
                  <input
                    id="term-end"
                    type="date"
                    required
                    min={form.startDate || undefined}
                    value={form.endDate}
                    onChange={(event) => setForm({ ...form, endDate: event.target.value })}
                  />
                </div>
              </div>
              <div className="form-actions">
                <Button type="button" variant="tertiary" isDisabled={saving} onPress={closeForm}>
                  <X size={15} aria-hidden="true" />
                  Cancelar
                </Button>
                <Button
                  type="submit"
                  className="primary-button"
                  isPending={saving}
                  isDisabled={saving}
                >
                  <Check size={15} aria-hidden="true" />
                  {editing ? "Guardar" : "Criar semestre"}
                </Button>
              </div>
            </form>
          </div>
        )}

        <Card.Content className="table-content">
          {terms.length === 0 ? (
            <div className="empty-state">
              <span className="empty-icon">
                <CalendarCheck size={22} aria-hidden="true" />
              </span>
              <strong>Nenhum semestre registado</strong>
              <p>Crie o período letivo para depois o fechar e notificar a turma.</p>
            </div>
          ) : (
            <TermsTable
              terms={terms}
              selectedId={selected?.id ?? null}
              onClose={(term) => setPendingAction({ type: "close", term })}
              onDetails={(term) => void loadDeliveries(term)}
              onEdit={openForm}
              onDelete={(term) => setPendingAction({ type: "delete", term })}
            />
          )}
        </Card.Content>
        <div className="table-footer">
          <span>
            <strong>{terms.length}</strong> semestre{terms.length === 1 ? "" : "s"} ·{" "}
            <strong>{terms.filter((term) => term.status === "closed").length}</strong>{" "}
            fechado{terms.filter((term) => term.status === "closed").length === 1 ? "" : "s"}
          </span>
          <span>Reenviar só entrega a quem ainda não recebeu</span>
        </div>
      </Card>

      {selected && (
        <TermDetails
          term={selected}
          deliveries={deliveries}
          report={report}
          onDismiss={() => setSelected(null)}
        />
      )}

      {pendingAction && (
        <ConfirmationDialog
          title={
            pendingAction.type === "delete"
              ? `Excluir ${pendingAction.term.code}?`
              : pendingAction.term.status === "open"
                ? `Fechar ${pendingAction.term.code} e notificar a turma?`
                : `Reenviar entregas pendentes de ${pendingAction.term.code}?`
          }
          description={
            pendingAction.type === "delete" ? (
              <p>O semestre será excluído. Esta ação não pode ser desfeita.</p>
            ) : (
              <>
                <p>
                  Cada estudante ainda não notificado recebe o boletim de{" "}
                  <strong>{pendingAction.term.name}</strong> com as notas atuais e um
                  resumo personalizado gerado por LLM (&quot;foi bem em…, atenção em…,
                  próximos passos…&quot;). Quem já recebeu não é notificado de novo.
                </p>
                {pendingAction.term.status === "open" &&
                  pendingAction.term.endDate > today && (
                    <blockquote>
                      A data de fecho é {formatDate(pendingAction.term.endDate)}. Fechar
                      agora antecipa o envio dos boletins.
                    </blockquote>
                  )}
              </>
            )
          }
          confirmLabel={
            pendingAction.type === "delete"
              ? "Excluir"
              : pendingAction.term.status === "open"
                ? "Fechar e notificar"
                : "Reenviar"
          }
          destructive={pendingAction.type === "delete"}
          isPending={running}
          onCancel={() => setPendingAction(null)}
          onConfirm={confirmAction}
        />
      )}
    </div>
  );
}
