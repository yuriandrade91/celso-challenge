import type { AuthUser } from "@/lib/auth-types";
import type { DemoProfile } from "@/lib/auth-types";
export type { AuthUser, DemoProfile } from "@/lib/auth-types";

export type BackendMetrics = {
  total_alunos_processados: number;
  revisoes_pendentes: number;
};

export type UploadReport = {
  execution_id: string;
  total_linhas: number;
  processados: number;
  ignorados_cache: number;
  atualizados: number;
  falhas: number;
  falhas_validacao: number;
  falhas_processamento: number;
  duplicados_ignorados: number;
  fallbacks_llm: number;
  tokens_gastos: number;
  custo_estimado_usd: number;
  tempo_total_ms: number;
  tempo_medio_processamento_ms: number;
  tempo_p95_processamento_ms: number;
  em_processamento: number;
  orcamento_excedido: boolean;
  summary_provider: string;
  notification_provider: string;
  erros: { linha: number; campo: string; mensagem: string }[];
};

export type Student = {
  student_id: string;
  name: string;
  email: string;
  math_grade: number;
  history_grade: number;
  review_requested: boolean;
};

export type StudentPayload = Omit<Student, "student_id" | "review_requested">;

export type ReviewRequest = {
  id: number;
  student_id: string;
  student_name: string;
  student_email: string;
  subject: "math" | "history";
  justification: string;
  original_grade: number;
  status: "pending" | "adjusted" | "cancelled";
  teacher_response: string | null;
  adjusted_grade: number | null;
  created_at: string;
  decided_at: string | null;
};

export type ReviewDecisionPayload =
  | {
      action: "adjusted";
      teacher_response: string;
      adjusted_grade: number;
    }
  | {
      action: "cancelled";
      teacher_response: string;
    };

type Pagination = {
  pageNumber: number;
  pageSize: number;
  totalRecords: number;
  totalPages: number;
  hasNextPage: boolean;
  hasPreviousPage: boolean;
};

type ApiError = {
  field: string | null;
  code: string;
  message: string;
};

type ApiResponse<T> = {
  success: boolean;
  data: T;
  pagination: Pagination | null;
  errors: ApiError[] | null;
};

type ApiStudent = {
  studentId: string;
  name: string;
  email: string;
  mathGrade: number;
  historyGrade: number;
  reviewRequested: boolean;
};

type ApiMetrics = {
  totalAlunosProcessados: number;
  revisoesPendentes: number;
};

type ApiReviewRequest = {
  id: number;
  studentId: string;
  studentName: string;
  studentEmail: string;
  subject: "math" | "history";
  justification: string;
  originalGrade: number;
  status: "pending" | "adjusted" | "cancelled";
  teacherResponse: string | null;
  adjustedGrade: number | null;
  createdAt: string;
  decidedAt: string | null;
};

type ApiUploadReport = {
  executionId: string;
  totalLinhas: number;
  processados: number;
  ignoradosCache: number;
  atualizados: number;
  falhas: number;
  falhasValidacao: number;
  falhasProcessamento: number;
  duplicadosIgnorados: number;
  fallbacksLlm: number;
  tokensGastos: number;
  custoEstimadoUsd: number;
  tempoTotalMs: number;
  tempoMedioProcessamentoMs: number;
  tempoP95ProcessamentoMs: number;
  emProcessamento: number;
  orcamentoExcedido: boolean;
  summaryProvider: string;
  notificationProvider: string;
  erros: { linha: number; campo: string; mensagem: string }[];
};

const backendUrl = (
  process.env.BACKEND_URL ??
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "http://127.0.0.1:8000"
).replace(/\/+$/, "");

export function backendEndpoint(path: string): string {
  return `${backendUrl}${path}`;
}

function frontendApiEndpoint(path: string): string {
  return `/api/backend${path}`;
}

async function readJson<T>(response: Response): Promise<T> {
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(getErrorMessage(body, response.status));
  }
  return body as T;
}

