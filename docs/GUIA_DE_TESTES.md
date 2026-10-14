# Guia de testes por critério de avaliação

Este guia mostra como verificar cada critério do desafio de duas formas:

- **Automática:** um comando `pytest` que roda só os testes daquele critério.
- **Manual:** um roteiro com a API rodando, para demonstrar ao vivo no debriefing.

## Preparação (uma vez)

```bash
cd backend
../.venv/bin/pip install -r requirements.txt
cp .env.example .env    # configure JWT_SECRET_KEY e as senhas (ver README)
```

Rode **todas as verificações** de uma vez, na raiz do repositório:

```bash
make check   # pytest + cobertura, Vitest, typecheck e lint, com quadro-resumo no final
make ci      # o mesmo e, se tudo passar, já sobe API e painel
```

Só o backend, com o relatório de cobertura linha a linha:

```bash
../.venv/bin/python -m pytest -q --cov=app --cov-report=term-missing
```

### Servidor para os testes manuais

Na raiz do repositório, **um comando** sobe a API (8000) e o painel (3000).
Para não mexer no `backoffice.db`, use um banco descartável. O `API_LOG`
grava o log JSON da API num ficheiro, para os `grep` deste guia:

```bash
rm -f /tmp/celso-demo.db
DATABASE_URL=sqlite:////tmp/celso-demo.db API_LOG=/tmp/celso-api.log make dev
```

Para os cenários que pedem variáveis diferentes, ponha-as antes do
`make dev`. Exemplo:

```bash
GRADE_MAX_CONCURRENCY=0 DATABASE_URL=sqlite:////tmp/celso-demo.db API_LOG=/tmp/celso-api.log make dev
```

As variáveis valem para a API e têm prioridade sobre o `.env`. Ctrl+C encerra
os dois servidores.

No terminal dos testes, obtenha um token de professor:

```bash
export API=http://127.0.0.1:8000
login() { curl -s -X POST $API/auth/login -H 'content-type: application/json' \
  -d "{\"profile\":\"$1\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['accessToken'])"; }
TOKEN=$(login professor)
upload() { curl -s -X POST "$API/upload$2" -H "Authorization: Bearer $TOKEN" -F file=@$1; }
```

> Cada cenário que pede variáveis diferentes exige reiniciar com
> `Ctrl+C` e `make dev`, sempre com `rm -f /tmp/celso-demo.db` para começar do
> zero. Onde o guia diz "reinicie a API com X=…", faça
> `X=… DATABASE_URL=sqlite:////tmp/celso-demo.db API_LOG=/tmp/celso-api.log make dev`.

---

## 1. Arquitetura

**O que foi feito:**
- contratos `ISummarizer`, `INotifier` e `IGradeReportRepository` em `app/interfaces/interfaces.py`;
- políticas transversais como decorators de `ISummarizer` (`FallbackSummarizer`, `BudgetedSummarizer`);
- provedores escolhidos por variável de ambiente (`create_summarizer`, `create_grade_report_notifier`);
- I/O de banco isolado do event loop pelo `_RepositoryGate`.

**Automático:**

```bash
../.venv/bin/python -m pytest -q -k "fallback_summarizer or provider_is_wrapped or roster or notification_contains"
```

**Manual:** os testes em `tests/test_business.py` rodam o pipeline inteiro com
fakes em memória (`MemoryReportRepository`, `FakeNotifier`, `FakeSummarizer`).
Isso prova que o pipeline depende só dos contratos. Para trocar o provedor sem
mudar código, reinicie com `GRADE_SUMMARY_PROVIDER=openai` (ver critério 2) e
confira `summaryProvider` no relatório.

---

## 2. Retry Strategy (backoff, idempotência, retriável × fatal)

**O que foi feito:**
- só erros transitórios são retentados: HTTP 408/429/5xx, falha de conexão e SMTP 4xx;
- até 3 tentativas, com backoff exponencial com *full jitter*;
- `Retry-After` é respeitado; acima de 30 s, falha rápido e o fallback assume;
- idempotência pelo hash + estado `pending`/`sent`;
- **lease por aluno**, que protege contra uploads concorrentes.

**Automático:**

```bash
../.venv/bin/python -m pytest -q -k "retry or retried or claim or concurrent_uploads or failed_delivery"
```

Os testes que mais importam aqui:

