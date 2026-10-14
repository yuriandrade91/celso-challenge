"use client";

import { useMemo, useState } from "react";
import {
  Bell,
  CheckCheck,
  ClipboardCheck,
  Footprints,
  GraduationCap,
  MessageSquareQuote,
  PencilLine,
  ThumbsUp,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { Accordion, Button, Card, Chip, Tabs } from "@heroui/react";
import {
  markAllNotificationsRead,
  markNotificationRead,
  type StudentInbox as Inbox,
  type StudentNotification,
} from "@/lib/backend";
import { notifications } from "@/lib/notifications";

const PASSING_GRADE = 10;

type AccordionKey = string | number;

type Filter = "all" | "unread" | "term_report" | "grade_update" | "review_decision";

const KIND_DISPLAY: Record<
  StudentNotification["kind"],
  { icon: LucideIcon; label: string; iconClass: string }
> = {
  term_report: { icon: GraduationCap, label: "Boletim", iconClass: "" },
  grade_update: {
    icon: PencilLine,
    label: "Nota atualizada",
    iconClass: " inbox-item-icon-review",
  },
  review_decision: {
    icon: ClipboardCheck,
    label: "Revisão de nota",
    iconClass: " inbox-item-icon-review",
  },
};

type SummarySection = {
  key: "good" | "attention" | "next";
  label: string;
  icon: LucideIcon;
  text: string;
};

// Marcadores do contrato do resumo (LLM e template), procurados por ordem.
const SECTION_MARKERS: Omit<SummarySection, "text">[] = [
  { key: "good", label: "Você foi bem em", icon: ThumbsUp },
  { key: "attention", label: "Atenção", icon: TriangleAlert },
  { key: "next", label: "Próximos passos", icon: Footprints },
];
const MARKER_PATTERNS: Record<SummarySection["key"], RegExp> = {
  good: /voc[eê] foi bem em:?/i,
  attention: /aten[cç][aã]o(?: em)?:?/i,
  next: /pr[oó]ximos passos:?/i,
};

function tidy(text: string): string {
  const trimmed = text.trim().replace(/^[,.;:\s]+|[,;\s]+$/g, "");
  return trimmed.charAt(0).toLocaleUpperCase("pt-BR") + trimmed.slice(1);
}

/** Divide o resumo em saudação e secções; null se não seguir o contrato. */
function parseSummary(
  summary: string
): { greeting: string; sections: SummarySection[] } | null {
  const found: { marker: (typeof SECTION_MARKERS)[number]; start: number; end: number }[] = [];
  let cursor = 0;
  for (const marker of SECTION_MARKERS) {
    const match = MARKER_PATTERNS[marker.key].exec(summary.slice(cursor));
    if (!match) continue;
    const start = cursor + match.index;
    found.push({ marker, start, end: start + match[0].length });
    cursor = start + match[0].length;
  }
  if (found.length < 2) return null;
  return {
    greeting: tidy(summary.slice(0, found[0].start)).replace(/[!,]$/, ""),
    sections: found.map(({ marker, end }, index) => ({
      ...marker,
      text: tidy(summary.slice(end, found[index + 1]?.start ?? summary.length)),
    })),
  };
}

function formatGrade(grade: number): string {
  return new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 }).format(grade);
}

const relativeFormat = new Intl.RelativeTimeFormat("pt-BR", { numeric: "auto" });

function formatRelative(value: string): string {
  const seconds = (new Date(value).getTime() - Date.now()) / 1000;
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
  ];
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) {
      return relativeFormat.format(Math.round(seconds / size), unit);
    }
  }
  return "agora mesmo";
}

function GradeTile({ subject, grade }: { subject: string; grade: number }) {
  const passing = grade >= PASSING_GRADE;
  return (
    <div className={`inbox-grade${passing ? "" : " inbox-grade-attention"}`}>
      <span>{subject}</span>
      <strong>
        {formatGrade(grade)}
        <small>/20</small>
      </strong>
      <Chip size="sm" color={passing ? "success" : "warning"}>
        {passing ? "Aprovado" : "Requer atenção"}
      </Chip>
    </div>
  );
}