export function getErrorMessage(body: unknown, status: number): string {
  if (typeof body === "object" && body !== null && "errors" in body) {
    const errors = body.errors;
    if (Array.isArray(errors)) {
      const message = errors
        .map((error) =>
          typeof error === "object" &&
          error !== null &&
          "message" in error &&
          typeof error.message === "string"
            ? error.message
            : "A solicitação não pode ser concluída."
        )
        .join(" ");
      if (message) return message;
    }
  }
  return `O backend respondeu com HTTP ${status}.`;
}

async function readApiResponse<T>(
  response: Response
): Promise<ApiResponse<T>> {
  const result = await readJson<ApiResponse<T>>(response);
  if (
    typeof result !== "object" ||
    result === null ||
    !("data" in result)
  ) {
    throw new Error("O backend devolveu uma resposta num formato inválido.");
  }
  if (result.success !== true) {
    throw new Error(getErrorMessage(result, response.status));
  }
  return result;
}

async function authenticatedFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const response = await fetch(frontendApiEndpoint(path), {
    ...init,
    cache: "no-store",
  });
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event("educa:session-expired"));
  }
  return response;
}

export async function login(profile: DemoProfile): Promise<AuthUser> {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile }),
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(getErrorMessage(body, response.status));
  }
  if (
    typeof body !== "object" ||
    body === null ||
    !("user" in body) ||
    typeof body.user !== "object" ||
    body.user === null ||
    !("email" in body.user) ||
    typeof body.user.email !== "string" ||
    !("role" in body.user) ||
    (body.user.role !== "student" && body.user.role !== "teacher") ||
    !("studentId" in body.user) ||
    (typeof body.user.studentId !== "string" && body.user.studentId !== null)
  ) {
    throw new Error("O servidor devolveu uma resposta de login inválida.");
  }
  return {
    email: body.user.email,
    role: body.user.role,
    studentId: body.user.studentId,
  };
}

export async function logout(): Promise<void> {
  const response = await fetch("/api/auth/logout", { method: "POST" });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(getErrorMessage(body, response.status));
  }
}

function fromApiStudent(student: ApiStudent): Student {
  return {
    student_id: student.studentId,
    name: student.name,
    email: student.email,
    math_grade: student.mathGrade,
    history_grade: student.historyGrade,
    review_requested: student.reviewRequested,
  };
}

function toApiStudent(
  payload: StudentPayload
): Omit<ApiStudent, "studentId" | "reviewRequested"> {
  return {
    name: payload.name,
    email: payload.email,
    mathGrade: payload.math_grade,
    historyGrade: payload.history_grade,
  };
}

export async function fetchMetrics(): Promise<BackendMetrics> {
  const { data } = await readApiResponse<ApiMetrics>(
    await authenticatedFetch("/metrics?recent=0", { cache: "no-store" })
  );
  return {
    total_alunos_processados: data.totalAlunosProcessados,
    revisoes_pendentes: data.revisoesPendentes,
  };
}

export type ExecutionRecord = {
  executionId: string | null;
  status: "running" | "completed" | "failed";
  erro: string | null;
  createdAt: string;
  totalLinhas: number;
  processados: number;
  falhas: number;
  ignoradosCache: number;
  falhasValidacao: number;
  falhasProcessamento: number;
  duplicadosIgnorados: number;
  emProcessamento: number;
  fallbacksLlm: number;
  orcamentoExcedido: boolean;
  tokensGastos: number;
  custoEstimadoUsd: number;
  tempoTotalMs: number;
  tempoMedioProcessamentoMs: number;
  tempoP95ProcessamentoMs: number;
  summaryProvider: string;
  notificationProvider: string;
};