| Teste | O que prova |
| --- | --- |
| `test_fatal_provider_errors_are_not_retried` | HTTP 400 não é retentado |
| `test_retry_honours_retry_after_from_provider` | `Retry-After` é respeitado |
| `test_long_retry_after_fails_fast` | `Retry-After` longo falha rápido |
| `test_concurrent_uploads_of_the_same_file_notify_each_student_once` | uploads concorrentes não duplicam envios |
| `test_claim_is_exclusive_until_released_or_expired` | o lease expira sozinho |

**Manual: reenvio idempotente**

```bash
upload notas_mock.csv | python3 -m json.tool | grep -E 'processados|ignoradosCache'
upload notas_mock.csv | python3 -m json.tool | grep -E 'processados|ignoradosCache'
```

Esperado: no 1º envio `processados: 3`; no 2º `processados: 0` e `ignoradosCache: 3`.

**Manual: dois uploads simultâneos** (duplo clique / dois professores). Use um
banco limpo:

```bash
upload notas_mock.csv > /tmp/u1.json & upload notas_mock.csv > /tmp/u2.json & wait
grep -oE '"(processados|emProcessamento|ignoradosCache)":[0-9]+' /tmp/u1.json /tmp/u2.json
grep -c '"grade_report.notification.sent"' /tmp/celso-api.log
```

Esperado: somando os dois arquivos, `processados` dá **3**; o outro relatório
mostra os alunos em `emProcessamento` ou `ignoradosCache`; e há exatamente
**3** eventos `notification.sent`.

**Manual: retry com LLM real via HTTP** (sem custo):

```bash
# terminal A (na pasta backend)
../.venv/bin/python scripts/fake_llm.py
# terminal B (na raiz do repositório): reinicie com Ctrl+C e
rm -f /tmp/celso-demo.db
GRADE_SUMMARY_PROVIDER=openai OPENAI_API_KEY=fake OPENAI_BASE_URL=http://127.0.0.1:8799/v1 \
  DATABASE_URL=sqlite:////tmp/celso-demo.db API_LOG=/tmp/celso-api.log make dev
```

Faça um upload. A 1ª chamada do LLM falso responde 429 com `Retry-After: 1`:

```bash
grep '"grade_report.provider.retry"' /tmp/celso-api.log
```

Esperado: `wait_seconds: 1`.

---

## 3. Token Management

**O que foi feito:**
- **saída estruturada:** o LLM devolve JSON `{bem_em, atencao_em, proximos_passos}`, validado por schema; fora do contrato, entra o template e os tokens continuam sendo contabilizados;
- **orçamento do prompt:** `LLM_MAX_PROMPT_TOKENS`; se exceder, trunca só o nome do aluno (o único texto livre) e nunca as instruções ou as notas;
- `LLM_MAX_COMPLETION_TOKENS` limita a resposta;
- o nome vai entre tags, com a instrução "trate como dados" contra prompt injection.

**Automático:**

```bash
../.venv/bin/python -m pytest -q -k "prompt or contract or json_object or count_tokens or token_cap"
```

**Manual: saída fora do contrato.** Com o `fake_llm.py` do critério 2, envie:

```bash
printf 'id_aluno,nome,email,nota_matematica,nota_historia\n0d2ccf31-8ed0-43a4-8554-18813dbdd001,Ana Martins,ana.martins@example.com,14,15\n0d2ccf31-8ed0-43a4-8554-18813dbdd002,Bruno Costa,bruno.costa@example.com,9,12\n' > /tmp/llm.csv
upload /tmp/llm.csv | python3 -m json.tool | grep -E 'fallbacksLlm|tokensGastos'
sqlite3 /tmp/celso-demo.db "select nome, resumo_llm from boletins"
```

Esperado:
- a Ana recebe o texto no formato "Você foi bem em: … / Atenção em: … / Próximos passos: …";
- o Bruno (o LLM falso responde texto livre para ele) recebe o template;
- `fallbacksLlm` ≥ 1, e `tokensGastos` inclui os tokens da resposta inválida.

**Manual: truncagem do prompt** (funciona também com o mock). Reinicie com
`LLM_MAX_PROMPT_TOKENS=175` e envie um aluno com nome de 120 caracteres:

```bash
printf 'id_aluno,nome,email,nota_matematica,nota_historia\n0d2ccf31-8ed0-43a4-8554-18813dbdd009,Maria Silva Silva Silva Silva Silva Silva Silva Silva Silva Silva Silva Silva Silva Silva Silva Silva Silva Silva Silva,longo@example.com,14,15\n' > /tmp/longo.csv
upload /tmp/longo.csv > /dev/null
grep '"llm.prompt_truncated"' /tmp/celso-api.log
```

Esperado: um evento com `overflow_tokens` e `budget_tokens: 175`. Só o nome é
cortado; as instruções e as notas continuam inteiras (ver
`test_prompt_fits_token_budget_by_truncating_only_the_name`).

---

## 4. Observabilidade (logs, tracing, métricas)

**O que foi feito:**
- logs JSON com `request_id`, `execution_id`, `trace_id` e `span_id`;
- **spans simulados no formato OpenTelemetry** (pai/filho, duração e status);
- latência média e p95 por aluno;
- evento `http.request` com status e latência de todo pedido.

**Automático:**

```bash
../.venv/bin/python -m pytest -q tests/test_observability.py
```

**Manual:**

```bash
curl -s -o /dev/null -D - -X POST "$API/upload" -H "Authorization: Bearer $TOKEN" \
  -H "X-Request-ID: demo-123" -F file=@notas_mock.csv | grep -i x-request-id
grep '"demo-123"' /tmp/celso-api.log | python3 -c "
import sys, json
for line in sys.stdin:
    e = json.loads(line)
    print(e['event'], e.get('span_name', ''), e.get('parent_span_id', ''), e.get('duration_ms', ''))"
```

Para as métricas de latência e erro sem ler logs:

```bash
curl -s "$API/metrics?recent=0" -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys, json
o = json.load(sys.stdin)['data']['operacional']
print({k: o[k] for k in ('httpRequisicoes', 'httpErros5xx', 'httpTaxaErro5xx', 'httpLatenciaP50Ms', 'httpLatenciaP95Ms', 'llmRetries')})"
```

Esperado: o header volta `X-Request-ID: demo-123`. Todos os eventos do upload
compartilham o `request_id`. Os spans `grade_report.student` têm como pai
`grade_report.execution`, e `llm.generate` e `notification.send` têm como pai
o span do aluno. Com `LOG_LEVEL=DEBUG` aparecem também os spans `db.*`.

---

## 5. Tratamento de Erros

**O que foi feito:**
- erros por linha (validação), envelope de erro padronizado;
- 400/413/429 para erros do cliente, 503 para configuração inválida do servidor, 500 genérico com stack trace só no log;
- fallback por template.

**Automático:**

```bash
../.venv/bin/python -m pytest -q -k "fallback or invalid or misconfiguration or rejects or not_found or fatal or permanent"
```

**Manual:**

```bash
printf 'x' > /tmp/a.txt; curl -s -X POST $API/upload -H "Authorization: Bearer $TOKEN" -F file=@/tmp/a.txt   # 400 "Apenas CSV"
printf '' > /tmp/v.csv;  upload /tmp/v.csv                                                                 # 400 CSV inválido
upload notas_mock.csv | python3 -m json.tool | grep -A3 '"erros"'                                          # linha 4: nota > 20
```

**Manual: LLM fora do ar.** Reinicie com
`GRADE_SUMMARY_PROVIDER=openai OPENAI_API_KEY=x OPENAI_BASE_URL=http://127.0.0.1:9/v1`
(nada escuta na porta 9) e faça um upload.

Esperado: `processados: 3` e `fallbacksLlm: 3`, ou seja, os alunos são
notificados mesmo com o LLM fora. No log aparecem `grade_report.provider.retry`
e `grade_report.summary.fallback`. Reinicie com `GRADE_SUMMARY_FALLBACK=none`
para ver o comportamento oposto (`falhasProcessamento: 3`).

**Manual: configuração inválida.** Reinicie com `GRADE_MAX_CONCURRENCY=0`. O
upload responde **503** com "Configuração do servidor inválida".

---

## 6. Rate Limiting (APIs externas, circuit breaker, throttling)

**O que foi feito:**

| Direção | Mecanismo |
| --- | --- |
| Saída | token bucket de RPM para o LLM (`LLM_REQUESTS_PER_MINUTE`), semáforos de concorrência, circuit breakers (LLM e SMTP) e `Retry-After` |
| Entrada | janela deslizante em `/auth/login` e `/auth/refresh` (por IP) e em `/upload` (por professor), com 429 + `Retry-After` |

