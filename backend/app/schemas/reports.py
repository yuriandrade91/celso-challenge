from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.responses import ApiModel


class AlunoCSV(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id_aluno: str = Field(json_schema_extra={"format": "uuid"})
    nome: str = Field(max_length=120)
    email: EmailStr
    nota_matematica: float = Field(ge=0, le=20)
    nota_historia: float = Field(ge=0, le=20)

    @field_validator("id_aluno", "nome")
    @classmethod
    def required_text(cls, value: str) -> str:
        if not value:
            raise ValueError("Este campo não pode estar vazio.")
        return value

    @field_validator("id_aluno")
    @classmethod
    def student_id_must_be_uuid(cls, value: str) -> str:
        try:
            return str(UUID(value))
        except ValueError as error:
            raise ValueError("O ID do estudante deve ser um UUID válido.") from error


class RowValidationError(ApiModel):
    linha: int
    campo: str
    mensagem: str


class Metrics(ApiModel):
    total_alunos_processados: int
    revisoes_pendentes: int
    dispatcher: "DispatcherMetrics"
    operacional: "OperationalMetrics"
    ultimas_execucoes: list["ExecutionRecord"]
    dados_emulados: bool = False


class UploadReport(ApiModel):
    execution_id: str = ""
    total_linhas: int = 0
    processados: int = 0
    ignorados_cache: int = 0
    atualizados: int = 0
    falhas: int = 0
    falhas_validacao: int = 0
    falhas_processamento: int = 0
    duplicados_ignorados: int = 0
    em_processamento: int = 0
    fallbacks_llm: int = 0
    orcamento_excedido: bool = False
    tokens_gastos: int = 0
    custo_estimado_usd: float = 0
    tempo_total_ms: float = 0
    tempo_medio_processamento_ms: float = 0
    tempo_p95_processamento_ms: float = 0
    summary_provider: str = "mock"
    notification_provider: str = "mock"
    erros: list[RowValidationError] = Field(default_factory=list)


class ExecutionRecord(ApiModel):
    execution_id: str | None
    status: str
    erro: str | None = None
    created_at: datetime
    total_linhas: int
    processados: int
    falhas: int
    falhas_validacao: int
    falhas_processamento: int
    duplicados_ignorados: int
    ignorados_cache: int
    em_processamento: int
    fallbacks_llm: int
    orcamento_excedido: bool
    tokens_gastos: int
    custo_estimado_usd: float
    tempo_total_ms: float
    tempo_medio_processamento_ms: float
    tempo_p95_processamento_ms: float
    summary_provider: str
    notification_provider: str


class DispatcherMetrics(ApiModel):
    """Agregado persistido de todas as execuções concluídas."""

    execucoes: int
    execucoes_em_andamento: int
    execucoes_com_falha: int
    ultima_execucao_em: datetime | None
    linhas_recebidas: int
    alunos_processados: int
    falhas: int
    falhas_validacao: int
    falhas_processamento: int
    duplicados_ignorados: int
    ignorados_cache: int
    taxa_falha_processamento: float
    taxa_cache: float
    fallbacks_llm: int
    taxa_fallback: float
    execucoes_com_orcamento_excedido: int
    tokens_gastos: int
    custo_estimado_usd: float
    custo_medio_por_aluno_usd: float
    tempo_medio_processamento_ms: float
    pior_p95_processamento_ms: float
    tempo_medio_pipeline_ms: float


class CircuitState(ApiModel):
    estado: str
    falhas_consecutivas: int


class OperationalMetrics(ApiModel):
    """Sinais voláteis deste processo, desde o arranque."""

    desde: datetime
    http_requisicoes: int
    http_erros_4xx: int
    http_erros_5xx: int
    http_taxa_erro_5xx: float
    http_latencia_p50_ms: float
    http_latencia_p95_ms: float
    llm_retries: int
    llm_fallbacks: int
    llm_throttles: int
    prompts_truncados: int
    orcamentos_esgotados: int
    notificacoes_enviadas: int
    alunos_com_falha: int
    pedidos_bloqueados_rate_limit: int
    circuito_llm: CircuitState
    circuito_smtp: CircuitState


class AsyncUploadAccepted(ApiModel):
    execution_id: str
    status: str


Metrics.model_rebuild()