type DispatcherMetrics = {
  execucoes: number;
  execucoesEmAndamento: number;
  execucoesComFalha: number;
  ultimaExecucaoEm: string | null;
  linhasRecebidas: number;
  alunosProcessados: number;
  falhas: number;
  falhasValidacao: number;
  falhasProcessamento: number;
  duplicadosIgnorados: number;
  ignoradosCache: number;
  taxaFalhaProcessamento: number;
  taxaCache: number;
  fallbacksLlm: number;
  taxaFallback: number;
  execucoesComOrcamentoExcedido: number;
  tokensGastos: number;
  custoEstimadoUsd: number;
  custoMedioPorAlunoUsd: number;
  tempoMedioProcessamentoMs: number;
  piorP95ProcessamentoMs: number;
  tempoMedioPipelineMs: number;
};

export type CircuitState = {
  estado: "closed" | "open" | "half_open";
  falhasConsecutivas: number;
};

type OperationalMetrics = {
  desde: string;
  httpRequisicoes: number;
  httpErros4xx: number;
  httpErros5xx: number;
  httpTaxaErro5xx: number;
  httpLatenciaP50Ms: number;
  httpLatenciaP95Ms: number;
  llmRetries: number;
  llmFallbacks: number;
  llmThrottles: number;
  promptsTruncados: number;
  orcamentosEsgotados: number;
  notificacoesEnviadas: number;
  alunosComFalha: number;
  pedidosBloqueadosRateLimit: number;
  circuitoLlm: CircuitState;
  circuitoSmtp: CircuitState;
};

export type DashboardMetrics = {
  totalAlunosProcessados: number;
  revisoesPendentes: number;
  dispatcher: DispatcherMetrics;
  operacional: OperationalMetrics;
  ultimasExecucoes: ExecutionRecord[];
  dadosEmulados: boolean;
};

export async function fetchDashboardMetrics(recent = 8): Promise<DashboardMetrics> {
  const { data } = await readApiResponse<DashboardMetrics>(
    await authenticatedFetch(`/metrics?recent=${recent}`)
  );
  return data;
}

export async function fetchStudents(): Promise<Student[]> {
  const fetchPage = async (pageNumber: number) =>
    readApiResponse<ApiStudent[]>(
      await authenticatedFetch(
        `/students/?pageNumber=${pageNumber}&pageSize=100`,
        { cache: "no-store" }
      )
    );
  const firstPage = await fetchPage(1);
  if (!firstPage.pagination || !firstPage.pagination.hasNextPage) {
    return firstPage.data.map(fromApiStudent);
  }
  const remainingPages = await Promise.all(
    Array.from(
      { length: firstPage.pagination.totalPages - 1 },
      (_, index) => fetchPage(index + 2)
    )
  );
  return [firstPage, ...remainingPages].flatMap((page) =>
    page.data.map(fromApiStudent)
  );
}

export async function fetchOwnStudent(): Promise<Student> {
  const response = await readApiResponse<ApiStudent>(
    await authenticatedFetch("/students/me", { cache: "no-store" })
  );
  return fromApiStudent(response.data);
}

function fromApiReview(review: ApiReviewRequest): ReviewRequest {
  return {
    id: review.id,
    student_id: review.studentId,
    student_name: review.studentName,
    student_email: review.studentEmail,
    subject: review.subject,
    justification: review.justification,
    original_grade: review.originalGrade,
    status: review.status,
    teacher_response: review.teacherResponse,
    adjusted_grade: review.adjustedGrade,
    created_at: review.createdAt,
    decided_at: review.decidedAt,
  };
}

export async function fetchOwnReviews(): Promise<ReviewRequest[]> {
  const { data } = await readApiResponse<ApiReviewRequest[]>(
    await authenticatedFetch("/reviews/me", { cache: "no-store" })
  );
  return data.map(fromApiReview);
}

export async function fetchPendingReviews(): Promise<ReviewRequest[]> {
  const { data } = await readApiResponse<ApiReviewRequest[]>(
    await authenticatedFetch("/reviews/", { cache: "no-store" })
  );
  return data.map(fromApiReview);
}