**Automático:**

```bash
../.venv/bin/python -m pytest -q -k "token_bucket or throttled or sliding_window or rate_limited or circuit"
```

**Manual: limite de entrada:**

```bash
for i in $(seq 1 12); do curl -s -o /dev/null -w "%{http_code} " -X POST $API/auth/login \
  -H 'content-type: application/json' -d '{"profile":"professor"}'; done; echo
```

Esperado: `200` até completar 10 logins no minuto (o login da preparação
conta), depois `429`. O header `Retry-After` vem na resposta.
Para o upload, reinicie com `UPLOAD_RATE_LIMIT_PER_MINUTE=2` e envie 3 vezes.

**Manual: circuit breaker.** Com o cenário "LLM fora do ar" do critério 5,
um único upload do `notas_mock.csv` gera 3 alunos × 3 tentativas. Depois de 5
falhas transitórias o circuito abre, e as chamadas seguintes nem chegam a
sair:

```bash
grep -c 'ProviderCircuitOpenError' /tmp/celso-api.log   # >= 1
```

Num novo upload com notas **diferentes** (notas iguais são servidas pelo
cache) feito em menos de 30 s, o resumo cai direto no template, sem esperar
retries.

**Manual: throttling (RPM).** Com o `fake_llm.py`, reinicie com
`LLM_REQUESTS_PER_MINUTE=6` e envie 3 alunos:

```bash
grep '"llm.throttled"' /tmp/celso-api.log
```

Esperado: esperas de cerca de 10 s entre chamadas.

---

## 7. FinOps

**O que foi feito:**
- cache por hash (reenvio custa zero);
- reaproveitamento do resumo salvo quando só o envio falhou;
- `max_tokens`;
- modelo configurável;
- custo estimado mesmo no mock;
- **teto de custo por execução**, com reserva antes de cada chamada.

**Automático:**

```bash
../.venv/bin/python -m pytest -q -k "budget or cache or cost or estimates"
```

**Manual: teto de custo.** Reinicie (banco limpo) com
`GRADE_MAX_COST_USD_PER_EXECUTION=0.00015 GRADE_MAX_CONCURRENCY=1`:

```bash
upload notas_mock.csv | python3 -m json.tool | grep -E 'processados|fallbacksLlm|orcamentoExcedido|custoEstimadoUsd'
grep '"grade_report.budget.exhausted"' /tmp/celso-api.log
```

Esperado: `processados: 3`, `fallbacksLlm: 2`, `orcamentoExcedido: true` e
custo abaixo de US$ 0,00015.

**Manual: cache.** Repita o upload: `tokensGastos: 0` e `custoEstimadoUsd: 0`.

---

## 8. Escalabilidade (stateless, concorrência)

**O que foi feito:**
- modo assíncrono `?mode=async` (202 + polling);
- pool de alunos limitado por semáforo;
- I/O de banco fora do event loop;
- garantias de corretude no banco (lease, `execution_id` único), e não em memória, o que permite várias réplicas.

**Automático:**

```bash
../.venv/bin/python -m pytest -q -k "async_upload or concurrency or concurrent or per_student"
```

**Manual: modo assíncrono:**

```bash
curl -s -i -X POST "$API/upload?mode=async" -H "Authorization: Bearer $TOKEN" -F file=@notas_mock.csv | grep -iE '^HTTP|^location|executionId'
# copie o executionId:
curl -s $API/executions/<executionId> -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | grep -E 'status|processados'
```

Esperado: `HTTP/1.1 202 Accepted` com `location: /executions/<id>`; o status
passa de `running` para `completed`.

**Manual: concorrência.** Repita o cenário "dois uploads simultâneos" do
critério 2.

---

## 9. Testes Automatizados

**O que foi feito:** testes automatizados em 11 arquivos:

| Tipo | Arquivos |
| --- | --- |
| Unitários de regra de negócio | `test_business.py`, `test_resilience.py` |
| Contrato com os provedores | `test_providers.py` (formato do pedido e da resposta da OpenAI, SMTP) |
| Integração da API | `test_upload_api.py`, `test_students.py`, `test_reviews.py`, `test_seed.py`, `test_terms.py` |
| Observabilidade e métricas | `test_observability.py`, `test_demo_metrics.py` |
| Rate limit | `test_rate_limit.py` |

