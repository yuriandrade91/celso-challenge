"use client";

import {
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type FormEvent,
} from "react";
import { ArrowUpFromLine, Check, FileSpreadsheet, X } from "lucide-react";
import { Button, Card, Chip, Spinner } from "@heroui/react";
import {
  uploadCsv,
  type UploadReport,
} from "@/lib/backend";
import { notifications } from "@/lib/notifications";

type UploadFormProps = {
  onUploaded: () => void;
};

export default function UploadForm({ onUploaded }: UploadFormProps) {
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<UploadReport | null>(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const chooseFile = (event: ChangeEvent<HTMLInputElement>) => {
    const nextFile = event.target.files?.[0] ?? null;
    setFile(nextFile);
    setReport(null);
  };

  const dropFile = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    const nextFile = event.dataTransfer.files[0] ?? null;
    setFile(nextFile);
    setReport(null);
  };

  const handleUpload = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file || loading) return;
    if (!file.name.toLowerCase().endsWith(".csv")) {
      notifications.warning("Selecione um ficheiro com extensão .csv.");
      return;
    }

    setLoading(true);
    setReport(null);
    try {
      const result = await uploadCsv(file);
      setReport(result);
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
      if (result.falhas > 0) {
        notifications.warning(
          "Importação concluída com falhas.",
          `${result.falhas} linha(s) não foram processadas. Consulte os detalhes abaixo.`
        );
      } else {
        notifications.success(
          "Importação concluída.",
          `${result.processados} estudante(s) processado(s).`
        );
      }
      onUploaded();
    } catch (uploadError) {
      notifications.error(
        uploadError,
        "Não foi possível enviar o ficheiro ao backend."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="upload-card">
      <Card.Content className="upload-content">
        <div className="upload-copy">
          <span className="upload-icon">
            <FileSpreadsheet aria-hidden="true" size={21} />
          </span>
          <div>
            <h3>Importar notas dos estudantes</h3>
            <p>Envie um CSV para processar novos boletins e atualizar registos.</p>
          </div>
        </div>

        <form onSubmit={handleUpload} className="upload-form">
          <input
            ref={inputRef}
            type="file"
            accept=".csv,text/csv"
            disabled={loading}
            onChange={chooseFile}
            className="sr-only"
            id="csv-upload"
          />
          {file ? (
            <div className="selected-file">
              <FileSpreadsheet size={18} aria-hidden="true" />
              <span>{file.name}</span>
              <button
                type="button"
                aria-label="Remover ficheiro"
                disabled={loading}
                onClick={() => {
                  setFile(null);
                  setReport(null);
                  if (inputRef.current) inputRef.current.value = "";
                }}
              >
                <X size={16} aria-hidden="true" />
              </button>
            </div>
          ) : (
            <label
              className="upload-dropzone"
              htmlFor="csv-upload"
              onDragOver={(event) => event.preventDefault()}
              onDrop={dropFile}
            >
              <ArrowUpFromLine size={19} aria-hidden="true" />
              <span>Escolher ficheiro CSV</span>
              <span className="dropzone-hint">ou arraste para esta área</span>
            </label>
          )}
          <Button
            type="submit"
            isDisabled={!file || loading}
            className="upload-button"
          >
            {loading ? (
              <>
                <Spinner size="sm" color="current" />
                A processar
              </>
            ) : (
              <>
                <ArrowUpFromLine size={17} aria-hidden="true" />
                Enviar ficheiro
              </>
            )}
          </Button>
        </form>

        {report && (
          <div className="upload-report" role="status">
            <div className="upload-report-heading">
              <span className="success-icon">
                <Check size={16} aria-hidden="true" />
              </span>
              <strong>Processamento concluído</strong>
            </div>
            <div className="upload-report-stats">
              <Chip color="success">{report.processados} processados</Chip>
              <Chip color="accent">{report.atualizados} atualizados</Chip>
              <Chip>{report.ignorados_cache} em cache</Chip>
              {report.falhas > 0 && (
                <Chip color="danger">{report.falhas} falhas totais</Chip>
              )}
              {report.duplicados_ignorados > 0 && (
                <Chip>{report.duplicados_ignorados} duplicados</Chip>
              )}
              {report.falhas_validacao > 0 && (
                <Chip color="danger">
                  {report.falhas_validacao} erros de validação
                </Chip>
              )}
              {report.em_processamento > 0 && (
                <Chip color="warning">
                  {report.em_processamento} já em processamento noutra execução
                </Chip>
              )}
              {report.orcamento_excedido && (
                <Chip color="warning">Teto de custo LLM atingido</Chip>
              )}
              {report.fallbacks_llm > 0 && (
                <Chip color="warning">
                  {report.fallbacks_llm} resumo(s) por template (LLM indisponível)
                </Chip>
              )}
              <span>{report.tokens_gastos} tokens</span>
              <span>
                US$ {report.custo_estimado_usd.toFixed(6)} estimados
              </span>
              <span>
                {report.tempo_total_ms.toFixed(1)} ms no total
              </span>
              <span>
                {report.tempo_medio_processamento_ms.toFixed(1)} ms/aluno
                (p95 {report.tempo_p95_processamento_ms.toFixed(1)} ms)
              </span>
              <span>
                Resumo: {report.summary_provider} · envio:{" "}
                {report.notification_provider}
              </span>
              <span>Execução: {report.execution_id}</span>
            </div>
            {report.erros.length > 0 && (
              <ul className="upload-errors">
                {report.erros.map((item, index) => (
                  <li key={`${item.linha}-${item.campo}-${index}`}>
                    Linha {item.linha}, {item.campo}: {item.mensagem}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <p className="upload-footnote">
          Colunas esperadas: id_aluno (UUID), nome, email, nota_matematica,
          nota_historia
        </p>
      </Card.Content>
    </Card>
  );
}