export async function createReviewRequest(
  subject: ReviewRequest["subject"],
  justification: string
): Promise<ReviewRequest> {
  const { data } = await readApiResponse<ApiReviewRequest>(
    await authenticatedFetch("/reviews/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject, justification }),
    })
  );
  return fromApiReview(data);
}

export async function decideReviewRequest(
  reviewId: number,
  decision: ReviewDecisionPayload
): Promise<ReviewRequest> {
  const { data } = await readApiResponse<ApiReviewRequest>(
    await authenticatedFetch(
      `/reviews/${encodeURIComponent(reviewId)}/decision`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: decision.action,
          teacherResponse: decision.teacher_response,
          ...(decision.action === "adjusted"
            ? { adjustedGrade: decision.adjusted_grade }
            : {}),
        }),
      }
    )
  );
  return fromApiReview(data);
}

export async function deleteReviewRequest(reviewId: number): Promise<void> {
  const response = await authenticatedFetch(
    `/reviews/${encodeURIComponent(reviewId)}`,
    { method: "DELETE" }
  );
  await readApiResponse<null>(response);
}

export async function fetchStudentsUnderReview(): Promise<Student[]> {
  const { data } = await readApiResponse<ApiStudent[]>(
    await authenticatedFetch("/students/under-review", { cache: "no-store" })
  );
  return data.map(fromApiStudent);
}

export async function createStudent(payload: StudentPayload): Promise<Student> {
  const response = await readApiResponse<ApiStudent>(
    await authenticatedFetch("/students/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toApiStudent(payload)),
    })
  );
  return fromApiStudent(response.data);
}

