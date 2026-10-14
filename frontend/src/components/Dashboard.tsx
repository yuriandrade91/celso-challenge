"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  Activity,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Bell,
  BookOpenCheck,
  CalendarCheck,
  Check,
  ChevronDown,
  CircleHelp,
  ClipboardList,
  FileUp,
  GraduationCap,
  LayoutDashboard,
  ListFilter,
  LogOut,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Trash2,
  UsersRound,
  X,
} from "lucide-react";
import Link from "next/link";
import {
  Badge,
  Button,
  Card,
  Chip,
  Input,
  Spinner,
  Table,
} from "@heroui/react";
import StudentForm from "@/components/StudentForm";
import LoginForm from "@/components/LoginForm";
import UploadForm from "@/components/UploadForm";
import MetricsPanel from "@/components/MetricsPanel";
import ConfirmationDialog from "@/components/ConfirmationDialog";
import StudentInbox from "@/components/StudentInbox";
import TermManager from "@/components/TermManager";
import {
  createReviewRequest,
  decideReviewRequest,
  deleteStudent,
  deleteReviewRequest,
  fetchOwnNotifications,
  fetchOwnReviews,
  fetchMetrics,
  fetchPendingReviews,
  fetchOwnStudent,
  fetchStudents,
  logout,
  type AuthUser,
  type BackendMetrics,
  type ReviewDecisionPayload,
  type ReviewRequest,
  type Student,
  type StudentInbox as Inbox,
} from "@/lib/backend";
import { notifications } from "@/lib/notifications";

type Section =
  | "overview"
  | "students"
  | "reviews"
  | "uploads"
  | "terms"
  | "metrics"
  | "inbox";

const sectionDetails: Record<Section, { title: string; subtitle: string }> = {
  overview: {
    title: "Visão geral",
    subtitle: "Acompanhe o desempenho e a atividade da sua instituição.",
  },
  students: {
    title: "Estudantes",
    subtitle: "Gira os registos e acompanhe as notas de cada estudante.",
  },
  reviews: {
    title: "Revisões",
    subtitle: "Pedidos de revisão enviados pelos estudantes.",
  },
  uploads: {
    title: "Importar dados",
    subtitle: "Processe boletins em lote através de um ficheiro CSV.",
  },
  terms: {
    title: "Semestres",
    subtitle: "Feche o período letivo e envie o boletim personalizado à turma.",
  },
  inbox: {
    title: "Notificações",
    subtitle: "Boletins do semestre e respostas aos seus pedidos de revisão.",
  },
  metrics: {
    title: "Métricas",
    subtitle: "Execuções do dispatcher, custo de LLM e saúde da operação.",
  },
};

