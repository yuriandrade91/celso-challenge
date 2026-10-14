"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Button, Card, Chip, Spinner, Table } from "@heroui/react";
import { RefreshCw } from "lucide-react";
import {
  fetchDashboardMetrics,
  type CircuitState,
  type DashboardMetrics,
  type ExecutionRecord,
} from "@/lib/backend";
import { ms, percent, time, usd } from "@/lib/format";

const REFRESH_INTERVAL_MS = 15_000;


const circuitLabels: Record<CircuitState["estado"], string> = {
  closed: "fechado",
  open: "aberto",
  half_open: "semiaberto",
};

function Kpi({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
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

function Circuit({ name, state }: { name: string; state: CircuitState }) {
  return (
    <Chip
      size="sm"
      color={state.estado === "closed" ? "success" : state.estado === "open" ? "danger" : "warning"}
    >
      {name}: {circuitLabels[state.estado]}
      {state.falhasConsecutivas > 0 && ` (${state.falhasConsecutivas} falhas)`}
    </Chip>
  );
}

const executionStatus: Record<
  ExecutionRecord["status"],
  { label: string; color: "success" | "danger" | "warning" }
> = {
  completed: { label: "Concluída", color: "success" },
  failed: { label: "Falhou", color: "danger" },
  running: { label: "Em curso", color: "warning" },
};

const executionDate = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

function Count({ value, tone }: { value: number; tone?: "danger" | "warning" }) {
  return (
    <span className={`execution-count${value > 0 && tone ? ` execution-count-${tone}` : ""}${value === 0 ? " execution-count-zero" : ""}`}>
      {value.toLocaleString("pt-BR")}
    </span>
  );
}

function ExecutionHistory({ executions }: { executions: ExecutionRecord[] }) {
  return (
    <Table className="execution-table">
      <Table.ScrollContainer>
        <Table.Content aria-label="Últimas execuções" className="min-w-[760px]">
          <Table.Header>
            <Table.Column isRowHeader>EXECUÇÃO</Table.Column>
            <Table.Column>ESTADO</Table.Column>
            <Table.Column className="execution-numeric">ENVIADOS</Table.Column>
            <Table.Column className="execution-numeric">CACHE</Table.Column>
            <Table.Column className="execution-numeric">FALHAS</Table.Column>
            <Table.Column className="execution-numeric">TEMPLATE</Table.Column>
            <Table.Column className="execution-numeric">CUSTO</Table.Column>
            <Table.Column className="execution-numeric">POR ALUNO</Table.Column>
          </Table.Header>
          <Table.Body>
            {executions.map((execution) => {
              const status = executionStatus[execution.status];
              const failed = execution.status === "failed";
              const isDemo = execution.summaryProvider === "demo";
              return (
                <Table.Row key={execution.executionId ?? execution.createdAt}>
                  <Table.Cell>
                    <span className="execution-when">
                      <strong>{executionDate.format(new Date(execution.createdAt))}</strong>
                      {failed && execution.erro ? (
                        <small className="execution-error" title={execution.erro}>
                          {execution.erro}
                        </small>
                      ) : (
                        <small>
                          {execution.totalLinhas.toLocaleString("pt-BR")} linhas
                          {isDemo && <span className="execution-demo">demo</span>}
                        </small>
                      )}
                    </span>
                  </Table.Cell>
                  <Table.Cell>
                    <Chip size="sm" color={status.color}>
                      {status.label}
                    </Chip>
                  </Table.Cell>
                  <Table.Cell className="execution-numeric">
                    <Count value={execution.processados} />
                  </Table.Cell>
                  <Table.Cell className="execution-numeric">
                    <Count value={execution.ignoradosCache} />
                  </Table.Cell>
                  <Table.Cell className="execution-numeric">
                    <span
                      title={`${execution.falhasValidacao} de validação · ${execution.falhasProcessamento} de processamento`}
                    >
                      <Count
                        value={execution.falhas}
                        tone={execution.falhasProcessamento > 0 ? "danger" : "warning"}
                      />
                    </span>
                  </Table.Cell>
                  <Table.Cell className="execution-numeric">
                    <Count value={execution.fallbacksLlm} tone="warning" />
                  </Table.Cell>
                  <Table.Cell className="execution-numeric">
                    {failed ? "—" : usd(execution.custoEstimadoUsd, 4)}
                  </Table.Cell>
                  <Table.Cell className="execution-numeric">
                    {failed ? "—" : ms(execution.tempoMedioProcessamentoMs)}
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

export default function MetricsPanel() {
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    const poll = () => {
      fetchDashboardMetrics()
        .then((next) => {
          if (!active) return;
          setMetrics(next);
          setUpdatedAt(new Date());
          setError(null);
        })
        .catch((reason: unknown) => {
          if (!active) return;
          setError(
            reason instanceof Error ? reason.message : "Não foi possível carregar as métricas."
          );
        });
    };
    poll();
    // Atualiza só com a aba visível, para não gerar tráfego à toa.
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") poll();
    }, REFRESH_INTERVAL_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [refreshKey]);

  if (!metrics) {
    return error ? (
      <p className="metrics-error">{error}</p>
    ) : (
      <Spinner size="sm" aria-label="A carregar métricas" />
    );
  }

  const { dispatcher: d, operacional: o } = metrics;

  return (
    <div className="metrics-page">
      <div className="metrics-toolbar">
        <span>
          {updatedAt && `Atualizado às ${updatedAt.toLocaleTimeString("pt-BR")}`} ·
          atualização automática a cada {REFRESH_INTERVAL_MS / 1000} s
        </span>
        {metrics.dadosEmulados && (
          <Chip
            size="sm"
            color="warning"
            title="ENABLE_DEMO_METRICS=true: histórico e tráfego simulados somam-se aos dados reais"
          >
            Inclui dados emulados
          </Chip>
        )}
        {error && <span className="metrics-error">{error}</span>}
        <Button size="sm" variant="secondary" onPress={() => setRefreshKey((key) => key + 1)}>
          <RefreshCw size={14} aria-hidden="true" />
          Atualizar
        </Button>
      </div>

      <Card className="content-card metrics-card">
        <Card.Content>
          <p className="eyebrow">RELATÓRIO DE EXECUÇÃO</p>
          <h3>Boletins enviados ({d.execucoes} execuções)</h3>
          <div className="metrics-grid">
            <Kpi
              label="Alunos processados"
              value={d.alunosProcessados}
              hint={`${d.linhasRecebidas} linhas recebidas`}
            />
            <Kpi
              label="Falhas"
              value={d.falhas}
              hint={`${d.falhasValidacao} validação · ${d.falhasProcessamento} processamento`}
              tone={d.falhasProcessamento > 0 ? "danger" : undefined}
            />
            <Kpi
              label="Custo estimado de tokens"
              value={usd(d.custoEstimadoUsd)}
              hint={`${d.tokensGastos.toLocaleString("pt-BR")} tokens`}
            />
            <Kpi
              label="Tempo médio por aluno"
              value={ms(d.tempoMedioProcessamentoMs)}
              hint={`pior p95 ${ms(d.piorP95ProcessamentoMs)}`}
            />
          </div>
        </Card.Content>
      </Card>

      <Card className="content-card metrics-card">
        <Card.Content>
          <p className="eyebrow">EFICIÊNCIA E CUSTO</p>
          <h3>FinOps e qualidade</h3>
          <div className="metrics-grid">
            <Kpi label="Taxa de cache" value={percent(d.taxaCache)} hint={`${d.ignoradosCache} sem custo`} />
            <Kpi
              label="Taxa de falha"
              value={percent(d.taxaFalhaProcessamento)}
              tone={d.taxaFalhaProcessamento > 0.05 ? "danger" : undefined}
            />
            <Kpi
              label="Resumos por template"
              value={percent(d.taxaFallback)}
              hint={`${d.fallbacksLlm} fallbacks do LLM`}
              tone={d.taxaFallback > 0.2 ? "warning" : undefined}
            />
            <Kpi label="Custo médio por aluno" value={usd(d.custoMedioPorAlunoUsd, 6)} />
            <Kpi label="Tempo médio do pipeline" value={ms(d.tempoMedioPipelineMs)} />
            <Kpi
              label="Teto de custo atingido"
              value={d.execucoesComOrcamentoExcedido}
              hint="execuções"
              tone={d.execucoesComOrcamentoExcedido > 0 ? "warning" : undefined}
            />
          </div>
        </Card.Content>
      </Card>

      <Card className="content-card metrics-card">
        <Card.Content>
          <p className="eyebrow">OPERAÇÃO · DESDE {time(o.desde)}</p>
          <h3>Saúde da API e dos provedores</h3>
          <div className="metrics-grid">
            <Kpi label="Pedidos HTTP" value={o.httpRequisicoes} hint={`${o.httpErros4xx} erros 4xx`} />
            <Kpi
              label="Taxa de erro 5xx"
              value={percent(o.httpTaxaErro5xx)}
              tone={o.httpErros5xx > 0 ? "danger" : undefined}
            />
            <Kpi label="Latência HTTP" value={`p50 ${ms(o.httpLatenciaP50Ms)}`} hint={`p95 ${ms(o.httpLatenciaP95Ms)}`} />
            <Kpi label="Retries de provedores" value={o.llmRetries} tone={o.llmRetries > 0 ? "warning" : undefined} />
            <Kpi label="Throttling do LLM" value={o.llmThrottles} hint={`${o.promptsTruncados} prompts truncados`} />
            <Kpi
              label="Bloqueios por rate limit"
              value={o.pedidosBloqueadosRateLimit}
              tone={o.pedidosBloqueadosRateLimit > 0 ? "warning" : undefined}
            />
          </div>
          <div className="metrics-circuits">
            <Circuit name="LLM" state={o.circuitoLlm} />
            <Circuit name="SMTP" state={o.circuitoSmtp} />
            <span>
              {o.notificacoesEnviadas} notificações · {o.alunosComFalha} alunos com falha neste processo
            </span>
          </div>
        </Card.Content>
      </Card>

      <Card className="content-card metrics-card">
        <Card.Content>
          <p className="eyebrow">HISTÓRICO</p>
          <h3>Últimas execuções</h3>
          {metrics.ultimasExecucoes.length === 0 ? (
            <p className="metrics-empty">Nenhuma execução ainda. Envie um CSV em Importar dados.</p>
          ) : (
            <ExecutionHistory executions={metrics.ultimasExecucoes} />
          )}
        </Card.Content>
      </Card>
    </div>
  );
}