```bash
../.venv/bin/python -m pytest -q --cov=app --cov-report=term-missing
```

Nenhum teste acessa a rede. Os tempos são controlados por relógios e
`sleep` falsos.

No frontend, os quatro arquivos em `frontend/tests/` usam Vitest e cobrem a
allowlist do proxy, a proteção CSRF por origem, a leitura do envelope de erro
da API e os formatadores do painel. `make check` roda tudo e mostra o resumo.

---

## 10. Product Analytics

**O que foi feito:**
- tabela `grade_report_executions` com uma linha por execução;
- **`GET /metrics`**, um único endpoint com três blocos:

| Bloco | Conteúdo |
| --- | --- |
| `dispatcher` | as 4 métricas pedidas na opção 2, mais taxas de cache, falha e fallback, custo por aluno, tempo do pipeline, p95 e teto de custo |
| `operacional` | latência e erros HTTP, retries, throttling, rate limit, circuit breakers |
| `ultimasExecucoes` | as execuções mais recentes |

- endpoints auxiliares `GET /executions` e `GET /executions/{id}`;
- página **Métricas** no dashboard.

**Automático:**

```bash
../.venv/bin/python -m pytest -q -k "metrics or execution or history or summary or persists"
```

**Manual:**

```bash
upload notas_mock.csv > /dev/null; upload notas_mock.csv > /dev/null
curl -s "$API/metrics?recent=5" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Esperado em `dispatcher`:
- `execucoes: 2`;
- `alunosProcessados: 3`;
- `falhas: 2` (uma linha inválida por upload);
- `taxaCache: 0.5`;
- `custoEstimadoUsd` > 0 e `tempoMedioProcessamentoMs` > 0.

Em `operacional`, aparecem `notificacoesEnviadas: 3` e `circuitoLlm.estado: "closed"`.

**No painel:** faça login como professor em http://localhost:3000 e abra
**Métricas** no menu. Há quatro cartões:

| Cartão | Conteúdo |
| --- | --- |
| Relatório de execução | as 4 métricas do desafio |
| Eficiência e custo | taxas de cache, falha e fallback, custo e teto |
| Operação | HTTP, retries, rate limit, circuit breakers |
| Últimas execuções | histórico recente |

A página se atualiza sozinha a cada 15 s. Para ver o painel reagir,
reinicie a API no cenário "LLM fora do ar" (critério 5): o circuito LLM fica
**aberto** e a taxa de "Resumos por template" sobe.

---

## 11. Segurança

**O que foi feito:**
- secrets só no `.env` (no `.gitignore`), com recusa de valores de exemplo;
- JWT com refresh rotativo e senhas com PBKDF2;
- cookies HttpOnly e proxy com allowlist no Next.js;
- rate limit no login;
- validação estrita das entradas e saída do LLM validada;
- CORS restrito;
- emails mascarados e conteúdo de mensagens nunca registado.

**Automático:**

```bash
../.venv/bin/python -m pytest -q -k "masked or requires_teacher or rate_limited or size_limit or request_id or grades_must or roster_conflicts"
```

**Manual:**

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST $API/upload -F file=@notas_mock.csv           # 401 sem token
STUDENT=$(login aluno_1); curl -s -o /dev/null -w "%{http_code}\n" -X POST $API/upload \
  -H "Authorization: Bearer $STUDENT" -F file=@notas_mock.csv                                  # 403 para aluno
grep -E '[a-z]+\.[a-z]+@example\.com' /tmp/celso-api.log | grep -v '\*\*\*' | wc -l            # 0: nenhum email em claro
git -C .. check-ignore backend/.env && echo ".env ignorado pelo git"
```

---

## Limitações do ambiente de demonstração

Estas limitações são intencionais e estão justificadas no README, em
"Arquitetura" e "Melhorias e implantação em AWS":

- Os limites (token bucket, janelas, circuit breakers) são **por processo**.
  Com várias réplicas, seria preciso Redis.
- O modo assíncrono usa tarefas em memória: reiniciar o servidor perde
  execuções em andamento, que ficam `running`. Em produção, seria uma fila
  durável.
- Os spans são eventos JSON no formato OpenTelemetry, sem exportação para um
  collector.
- O envio de email é *at-least-once*: um crash entre o aceite do SMTP e a
  gravação de `sent` pode duplicar um email.