function initials(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

function formatGrade(grade: number): string {
  return new Intl.NumberFormat("pt-PT", {
    maximumFractionDigits: 1,
  }).format(grade);
}

function StudentTable({
  students,
  onEdit,
  onDelete,
  deletingId,
  onCancelDelete,
  onConfirmDelete,
  readOnly,
}: {
  students: Student[];
  onEdit: (student: Student) => void;
  onDelete: (studentId: string) => void;
  deletingId: string | null;
  onCancelDelete: () => void;
  onConfirmDelete: (studentId: string) => void;
  readOnly: boolean;
}) {
  if (!students.length) {
    return (
      <div className="empty-state">
        <span className="empty-icon">
          <UsersRound size={22} aria-hidden="true" />
        </span>
        <strong>Nenhum estudante encontrado</strong>
        <p>Adicione um registo ou ajuste a pesquisa para ver estudantes.</p>
      </div>
    );
  }

  return (
    <Table className="student-table">
      <Table.ScrollContainer>
        <Table.Content aria-label="Lista de estudantes" className="min-w-[760px]">
          <Table.Header>
            <Table.Column isRowHeader>ESTUDANTE</Table.Column>
            <Table.Column>IDENTIFICAÇÃO</Table.Column>
            <Table.Column>MATEMÁTICA</Table.Column>
            <Table.Column>HISTÓRIA</Table.Column>
            <Table.Column>ESTADO</Table.Column>
            {!readOnly && <Table.Column className="text-right">AÇÕES</Table.Column>}
          </Table.Header>
          <Table.Body>
            {students.map((student) => (
              <Table.Row key={student.student_id}>
                <Table.Cell>
                  <div className="student-identity">
                    <span className="student-avatar">{initials(student.name)}</span>
                    <span>
                      <strong>{student.name}</strong>
                      <small>{student.email}</small>
                    </span>
                  </div>
                </Table.Cell>
                <Table.Cell>
                  <span className="student-code">{student.student_id}</span>
                </Table.Cell>
                <Table.Cell>
                  <span className="grade-value">{formatGrade(student.math_grade)}</span>
                </Table.Cell>
                <Table.Cell>
                  <span className="grade-value">{formatGrade(student.history_grade)}</span>
                </Table.Cell>
                <Table.Cell>
                  {student.review_requested ? (
                    <Chip color="warning" size="sm">
                      Revisão solicitada
                    </Chip>
                  ) : (
                    <Chip color="success" size="sm">
                      Regular
                    </Chip>
                  )}
                </Table.Cell>
                {!readOnly && <Table.Cell>
                  {deletingId === student.student_id ||
                  deletingId === `loading:${student.student_id}` ? (
                    <div className="row-confirm-actions">
                      <Button
                        size="sm"
                        className="confirm-delete-button"
                        isPending={deletingId === `loading:${student.student_id}`}
                        onPress={() => onConfirmDelete(student.student_id)}
                      >
                        <Check size={14} aria-hidden="true" />
                        Confirmar
                      </Button>
                      <Button
                        isIconOnly
                        size="sm"
                        variant="tertiary"
                        aria-label="Cancelar exclusão"
                        onPress={onCancelDelete}
                      >
                        <X size={16} aria-hidden="true" />
                      </Button>
                    </div>
                  ) : (
                    <div className="row-actions">
                      <Button
                        isIconOnly
                        size="sm"
                        variant="tertiary"
                        aria-label={`Editar ${student.name}`}
                        onPress={() => onEdit(student)}
                      >
                        <Pencil size={15} aria-hidden="true" />
                      </Button>
                      <Button
                        isIconOnly
                        size="sm"
                        variant="tertiary"
                        aria-label={`Excluir ${student.name}`}
                        className="delete-icon-button"
                        onPress={() => onDelete(student.student_id)}
                      >
                        <Trash2 size={15} aria-hidden="true" />
                      </Button>
                    </div>
                  )}
                </Table.Cell>}
              </Table.Row>
            ))}
          </Table.Body>
        </Table.Content>
      </Table.ScrollContainer>
    </Table>
  );
}

function LoadingPanel() {
  return (
    <div className="loading-panel" role="status">
      <Spinner size="md" />
      <span>A carregar dados do backend…</span>
    </div>
  );
}

function subjectName(subject: ReviewRequest["subject"]): string {
  return subject === "math" ? "Matemática" : "História";
}

function StudentGradeCard({
  subject,
  grade,
  review,
  onRequest,
  dark = false,
}: {
  subject: ReviewRequest["subject"];
  grade: number;
  review?: ReviewRequest;
  onRequest: (
    subject: ReviewRequest["subject"],
    justification: string
  ) => Promise<void>;
  dark?: boolean;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [justification, setJustification] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const isPending = review?.status === "pending";

  const submitRequest = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedJustification = justification.trim();
    if (trimmedJustification.length < 10) {
      notifications.warning("A justificativa deve ter pelo menos 10 caracteres.");
      return;
    }
    setConfirming(true);
  };

  const confirmRequest = async () => {
    setSubmitting(true);
    try {
      await onRequest(subject, justification.trim());
      setJustification("");
      setIsOpen(false);
      setConfirming(false);
      notifications.success("Pedido de revisão enviado ao professor.");
    } catch (requestError) {
      notifications.error(
        requestError instanceof Error
          ? requestError.message
          : "Não foi possível enviar o pedido de revisão.",
        "Não foi possível enviar o pedido de revisão."
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card className={`metric-card grade-review-card${dark ? " metric-card-dark" : ""}`}>
      <Card.Content>
        <p className="metric-label">{subjectName(subject)}</p>
        <div className="metric-value-row">
          <strong>{formatGrade(grade)}</strong>
          <span>nota</span>
        </div>
        <div className="grade-review-actions">
          {isPending ? (
            <Chip color="warning" size="sm">Pedido em análise</Chip>
          ) : (
            <Button
              size="sm"
              variant="secondary"
              onPress={() => setIsOpen((current) => !current)}
            >
              {review ? "Solicitar nova revisão" : "Pedir revisão"}
            </Button>
          )}
        </div>
        {review && !isPending && (
          <div className="student-review-response">
            <strong>
              {review.status === "adjusted"
                ? `Nota ajustada para ${formatGrade(review.adjusted_grade ?? grade)}`
                : "Pedido cancelado"}
            </strong>
            {review.teacher_response && <p>{review.teacher_response}</p>}
          </div>
        )}
        {isPending && (
          <p className="student-review-pending">{review?.justification}</p>
        )}
        {isOpen && !isPending && (
          <form className="grade-review-form" onSubmit={submitRequest}>
            <label htmlFor={`review-justification-${subject}`}>
              Por que esta nota deve ser revista?
            </label>
            <textarea
              id={`review-justification-${subject}`}
              value={justification}
              minLength={10}
              maxLength={2000}
              rows={3}
              required
              onChange={(event) => setJustification(event.target.value)}
              placeholder="Explique os pontos que gostaria que o professor analisasse."
            />
            <div className="grade-review-form-actions">
              <Button
                type="button"
                variant="tertiary"
                size="sm"
                onPress={() => setIsOpen(false)}
              >
                Fechar
              </Button>
              <Button
                type="submit"
                size="sm"
                className="primary-button"
                isPending={submitting}
                isDisabled={submitting}
              >
                Continuar
              </Button>
            </div>
          </form>
        )}
        {confirming && (
          <ConfirmationDialog
            title="Confirmar pedido de revisão?"
            description={
              <>
                <p>
                  O professor receberá um pedido para rever sua nota de{" "}
                  <strong>{subjectName(subject)}</strong> ({formatGrade(grade)}).
                </p>
                <blockquote>{justification.trim()}</blockquote>
              </>
            }
            confirmLabel="Enviar pedido"
            isPending={submitting}
            onCancel={() => setConfirming(false)}
            onConfirm={confirmRequest}
          />
        )}
      </Card.Content>
    </Card>
  );
}

function TeacherReviewCard({
  review,
  onDecide,
  onDelete,
}: {
  review: ReviewRequest;
  onDecide: (
    reviewId: number,
    decision: ReviewDecisionPayload
  ) => Promise<void>;
  onDelete: (reviewId: number) => Promise<void>;
}) {
  const [response, setResponse] = useState("");
  const [grade, setGrade] = useState(String(review.original_grade));
  const [submitting, setSubmitting] = useState(false);
  const [pendingAction, setPendingAction] = useState<
    ReviewDecisionPayload | "delete" | null
  >(null);

  const requestDecision = (action: ReviewDecisionPayload["action"]) => {
    if (!response.trim()) {
      notifications.warning("Escreva uma resposta para o estudante.");
      return;
    }
    const decision: ReviewDecisionPayload =
      action === "adjusted"
        ? {
            action,
            teacher_response: response.trim(),
            adjusted_grade: Number(grade),
          }
        : { action, teacher_response: response.trim() };
    if (
      decision.action === "adjusted" &&
      (!Number.isFinite(decision.adjusted_grade) ||
        decision.adjusted_grade < 0 ||
        decision.adjusted_grade > 20)
    ) {
      notifications.warning("A nova nota deve estar entre 0 e 20.");
      return;
    }

    setPendingAction(decision);
  };

  const confirmDecision = async () => {
    if (!pendingAction) return;
    setSubmitting(true);
    try {
      if (pendingAction === "delete") {
        await onDelete(review.id);
      } else {
        await onDecide(review.id, pendingAction);
      }
      setPendingAction(null);
      notifications.success(
        pendingAction === "delete"
          ? "Pedido de revisão excluído."
          : pendingAction.action === "adjusted"
            ? "Nota ajustada. O estudante foi notificado."
            : "Pedido de revisão cancelado. O estudante foi notificado."
      );
    } catch (decisionError) {
      notifications.error(decisionError, "Não foi possível concluir esta ação.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <article className="teacher-review-card">
      <div className="teacher-review-heading">
        <div>
          <p className="eyebrow">{subjectName(review.subject)}</p>
          <h2>{review.student_name}</h2>
          <p>{review.student_email}</p>
        </div>
        <Chip color="warning" size="sm">Pendente</Chip>
      </div>
      <div className="teacher-review-grades">
        <span>Nota atual</span>
        <strong>{formatGrade(review.original_grade)} / 20</strong>
      </div>
      <div className="teacher-review-justification">
        <strong>Justificativa do estudante</strong>
        <p>{review.justification}</p>
      </div>
      <label className="teacher-review-label" htmlFor={`review-response-${review.id}`}>
        Resposta ao estudante
      </label>
      <textarea
        id={`review-response-${review.id}`}
        value={response}
        maxLength={2000}
        rows={3}
        onChange={(event) => setResponse(event.target.value)}
        placeholder="Explique a análise feita e a decisão."
      />
      <div className="teacher-review-adjustment">
        <label htmlFor={`review-grade-${review.id}`}>Nova nota</label>
        <input
          id={`review-grade-${review.id}`}
          type="number"
          min="0"
          max="20"
          step="0.1"
          value={grade}
          onChange={(event) => setGrade(event.target.value)}
        />
        <span>Informe a nota apenas para aplicar um ajuste.</span>
      </div>
      <div className="teacher-review-actions">
        <Button
          size="sm"
          className="primary-button"
          isPending={submitting}
          isDisabled={submitting}
          onPress={() => requestDecision("adjusted")}
        >
          <Check size={15} aria-hidden="true" />
          Aplicar ajuste
        </Button>
        <Button
          size="sm"
          variant="secondary"
          isPending={submitting}
          isDisabled={submitting}
          onPress={() => requestDecision("cancelled")}
        >
          <X size={15} aria-hidden="true" />
          Cancelar pedido
        </Button>
        <Button
          size="sm"
          variant="tertiary"
          className="delete-review-button"
          isPending={submitting}
          isDisabled={submitting}
          onPress={() => {
            setPendingAction("delete");
          }}
        >
          <Trash2 size={15} aria-hidden="true" />
          Excluir pedido
        </Button>
      </div>
      {pendingAction && (
        <ConfirmationDialog
          title={
            pendingAction === "delete"
              ? "Excluir pedido de revisão?"
              : pendingAction.action === "adjusted"
                ? "Confirmar ajuste da nota?"
                : "Cancelar pedido de revisão?"
          }
          description={
            pendingAction === "delete" ? (
              <p>
                O pedido pendente de <strong>{review.student_name}</strong> será
                excluído permanentemente. Esta ação não pode ser desfeita.
              </p>
            ) : (
              <>
                <p>
                  {pendingAction.action === "adjusted"
                    ? `A nota de ${subjectName(review.subject)} será alterada de ${formatGrade(review.original_grade)} para ${formatGrade(pendingAction.adjusted_grade)}.`
                    : `O pedido de ${subjectName(review.subject)} de ${review.student_name} será encerrado sem alterar a nota.`}
                </p>
                <blockquote>{pendingAction.teacher_response}</blockquote>
              </>
            )
          }
          confirmLabel={
            pendingAction === "delete"
              ? "Excluir pedido"
              : pendingAction.action === "adjusted"
                ? "Confirmar ajuste"
                : "Confirmar cancelamento"
          }
          destructive={
            pendingAction === "delete" || pendingAction.action === "cancelled"
          }
          isPending={submitting}
          onCancel={() => setPendingAction(null)}
          onConfirm={confirmDecision}
        />
      )}
    </article>
  );
}

export default function Dashboard({
  initialUser,
}: {
  initialUser: AuthUser | null;
}) {
  const [user, setUser] = useState<AuthUser | null>(initialUser);
  const [section, setSection] = useState<Section>("overview");
  const [metrics, setMetrics] = useState<BackendMetrics | null>(null);
  const [students, setStudents] = useState<Student[]>([]);
  const [reviews, setReviews] = useState<ReviewRequest[]>([]);
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [showStudentForm, setShowStudentForm] = useState(false);
  const [editingStudent, setEditingStudent] = useState<Student | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const observedPendingReviewIds = useRef<Set<number> | null>(null);
  const pollErrorShown = useRef(false);
  const observedNotificationIds = useRef<Set<number> | null>(null);

  const applyInbox = useCallback((nextInbox: Inbox) => {
    const previousIds = observedNotificationIds.current;
    if (previousIds !== null) {
      const fresh = nextInbox.items.filter(
        (item) => item.readAt === null && !previousIds.has(item.id)
      );
      if (fresh.length === 1) {
        notifications.info("Nova notificação", fresh[0].title);
      } else if (fresh.length > 1) {
        notifications.info(`${fresh.length} novas notificações`);
      }
    }
    observedNotificationIds.current = new Set(
      nextInbox.items.map((item) => item.id)
    );
    setInbox(nextInbox);
  }, []);

  const applyPendingReviews = useCallback((nextReviews: ReviewRequest[]) => {
    const previousIds = observedPendingReviewIds.current;
    if (previousIds !== null) {
      const newReviews = nextReviews.filter(
        (review) => !previousIds.has(review.id)
      );
      if (newReviews.length > 0) {
        const descriptions = newReviews
          .slice(0, 3)
          .map(
            (review) =>
              `${review.student_name} · ${subjectName(review.subject)}`
          );
        if (newReviews.length > 3) {
          descriptions.push(`e mais ${newReviews.length - 3}`);
        }
        notifications.info(
          newReviews.length === 1
            ? "Nova solicitação de revisão"
            : `${newReviews.length} novas solicitações de revisão`,
          descriptions.join(", ")
        );
      }
    }
    observedPendingReviewIds.current = new Set(
      nextReviews.map((review) => review.id)
    );
    setReviews(nextReviews);
    setMetrics((current) =>
      current
        ? { ...current, revisoes_pendentes: nextReviews.length }
        : current
    );
  }, []);

  useEffect(() => {
    observedPendingReviewIds.current = null;
    observedNotificationIds.current = null;
    pollErrorShown.current = false;
  }, [user?.email]);

  const refreshData = useCallback(async (showRefresh = false) => {
    if (!user) return;
    if (showRefresh) setRefreshing(true);
    else setLoading(true);
    setLoadError(null);

    if (user.role === "student") {
      const [studentResult, reviewResult, inboxResult] = await Promise.allSettled([
        fetchOwnStudent(),
        fetchOwnReviews(),
        fetchOwnNotifications(),
      ]);
      const errors: string[] = [];
      if (studentResult.status === "fulfilled") {
        setStudents([studentResult.value]);
      } else {
        errors.push(
          studentResult.reason instanceof Error
            ? studentResult.reason.message
            : "Não foi possível carregar o seu registo."
        );
      }
      if (reviewResult.status === "fulfilled") {
        setReviews(reviewResult.value);
      } else {
        errors.push(
          reviewResult.reason instanceof Error
            ? reviewResult.reason.message
            : "Não foi possível carregar os seus pedidos de revisão."
        );
      }
      if (inboxResult.status === "fulfilled") {
        applyInbox(inboxResult.value);
      } else {
        errors.push(
          inboxResult.reason instanceof Error
            ? inboxResult.reason.message
            : "Não foi possível carregar as suas notificações."
        );
      }
      setMetrics(null);
      const message = errors.join(" ");
      setLoadError(message || null);
      if (message) notifications.error(message, "Alguns dados não foram carregados.");
      setLoading(false);
      setRefreshing(false);
      return;
    }

    const [metricsResult, studentsResult, reviewsResult] =
      await Promise.allSettled([
        fetchMetrics(),
        fetchStudents(),
        fetchPendingReviews(),
      ]);
    const errors: string[] = [];

    if (metricsResult.status === "fulfilled") {
      setMetrics(metricsResult.value);
    } else {
      errors.push(
        metricsResult.reason instanceof Error
          ? metricsResult.reason.message
          : "Não foi possível carregar as métricas."
      );
    }
    if (studentsResult.status === "fulfilled") {
      setStudents(studentsResult.value);
    } else {
      errors.push(
        studentsResult.reason instanceof Error
          ? studentsResult.reason.message
          : "Não foi possível carregar os estudantes."
      );
    }
    if (reviewsResult.status === "fulfilled") {
      applyPendingReviews(reviewsResult.value);
    } else {
      errors.push(
        reviewsResult.reason instanceof Error
          ? reviewsResult.reason.message
          : "Não foi possível carregar os pedidos de revisão."
      );
    }
    const message = errors.join(" ");
    setLoadError(message || null);
    if (message) notifications.error(message, "Alguns dados não foram carregados.");
    setLoading(false);
    setRefreshing(false);
  }, [applyInbox, applyPendingReviews, user]);

  useEffect(() => {
    const handleExpiredSession = () => {
      notifications.warning("A sessão expirou. Inicie sessão novamente.");
      setUser(null);
    };
    window.addEventListener("educa:session-expired", handleExpiredSession);
    return () => {
      window.removeEventListener("educa:session-expired", handleExpiredSession);
    };
  }, []);

  useEffect(() => {
    if (!user) return;
    const timer = window.setTimeout(() => void refreshData(), 0);
    return () => window.clearTimeout(timer);
  }, [refreshData, user]);

  useEffect(() => {
    if (!user || user.role !== "teacher" || loading) return;

    let isCancelled = false;
    let isChecking = false;
    const checkForNewReviews = async () => {
      if (isCancelled || isChecking || document.visibilityState !== "visible") {
        return;
      }

      isChecking = true;
      try {
        const nextReviews = await fetchPendingReviews();
        if (isCancelled) return;
        applyPendingReviews(nextReviews);
        pollErrorShown.current = false;
      } catch (error) {
        if (!isCancelled && !pollErrorShown.current) {
          notifications.error(
            error,
            "Não foi possível verificar novas solicitações de revisão."
          );
          pollErrorShown.current = true;
        }
      } finally {
        isChecking = false;
      }
    };

    const timer = window.setInterval(() => void checkForNewReviews(), 10_000);
    document.addEventListener("visibilitychange", checkForNewReviews);
    return () => {
      isCancelled = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", checkForNewReviews);
    };
  }, [applyPendingReviews, loading, user]);

  useEffect(() => {
    if (!user || user.role !== "student" || loading) return;

    let isCancelled = false;
    const checkInbox = async () => {
      if (isCancelled || document.visibilityState !== "visible") return;
      try {
        const nextInbox = await fetchOwnNotifications();
        if (isCancelled) return;
        const knownIds = observedNotificationIds.current;
        const hasNews =
          knownIds !== null &&
          nextInbox.items.some((item) => !knownIds.has(item.id));
        applyInbox(nextInbox);
        if (!hasNews) return;
        // Nota editada ou revisão decidida: as notas e os pedidos mudaram.
        const [student, ownReviews] = await Promise.all([
          fetchOwnStudent(),
          fetchOwnReviews(),
        ]);
        if (isCancelled) return;
        setStudents([student]);
        setReviews(ownReviews);
      } catch {
        // Falhas transitórias: a próxima verificação tenta de novo.
      }
    };

    const timer = window.setInterval(() => void checkInbox(), 10_000);
    document.addEventListener("visibilitychange", checkInbox);
    return () => {
      isCancelled = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", checkInbox);
    };
  }, [applyInbox, loading, user]);

  const filteredStudents = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("pt-PT");
    if (!query) return students;
    return students.filter((student) =>
      `${student.name} ${student.email} ${student.student_id}`
        .toLocaleLowerCase("pt-PT")
        .includes(query)
    );
  }, [search, students]);
  const filteredReviews = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("pt-PT");
    if (!query) return reviews;
    return reviews.filter((review) =>
      `${review.student_name} ${review.student_email} ${review.student_id} ${subjectName(review.subject)}`
        .toLocaleLowerCase("pt-PT")
        .includes(query)
    );
  }, [reviews, search]);

  const submitReviewRequest = async (
    subject: ReviewRequest["subject"],
    justification: string
  ) => {
    await createReviewRequest(subject, justification);
    await refreshData(true);
  };

  const decideReview = async (
    reviewId: number,
    decision: ReviewDecisionPayload
  ) => {
    await decideReviewRequest(reviewId, decision);
    await refreshData(true);
  };

  const removeReview = async (reviewId: number) => {
    await deleteReviewRequest(reviewId);
    await refreshData(true);
  };

  const openCreateForm = () => {
    setEditingStudent(null);
    setShowStudentForm(true);
  };

  const openEditForm = (student: Student) => {
    setEditingStudent(student);
    setShowStudentForm(true);
  };

  const saveCompleted = () => {
    setShowStudentForm(false);
    setEditingStudent(null);
    void refreshData(true);
  };

  const deleteCompleted = async (studentId: string) => {
    setDeletingId(`loading:${studentId}`);
    try {
      await deleteStudent(studentId);
      setDeletingId(null);
      notifications.success("Estudante excluído.");
      void refreshData(true);
    } catch (error) {
      setDeletingId(null);
      notifications.error(error, "Não foi possível excluir o estudante.");
    }
  };

  const detail = sectionDetails[section];
  const unreadCount = inbox?.unreadCount ?? 0;
  const isStudentView = section === "students" || section === "reviews";
  const needsInitialLoad = loading && !metrics && students.length === 0;
  const handleLogin = (authenticatedUser: AuthUser) => {
    setSection("overview");
    setUser(authenticatedUser);
  };
  const handleLogout = async () => {
    try {
      await logout();
    } catch (error) {
      notifications.error(error, "Não foi possível encerrar a sessão no servidor.");
    } finally {
      setUser(null);
      setStudents([]);
      setReviews([]);
      setInbox(null);
      setMetrics(null);
      setSection("overview");
    }
  };

  if (!user) return <LoginForm onLoggedIn={handleLogin} />;

  return (
    <main className="dashboard-shell">
      <aside className="sidebar">
        <Link className="brand-lockup" href="/" aria-label="Educa, início">
          <span className="brand-mark">
            <GraduationCap size={22} aria-hidden="true" />
          </span>
          <span className="brand-name">
            educa<span>.</span>
            <small>PAINEL ADMINISTRATIVO</small>
          </span>
        </Link>

        <div className="workspace-switcher">
          <span className="workspace-avatar">
            {user.role === "teacher" ? "P" : initials(students[0]?.name ?? user.email)}
          </span>
          <span className="workspace-name">
            <strong>{user.role === "teacher" ? "Professor" : students[0]?.name ?? "Estudante"}</strong>
            <small>{user.role === "teacher" ? "Perfil de professor" : "Perfil de estudante"}</small>
          </span>
          {user.role === "teacher" && <ChevronDown size={15} aria-hidden="true" />}
        </div>

        {user.role === "teacher" && <>
        <div className="nav-section-label">MENU PRINCIPAL</div>
        <nav className="side-nav" aria-label="Navegação principal">
          <button
            className={section === "overview" ? "nav-item active" : "nav-item"}
            onClick={() => setSection("overview")}
          >
            <LayoutDashboard size={18} aria-hidden="true" />
            Visão geral
          </button>
          <button
            className={section === "students" ? "nav-item active" : "nav-item"}
            onClick={() => setSection("students")}
          >
            <UsersRound size={18} aria-hidden="true" />
            Estudantes
            <span className="nav-count">{students.length}</span>
          </button>
          <button
            className={section === "reviews" ? "nav-item active" : "nav-item"}
            onClick={() => setSection("reviews")}
          >
            <ClipboardList size={18} aria-hidden="true" />
            Revisões
            {reviews.length > 0 && (
              <span className="nav-count nav-count-alert">{reviews.length}</span>
            )}
          </button>
          <button
            className={section === "uploads" ? "nav-item active" : "nav-item"}
            onClick={() => setSection("uploads")}
          >
            <FileUp size={18} aria-hidden="true" />
            Importar dados
          </button>
          <button
            className={section === "terms" ? "nav-item active" : "nav-item"}
            onClick={() => setSection("terms")}
          >
            <CalendarCheck size={18} aria-hidden="true" />
            Semestres
          </button>
          <button
            className={section === "metrics" ? "nav-item active" : "nav-item"}
            onClick={() => setSection("metrics")}
          >
            <Activity size={18} aria-hidden="true" />
            Métricas
          </button>
        </nav>

        <div className="nav-section-label tools-label">PREFERÊNCIAS</div>
        <nav className="side-nav" aria-label="Preferências">
          <button className="nav-item" onClick={() => notifications.info("As definições estarão disponíveis em breve.")}>
            <Settings2 size={18} aria-hidden="true" />
            Definições
          </button>
          <button className="nav-item" onClick={() => notifications.info("Consulte a documentação da API em /docs.")}>
            <CircleHelp size={18} aria-hidden="true" />
            Ajuda e suporte
          </button>
        </nav>
        </>}

        {user.role === "student" && <>
        <div className="nav-section-label">MENU PRINCIPAL</div>
        <nav className="side-nav" aria-label="Navegação principal">
          <button
            className={section === "overview" ? "nav-item active" : "nav-item"}
            onClick={() => setSection("overview")}
          >
            <LayoutDashboard size={18} aria-hidden="true" />
            Visão geral
          </button>
          <button
            className={section === "inbox" ? "nav-item active" : "nav-item"}
            onClick={() => setSection("inbox")}
          >
            <Bell size={18} aria-hidden="true" />
            Notificações
            {unreadCount > 0 && (
              <span className="nav-count nav-count-alert">{unreadCount}</span>
            )}
          </button>
        </nav>
        </>}

        <Card className="sidebar-help-card">
          <Card.Content>
            <span className="help-card-icon">
              <Sparkles size={17} aria-hidden="true" />
            </span>
            <strong>Precisa de ajuda?</strong>
            <p>Consulte a documentação da API e os formatos de importação.</p>
            <a href={`${process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000"}/docs`} target="_blank" rel="noreferrer">
              Abrir documentação <ArrowRight size={14} aria-hidden="true" />
            </a>
          </Card.Content>
        </Card>

        <button className="profile-menu" onClick={() => void handleLogout()}>
          <span className="profile-avatar">{initials(user.email)}</span>
          <span>
            <strong>{user.email}</strong>
            <small>{user.role === "teacher" ? "Professor" : "Estudante"}</small>
          </span>
          <LogOut size={17} aria-hidden="true" />
        </button>
      </aside>

      <section className="main-panel">
        <header className="topbar">
          <div className="breadcrumb">
            <span>Workspace</span>
            <span className="breadcrumb-divider">/</span>
            <strong>{detail.title}</strong>
          </div>
          <div className="topbar-actions">
            {user.role === "student" && (
              <Badge.Anchor>
                <Button
                  isIconOnly
                  variant="secondary"
                  className="notification-bell"
                  aria-label={unreadCount ? `Notificações: ${unreadCount} não lidas` : "Notificações"}
                  onPress={() => setSection("inbox")}
                >
                  <Bell size={17} aria-hidden="true" />
                </Button>
                {unreadCount > 0 && (
                  <Badge color="danger" size="sm" placement="top-right">
                    {unreadCount > 9 ? "9+" : unreadCount}
                  </Badge>
                )}
              </Badge.Anchor>
            )}
            <span className="connection-status">
              <span className={loadError ? "status-dot offline" : "status-dot"} />
              {loadError ? "Verificar conexão" : "Sistema operacional"}
            </span>
            <Button
              variant="secondary"
              className="refresh-button"
              isPending={refreshing}
              onPress={() => void refreshData(true)}
            >
              <RefreshCw size={15} aria-hidden="true" />
              Atualizar
            </Button>
          </div>
        </header>

        <div className="page-content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">ACOMPANHAMENTO ACADÉMICO</p>
              <h1>{detail.title}</h1>
              <p>{detail.subtitle}</p>
            </div>
            <div className="heading-actions">
                {user.role === "teacher" && section === "students" && (
                <Button
                  className="primary-button"
                  onPress={openCreateForm}
                >
                  <Plus size={17} aria-hidden="true" />
                  Novo estudante
                </Button>
              )}
              {user.role === "teacher" && section === "uploads" && (
                <Button
                  className="primary-button"
                  onPress={() => document.getElementById("csv-upload")?.click()}
                >
                  <FileUp size={17} aria-hidden="true" />
                  Selecionar CSV
                </Button>
              )}
            </div>
          </div>

          {needsInitialLoad ? (
            <LoadingPanel />
          ) : section === "overview" ? (
            <div className="overview-content">
              <div className="metric-grid">
                {user.role === "student" ? (
                  students[0] ? (
                    <>
                      <StudentGradeCard
                        subject="math"
                        grade={students[0].math_grade}
                        review={reviews.find((review) => review.subject === "math")}
                        onRequest={submitReviewRequest}
                      />
                      <StudentGradeCard
                        subject="history"
                        grade={students[0].history_grade}
                        review={reviews.find((review) => review.subject === "history")}
                        onRequest={submitReviewRequest}
                        dark
                      />
                    </>
                  ) : null
                ) : <>
                <Card className="metric-card">
                  <Card.Content>
                    <div className="metric-topline">
                      <span className="metric-icon metric-icon-green">
                        <UsersRound size={19} aria-hidden="true" />
                      </span>
                      <span className="metric-period">
                        <ArrowUpRight size={14} aria-hidden="true" />
                        Base atual
                      </span>
                    </div>
                    <p className="metric-label">Estudantes processados</p>
                    <div className="metric-value-row">
                      <strong>{metrics?.total_alunos_processados ?? "—"}</strong>
                      <span>registos</span>
                    </div>
                    <div className="metric-footnote">
                      <span className="metric-footnote-dot" />
                      Total de boletins na base de dados
                    </div>
                  </Card.Content>
                </Card>
                <Card className="metric-card">
                  <Card.Content>
                    <div className="metric-topline">
                      <span className="metric-icon metric-icon-amber">
                        <ClipboardList size={19} aria-hidden="true" />
                      </span>
                      <span className="metric-period metric-period-warn">
                        Acompanhamento
                      </span>
                    </div>
                    <p className="metric-label">Revisões de boletins pendentes</p>
                    <div className="metric-value-row">
                      <strong>{metrics?.revisoes_pendentes ?? "—"}</strong>
                      <span>pedidos</span>
                    </div>
                    <div className="metric-footnote">
                      <span className="metric-footnote-dot metric-footnote-amber" />
                      Contagem reportada pelo endpoint de métricas
                    </div>
                  </Card.Content>
                </Card>
                <Card className="metric-card metric-card-dark">
                  <Card.Content>
                    <div className="metric-topline">
                      <span className="metric-icon metric-icon-white">
                        <BookOpenCheck size={19} aria-hidden="true" />
                      </span>
                      <span className="metric-period metric-period-light">
                        Tempo real
                      </span>
                    </div>
                    <p className="metric-label">Estudantes registados</p>
                    <div className="metric-value-row">
                      <strong>{students.length}</strong>
                      <span>perfis</span>
                    </div>
                    <button
                      className="metric-link"
                      onClick={() => setSection("students")}
                    >
                      Ver todos <ArrowRight size={14} aria-hidden="true" />
                    </button>
                  </Card.Content>
                </Card>
                </>}
              </div>

              {user.role === "student" && inbox && inbox.items.length > 0 && (
                <Card className="content-card review-card">
                  <Card.Header className="content-card-header">
                    <div>
                      <Card.Title>Notificações recentes</Card.Title>
                      <Card.Description>
                        Boletins e respostas do professor
                      </Card.Description>
                    </div>
                    <Button
                      variant="tertiary"
                      className="text-action"
                      onPress={() => setSection("inbox")}
                    >
                      Ver todas <ArrowRight size={15} aria-hidden="true" />
                    </Button>
                  </Card.Header>
                  <Card.Content>
                    <div className="review-list">
                      {inbox.items.slice(0, 3).map((item) => (
                        <button
                          type="button"
                          className="review-row inbox-preview-row"
                          key={item.id}
                          onClick={() => setSection("inbox")}
                        >
                          <span className="review-avatar">
                            <Bell size={15} aria-hidden="true" />
                          </span>
                          <span>
                            <strong>{item.title}</strong>
                            <small>{item.summary.split("\n")[0]}</small>
                          </span>
                          {item.readAt === null && (
                            <span className="inbox-unread-dot" aria-label="Não lida" />
                          )}
                        </button>
                      ))}
                    </div>
                  </Card.Content>
                </Card>
              )}

              {user.role === "teacher" && <>
              <div className="overview-grid">
                <Card className="content-card activity-card">
                  <Card.Header className="content-card-header">
                    <div>
                      <Card.Title>Estudantes recentes</Card.Title>
                      <Card.Description>
                        Registos mais recentes na base de dados
                      </Card.Description>
                    </div>
                    <Button
                      variant="tertiary"
                      className="text-action"
                      onPress={() => setSection("students")}
                    >
                      Ver estudantes <ArrowRight size={15} aria-hidden="true" />
                    </Button>
                  </Card.Header>
                  <Card.Content>
                    {students.length ? (
                      <div className="recent-list">
                        {students.slice(0, 5).map((student, index) => (
                          <div className="recent-row" key={student.student_id}>
                            <span className={`student-avatar avatar-tone-${index % 4}`}>
                              {initials(student.name)}
                            </span>
                            <span className="recent-name">
                              <strong>{student.name}</strong>
                              <small>{student.email}</small>
                            </span>
                            <span className="recent-grade">
                              <strong>
                                {formatGrade(
                                  (student.math_grade + student.history_grade) / 2
                                )}
                              </strong>
                              <small>média</small>
                            </span>
                            {student.review_requested ? (
                              <Chip color="warning" size="sm">
                                Revisão
                              </Chip>
                            ) : (
                              <Chip color="success" size="sm">
                                Regular
                              </Chip>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="compact-empty">
                        <p>A lista de estudantes aparecerá aqui quando existirem registos.</p>
                        <Button size="sm" onPress={openCreateForm}>
                          <Plus size={15} aria-hidden="true" /> Adicionar estudante
                        </Button>
                      </div>
                    )}
                  </Card.Content>
                </Card>

                <Card className="content-card review-card">
                  <Card.Header className="content-card-header">
                    <div>
                      <Card.Title>Pedidos de revisão</Card.Title>
                      <Card.Description>
                        Pedidos pendentes enviados pelos estudantes
                      </Card.Description>
                    </div>
                    <span className="review-count">{reviews.length}</span>
                  </Card.Header>
                  <Card.Content>
                    {reviews.length ? (
                      <div className="review-list">
                        {reviews.slice(0, 4).map((review) => (
                          <div className="review-row" key={review.id}>
                            <span className="review-avatar">
                              {initials(review.student_name)}
                            </span>
                            <span>
                              <strong>{review.student_name}</strong>
                              <small>
                                {subjectName(review.subject)} · {review.justification}
                              </small>
                            </span>
                            <ArrowDownRight
                              size={16}
                              aria-hidden="true"
                              className="review-arrow"
                            />
                          </div>
                        ))}
                        <Button
                          variant="secondary"
                          className="review-all-button"
                          onPress={() => setSection("reviews")}
                        >
                          Abrir fila de revisões
                          <ArrowRight size={15} aria-hidden="true" />
                        </Button>
                      </div>
                    ) : (
                      <div className="no-reviews">
                        <span>
                          <Check size={20} aria-hidden="true" />
                        </span>
                        <strong>Tudo em dia</strong>
                        <p>Não existem pedidos de revisão pendentes.</p>
                      </div>
                    )}
                  </Card.Content>
                </Card>
              </div>

              <Card className="import-banner">
                <Card.Content>
                  <span className="import-banner-icon">
                    <FileUp size={20} aria-hidden="true" />
                  </span>
                  <span className="import-banner-copy">
                    <strong>Atualize a sua base de dados</strong>
                    <small>Importe as notas da turma a partir de um ficheiro CSV.</small>
                  </span>
                  <Button
                    variant="secondary"
                    onPress={() => setSection("uploads")}
                  >
                    Importar CSV <ArrowRight size={15} aria-hidden="true" />
                  </Button>
                </Card.Content>
              </Card>
              </>}
            </div>
          ) : section === "metrics" && user.role === "teacher" ? (
            <MetricsPanel />
          ) : section === "terms" && user.role === "teacher" ? (
            <TermManager />
          ) : section === "inbox" && user.role === "student" ? (
            <div className="list-content">
              <StudentInbox inbox={inbox} onChanged={setInbox} />
            </div>
          ) : isStudentView ? (
            <div className="list-content">
              <Card className="content-card list-card">
                <Card.Header className="list-card-header">
                  <div>
                    <Card.Title>
                      {section === "reviews"
                        ? "Fila de revisões"
                        : "Todos os estudantes"}
                    </Card.Title>
                    <Card.Description>
                      {section === "reviews"
                        ? `${reviews.length} pedido${reviews.length === 1 ? "" : "s"} pendente${reviews.length === 1 ? "" : "s"}`
                        : `${students.length} registo${students.length === 1 ? "" : "s"} encontrado${students.length === 1 ? "" : "s"}`}
                    </Card.Description>
                  </div>
                  <div className="list-toolbar">
                    <div className="search-control">
                      <Search size={16} aria-hidden="true" />
                      <Input
                        aria-label={section === "reviews" ? "Pesquisar pedidos de revisão" : "Pesquisar estudantes"}
                        className="student-search"
                        placeholder={section === "reviews" ? "Pesquisar pedidos..." : "Pesquisar..."}
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                      />
                    </div>
                    <Button
                      variant="secondary"
                      isIconOnly
                      aria-label="Atualizar lista"
                      isPending={refreshing}
                      onPress={() => void refreshData(true)}
                    >
                      <ListFilter size={16} aria-hidden="true" />
                    </Button>
                  </div>
                </Card.Header>
                {section === "reviews" ? (
                  <Card.Content className="review-queue-content">
                    {loading && !reviews.length ? (
                      <LoadingPanel />
                    ) : filteredReviews.length ? (
                      filteredReviews.map((review) => (
                        <TeacherReviewCard
                          key={review.id}
                          review={review}
                          onDecide={decideReview}
                          onDelete={removeReview}
                        />
                      ))
                    ) : (
                      <div className="no-reviews">
                        <span><Check size={20} aria-hidden="true" /></span>
                        <strong>Nenhum pedido pendente</strong>
                        <p>Os novos pedidos enviados pelos estudantes aparecerão aqui.</p>
                      </div>
                    )}
                  </Card.Content>
                ) : (
                  <>
                    {showStudentForm && (
                      <div className="form-container">
                        <StudentForm
                          key={editingStudent?.student_id ?? "new-student"}
                          student={editingStudent}
                          onCancel={() => {
                            setShowStudentForm(false);
                            setEditingStudent(null);
                          }}
                          onSaved={saveCompleted}
                        />
                      </div>
                    )}
                    <Card.Content className="table-content">
                      {loading && !students.length ? (
                        <LoadingPanel />
                      ) : (
                        <StudentTable
                          students={filteredStudents}
                          onEdit={openEditForm}
                          onDelete={setDeletingId}
                          deletingId={deletingId}
                          onCancelDelete={() => setDeletingId(null)}
                          onConfirmDelete={(studentId) => void deleteCompleted(studentId)}
                          readOnly={user.role === "student"}
                        />
                      )}
                    </Card.Content>
                    <div className="table-footer">
                      <span>
                        A mostrar <strong>{filteredStudents.length}</strong> de{" "}
                        <strong>{students.length}</strong> registos
                      </span>
                      <span>Dados sincronizados com a API</span>
                    </div>
                  </>
                )}
              </Card>
            </div>
          ) : (
            <div className="upload-page-content">
              <div className="upload-intro">
                <div className="upload-intro-icon">
                  <FileUp size={22} aria-hidden="true" />
                </div>
                <div>
                  <h2>Importação em lote</h2>
                  <p>
                    Envie um ficheiro CSV para criar boletins, atualizar notas e
                    identificar registos inválidos.
                  </p>
                </div>
              </div>
              <UploadForm onUploaded={() => void refreshData(true)} />
              <div className="csv-guide">
                <div className="csv-guide-heading">
                  <div>
                    <p className="eyebrow">FORMATO DO FICHEIRO</p>
                    <h3>Prepare o seu CSV</h3>
                  </div>
                  <Chip color="accent">CSV UTF-8</Chip>
                </div>
                <p>
                  A primeira linha deve conter os nomes das colunas. Cada linha
                  seguinte representa um estudante.
                </p>
                <div className="csv-columns">
                  {["id_aluno", "nome", "email", "nota_matematica", "nota_historia"].map(
                    (column) => (
                      <code key={column}>{column}</code>
                    )
                  )}
                </div>
                <div className="csv-note">
                  <ShieldCheck size={16} aria-hidden="true" />
                  Registos com ID e notas iguais aos existentes são ignorados
                  automaticamente pela cache.
                </div>
              </div>
            </div>
          )}

          <footer className="page-footer">
            <span>© 2026 Educa · Plataforma de gestão académica</span>
            <span>
              <span className="footer-status-dot" />
              API REST conectada
            </span>
          </footer>
        </div>
      </section>
    </main>
  );
}