function TermReportBody({ item }: { item: StudentNotification }) {
  const parsed = parseSummary(item.summary);
  return (
    <>
      <div className="inbox-grades">
        <GradeTile subject="Matemática" grade={item.mathGrade} />
        <GradeTile subject="História" grade={item.historyGrade} />
      </div>
      {parsed ? (
        <>
          {parsed.greeting && <p className="inbox-greeting">{parsed.greeting}</p>}
          <div className="inbox-sections">
            {parsed.sections.map(({ key, label, icon: Icon, text }) => (
              <section key={key} className={`inbox-section inbox-section-${key}`}>
                <span className="inbox-section-icon">
                  <Icon size={15} aria-hidden="true" />
                </span>
                <div>
                  <strong>{label}</strong>
                  <p>{text}</p>
                </div>
              </section>
            ))}
          </div>
        </>
      ) : (
        <p className="inbox-greeting">{item.summary}</p>
      )}
    </>
  );
}

function ReviewDecisionBody({ item }: { item: StudentNotification }) {
  const [message, response] = item.summary.split(/\n+Resposta do professor:\s*/);
  return (
    <>
      <p className="inbox-greeting">{message}</p>
      {response && (
        <blockquote className="inbox-teacher-response">
          <MessageSquareQuote size={15} aria-hidden="true" />
          <span>
            <strong>Resposta do professor</strong>
            {response}
          </span>
        </blockquote>
      )}
    </>
  );
}