export async function updateStudent(
  studentId: string,
  payload: Partial<
    Pick<Student, "math_grade" | "history_grade" | "review_requested">
  >
): Promise<Student> {
  const response = await readApiResponse<ApiStudent>(
    await authenticatedFetch(`/students/${encodeURIComponent(studentId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...(payload.math_grade !== undefined
          ? { mathGrade: payload.math_grade }
          : {}),
        ...(payload.history_grade !== undefined
          ? { historyGrade: payload.history_grade }
          : {}),
        ...(payload.review_requested !== undefined
          ? { reviewRequested: payload.review_requested }
          : {}),
      }),
    })
  );
  return fromApiStudent(response.data);
}

export async function deleteStudent(studentId: string): Promise<void> {
  const response = await authenticatedFetch(
    `/students/${encodeURIComponent(studentId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    await readJson<unknown>(response);
  } else {
    await readApiResponse<null>(response);
  }
}

export async function uploadCsv(file: File): Promise<UploadReport> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await authenticatedFetch("/upload", {
    method: "POST",
    body: formData,
  });
  const { data } = await readApiResponse<ApiUploadReport>(response);
  return {
    execution_id: data.executionId,
    total_linhas: data.totalLinhas,
    processados: data.processados,
    ignorados_cache: data.ignoradosCache,
    atualizados: data.atualizados,
    falhas: data.falhas,
    falhas_validacao: data.falhasValidacao,
    falhas_processamento: data.falhasProcessamento,
    duplicados_ignorados: data.duplicadosIgnorados,
    fallbacks_llm: data.fallbacksLlm,
    tokens_gastos: data.tokensGastos,
    custo_estimado_usd: data.custoEstimadoUsd,
    tempo_total_ms: data.tempoTotalMs,
    tempo_medio_processamento_ms: data.tempoMedioProcessamentoMs,
    tempo_p95_processamento_ms: data.tempoP95ProcessamentoMs,
    em_processamento: data.emProcessamento,
    orcamento_excedido: data.orcamentoExcedido,
    summary_provider: data.summaryProvider,
    notification_provider: data.notificationProvider,
    erros: data.erros,
  };
}

type TermStatus = "open" | "closing" | "closed";

export type AcademicTerm = {
  id: number;
  code: string;
  name: string;
  startDate: string;
  endDate: string;
  status: TermStatus;
  closedAt: string | null;
  closedBy: string | null;
  createdAt: string;
  entregas: {
    alunosNotificados: number;
    emailsPendentes: number;
    notificacoesLidas: number;
  };
};

export type TermPayload = Pick<
  AcademicTerm,
  "code" | "name" | "startDate" | "endDate"
>;

export type TermCloseReport = {
  termId: number;
  executionId: string;
  totalAlunos: number;
  notificados: number;
  jaNotificados: number;
  resumosReaproveitados: number;
  falhas: number;
  fallbacksLlm: number;
  orcamentoExcedido: boolean;
  tokensGastos: number;
  custoEstimadoUsd: number;
  tempoTotalMs: number;
  summaryProvider: string;
  notificationProvider: string;
  erros: { linha: number; campo: string; mensagem: string }[];
};

export type TermDelivery = {
  notificationId: number;
  studentId: string;
  studentName: string;
  studentEmail: string;
  mathGrade: number;
  historyGrade: number;
  summarySource: "llm" | "template" | "cache";
  emailStatus: "pending" | "sent" | "failed";
  readAt: string | null;
  createdAt: string;
};

export type StudentNotification = {
  id: number;
  kind: "term_report" | "review_decision" | "grade_update";
  termId: number | null;
  termCode: string | null;
  termName: string | null;
  reviewId: number | null;
  title: string;
  summary: string;
  mathGrade: number;
  historyGrade: number;
  readAt: string | null;
  createdAt: string;
};

export type StudentInbox = {
  unreadCount: number;
  items: StudentNotification[];
};

const jsonHeaders = { "Content-Type": "application/json" };

export async function fetchTerms(): Promise<AcademicTerm[]> {
  const { data } = await readApiResponse<AcademicTerm[]>(
    await authenticatedFetch("/terms")
  );
  return data;
}

export async function createTerm(payload: TermPayload): Promise<AcademicTerm> {
  const { data } = await readApiResponse<AcademicTerm>(
    await authenticatedFetch("/terms", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    })
  );
  return data;
}

export async function updateTerm(
  termId: number,
  payload: Partial<Omit<TermPayload, "code">>
): Promise<AcademicTerm> {
  const { data } = await readApiResponse<AcademicTerm>(
    await authenticatedFetch(`/terms/${encodeURIComponent(termId)}`, {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    })
  );
  return data;
}

export async function deleteTerm(termId: number): Promise<void> {
  await readApiResponse<null>(
    await authenticatedFetch(`/terms/${encodeURIComponent(termId)}`, {
      method: "DELETE",
    })
  );
}

export async function closeTerm(termId: number): Promise<TermCloseReport> {
  const { data } = await readApiResponse<TermCloseReport>(
    await authenticatedFetch(`/terms/${encodeURIComponent(termId)}/close`, {
      method: "POST",
    })
  );
  return data;
}

export async function fetchTermDeliveries(
  termId: number
): Promise<TermDelivery[]> {
  const { data } = await readApiResponse<TermDelivery[]>(
    await authenticatedFetch(
      `/terms/${encodeURIComponent(termId)}/notifications`
    )
  );
  return data;
}

export async function fetchOwnNotifications(): Promise<StudentInbox> {
  const { data } = await readApiResponse<StudentInbox>(
    await authenticatedFetch("/notifications/me")
  );
  return data;
}

export async function markNotificationRead(
  notificationId: number
): Promise<void> {
  await readApiResponse<null>(
    await authenticatedFetch(
      `/notifications/${encodeURIComponent(notificationId)}/read`,
      { method: "PATCH" }
    )
  );
}

export async function markAllNotificationsRead(): Promise<number> {
  const { data } = await readApiResponse<number>(
    await authenticatedFetch("/notifications/me/read-all", { method: "POST" })
  );
  return data;
}