function GradeUpdateBody({ item }: { item: StudentNotification }) {
  const [message, changes] = item.summary.split(/\n{2,}/);
  return (
    <>
      <div className="inbox-grades">
        <GradeTile subject="Matemática" grade={item.mathGrade} />
        <GradeTile subject="História" grade={item.historyGrade} />
      </div>
      <p className="inbox-greeting">{message}</p>
      {changes && (
        <ul className="inbox-grade-changes">
          {changes.split("\n").map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
    </>
  );
}

function NotificationList({
  items,
  expandedKeys,
  onExpandedChange,
}: {
  items: StudentNotification[];
  expandedKeys: Set<AccordionKey>;
  onExpandedChange: (keys: Set<AccordionKey>) => void;
}) {
  if (items.length === 0) {
    return (
      <div className="no-reviews">
        <span>
          <Bell size={20} aria-hidden="true" />
        </span>
        <strong>Nada por aqui</strong>
        <p>
          O boletim do semestre, as notas atualizadas pelo professor e as
          respostas aos pedidos de revisão aparecerão aqui.
        </p>
      </div>
    );
  }

  return (
    <Accordion
      className="inbox-accordion"
      allowsMultipleExpanded
      expandedKeys={expandedKeys}
      onExpandedChange={onExpandedChange}
    >
      {items.map((item) => {
        const unread = item.readAt === null;
        const display = KIND_DISPLAY[item.kind];
        const Icon = display.icon;
        return (
          <Accordion.Item
            key={item.id}
            id={String(item.id)}
            className={`inbox-item${unread ? " inbox-item-unread" : ""}`}
          >
            <Accordion.Heading>
              <Accordion.Trigger className="inbox-trigger">
                <span className={`inbox-item-icon${display.iconClass}`}>
                  <Icon size={17} aria-hidden="true" />
                </span>
                <span className="inbox-item-title">
                  <strong>{item.title}</strong>
                  <small>
                    {item.kind === "term_report"
                      ? `${display.label} · ${item.termCode}`
                      : display.label}{" "}
                    ·{" "}
                    <time
                      dateTime={item.createdAt}
                      title={new Date(item.createdAt).toLocaleString("pt-BR")}
                    >
                      {formatRelative(item.createdAt)}
                    </time>
                  </small>
                </span>
                {unread && (
                  <Chip size="sm" color="accent" className="inbox-new-chip">
                    Nova
                  </Chip>
                )}
                <Accordion.Indicator />
              </Accordion.Trigger>
            </Accordion.Heading>
            <Accordion.Panel>
              <Accordion.Body className="inbox-item-body">
                {item.kind === "term_report" ? (
                  <TermReportBody item={item} />
                ) : item.kind === "grade_update" ? (
                  <GradeUpdateBody item={item} />
                ) : (
                  <ReviewDecisionBody item={item} />
                )}
              </Accordion.Body>
            </Accordion.Panel>
          </Accordion.Item>
        );
      })}
    </Accordion>
  );
}

export default function StudentInbox({
  inbox,
  onChanged,
}: {
  inbox: Inbox | null;
  onChanged: (inbox: Inbox) => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [expandedKeys, setExpandedKeys] = useState<Set<AccordionKey>>(new Set());
  const [markingAll, setMarkingAll] = useState(false);

  const filtered = useMemo(() => {
    const items = inbox?.items ?? [];
    return {
      all: items,
      unread: items.filter((item) => item.readAt === null),
      term_report: items.filter((item) => item.kind === "term_report"),
      grade_update: items.filter((item) => item.kind === "grade_update"),
      review_decision: items.filter((item) => item.kind === "review_decision"),
    } satisfies Record<Filter, StudentNotification[]>;
  }, [inbox]);

  if (!inbox) return null;

  const markRead = (ids: number[]) => {
    const readAt = new Date().toISOString();
    // Otimista: o aluno não espera pela API para ver o item como lido.
    onChanged({
      unreadCount: Math.max(inbox.unreadCount - ids.length, 0),
      items: inbox.items.map((item) =>
        ids.includes(item.id) ? { ...item, readAt } : item
      ),
    });
    for (const id of ids) {
      markNotificationRead(id).catch((error: unknown) =>
        notifications.error(error, "Não foi possível marcar a notificação como lida.")
      );
    }
  };

  const changeExpanded = (keys: Set<AccordionKey>) => {
    const opened = inbox.items.filter(
      (item) =>
        item.readAt === null &&
        keys.has(String(item.id)) &&
        !expandedKeys.has(String(item.id))
    );
    setExpandedKeys(keys);
    if (opened.length) markRead(opened.map((item) => item.id));
  };

  const markAll = async () => {
    setMarkingAll(true);
    try {
      await markAllNotificationsRead();
      const readAt = new Date().toISOString();
      onChanged({
        unreadCount: 0,
        items: inbox.items.map((item) => ({ ...item, readAt: item.readAt ?? readAt })),
      });
    } catch (error) {
      notifications.error(error, "Não foi possível marcar as notificações como lidas.");
    } finally {
      setMarkingAll(false);
    }
  };

  const tabs: { id: Filter; label: string }[] = [
    { id: "all", label: "Todas" },
    { id: "unread", label: "Não lidas" },
    { id: "term_report", label: "Boletins" },
    { id: "grade_update", label: "Notas" },
    { id: "review_decision", label: "Revisões" },
  ];

  return (
    <Card className="content-card list-card inbox-card">
      <Card.Header className="list-card-header">
        <div className="inbox-heading">
          <span className="inbox-heading-icon">
            <Bell size={18} aria-hidden="true" />
          </span>
          <div>
            <Card.Title>Central de notificações</Card.Title>
            <Card.Description>
              {inbox.unreadCount > 0
                ? `${inbox.unreadCount} não lida${inbox.unreadCount === 1 ? "" : "s"} · abra uma notificação para a marcar como lida`
                : "Está tudo em dia"}
            </Card.Description>
          </div>
        </div>
        <Button
          size="sm"
          variant="secondary"
          isDisabled={inbox.unreadCount === 0 || markingAll}
          isPending={markingAll}
          onPress={() => void markAll()}
        >
          <CheckCheck size={15} aria-hidden="true" />
          Marcar todas como lidas
        </Button>
      </Card.Header>
      <Card.Content className="inbox-content">
        <Tabs
          variant="secondary"
          align="start"
          selectedKey={filter}
          onSelectionChange={(key) => setFilter(key as Filter)}
        >
          <Tabs.ListContainer>
            <Tabs.List aria-label="Filtrar notificações">
              {tabs.map((tab) => (
                <Tabs.Tab key={tab.id} id={tab.id}>
                  {tab.label}
                  {filtered[tab.id].length > 0 && (
                    <span
                      className={`inbox-tab-count${tab.id === "unread" ? " inbox-tab-count-alert" : ""}`}
                    >
                      {filtered[tab.id].length}
                    </span>
                  )}
                  <Tabs.Indicator />
                </Tabs.Tab>
              ))}
            </Tabs.List>
          </Tabs.ListContainer>
          {tabs.map((tab) => (
            <Tabs.Panel key={tab.id} id={tab.id} className="inbox-panel">
              <NotificationList
                items={filtered[tab.id]}
                expandedKeys={expandedKeys}
                onExpandedChange={changeExpanded}
              />
            </Tabs.Panel>
          ))}
        </Tabs>
      </Card.Content>
    </Card>
  );
}
