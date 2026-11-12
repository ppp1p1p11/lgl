"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ErrorText } from "@/components/ErrorText";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorMessage } from "@/lib/errors";
import { fill, formatDate, formatDateTime, todayIso } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useCan } from "@/lib/session";

type Rules = components["schemas"]["RulesOut"];
type Proposal = components["schemas"]["ProposalOut"];
type Preview = components["schemas"]["PreviewOut"];
type DeadlineIn = components["schemas"]["DeadlineIn"];
type Step = components["schemas"]["StepOut"];

const EMPTY: DeadlineIn = {
  title: "",
  rule_set: "cpc",
  trigger_kind: "disponibilizacao_dje",
  trigger_date: "",
  days: 15,
  unit: "dias_uteis",
  doubled_reason: null,
  preset_id: null,
};

function Reasoning({ steps }: { steps: Step[] }) {
  return (
    <ol className="steps">
      {steps.map((s, i) => (
        <li key={i}>
          <strong>{s.label}:</strong> {s.detail}
        </li>
      ))}
    </ol>
  );
}

/** Deadlines of one processo: calculator with visible reasoning, proposals and decisions. */
export function Deadlines({ matterId, onChange }: { matterId: string; onChange: () => void }) {
  const canPropose = useCan("manage_tasks");
  const canConfirm = useCan("confirm_deadlines");
  const [rules, setRules] = useState<Rules | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<DeadlineIn>(EMPTY);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchProposals = useCallback(async () => {
    const { data } = await api.GET("/api/matters/{matter_id}/deadline-proposals", {
      params: { path: { matter_id: matterId } },
    });
    return data ?? [];
  }, [matterId]);

  useEffect(() => {
    fetchProposals().then(setProposals);
    api.GET("/api/deadline-rules").then(({ data }) => setRules(data ?? null));
  }, [fetchProposals]);

  function update(patch: Partial<DeadlineIn>) {
    setForm({ ...form, ...patch });
    setPreview(null);
  }

  function open() {
    setForm({ ...EMPTY, trigger_date: todayIso() });
    setPreview(null);
    setError(null);
    setShowForm(true);
  }

  function choosePreset(presetId: string) {
    const preset = rules?.presets.find((p) => p.id === presetId);
    if (!preset) {
      update({ preset_id: null });
      return;
    }
    update({
      preset_id: preset.id,
      rule_set: preset.rule_set,
      days: preset.days,
      title: preset.label,
      unit: "dias_uteis",
    });
  }

  async function calculate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const { data, error: apiError } = await api.POST("/api/deadline-preview", { body: form });
    setError(data ? null : errorMessage(apiError));
    setPreview(data ?? null);
  }

  async function save() {
    const { data, error: apiError } = await api.POST(
      "/api/matters/{matter_id}/deadline-proposals",
      { params: { path: { matter_id: matterId } }, body: form },
    );
    if (!data) {
      setError(errorMessage(apiError));
      return;
    }
    setShowForm(false);
    setProposals(await fetchProposals());
  }

  const presets = rules?.presets ?? [];
  const chosen = presets.find((p) => p.id === form.preset_id);

  return (
    <section className="card">
      <div className="page-header">
        <h2>{t.prazos.title}</h2>
        {canPropose && !showForm && (
          <button type="button" className="secondary" onClick={open}>
            {t.prazos.new}
          </button>
        )}
      </div>
      <p className="muted small">
        {t.prazos.intro} <Link href="/agenda/feriados">{t.prazos.holidaysLink}</Link>
      </p>

      {showForm && rules && (
        <form onSubmit={calculate} className="subform">
          <div className="grid">
            <label>
              {t.prazos.preset}
              <select value={form.preset_id ?? ""} onChange={(e) => choosePreset(e.target.value)}>
                <option value="">{t.prazos.presetNone}</option>
                {rules.rule_sets.map((r) => (
                  <optgroup key={r.id} label={r.label}>
                    {presets
                      .filter((p) => p.rule_set === r.id)
                      .map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.label} ({p.days} d)
                        </option>
                      ))}
                  </optgroup>
                ))}
              </select>
              {chosen && <span className="muted small">{chosen.basis}</span>}
            </label>
            <label>
              {t.prazos.name}
              <input
                required
                minLength={3}
                maxLength={200}
                value={form.title}
                onChange={(e) => update({ title: e.target.value })}
              />
            </label>
            <label>
              {t.prazos.ruleSet}
              <select
                value={form.rule_set}
                onChange={(e) =>
                  update({ rule_set: e.target.value as DeadlineIn["rule_set"], preset_id: null })
                }
              >
                {rules.rule_sets.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.label}
                  </option>
                ))}
              </select>
              <span className="muted small">
                {rules.rule_sets.find((r) => r.id === form.rule_set)?.basis}
              </span>
            </label>
            <label>
              {t.prazos.triggerKind}
              <select
                value={form.trigger_kind}
                onChange={(e) =>
                  update({ trigger_kind: e.target.value as DeadlineIn["trigger_kind"] })
                }
              >
                {(Object.keys(t.prazos.triggerKinds) as DeadlineIn["trigger_kind"][]).map((k) => (
                  <option key={k} value={k}>
                    {t.prazos.triggerKinds[k]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t.prazos.triggerDate}
              <input
                type="date"
                required
                value={form.trigger_date}
                onChange={(e) => update({ trigger_date: e.target.value })}
              />
            </label>
            <label>
              {t.prazos.days}
              <input
                type="number"
                required
                min={1}
                max={365}
                value={form.days}
                onChange={(e) => update({ days: Number(e.target.value), preset_id: null })}
              />
            </label>
            <label>
              {t.prazos.unit}
              <select
                value={form.unit ?? "dias_uteis"}
                onChange={(e) => update({ unit: e.target.value as DeadlineIn["unit"] })}
              >
                <option value="dias_uteis">{t.prazos.units.dias_uteis}</option>
                <option value="dias_corridos">{t.prazos.units.dias_corridos}</option>
              </select>
            </label>
            <label>
              {t.prazos.doubling}
              <select
                value={form.doubled_reason ?? ""}
                onChange={(e) =>
                  update({
                    doubled_reason: (e.target.value || null) as DeadlineIn["doubled_reason"],
                  })
                }
              >
                <option value="">{t.prazos.doublingNone}</option>
                {rules.doubling_reasons.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <ErrorText message={error} />
          {preview && (
            <div className="preview">
              <p>
                <strong>{t.prazos.proposedDate}:</strong>{" "}
                <span className="big-date">{formatDate(preview.proposed_date)}</span>
              </p>
              <p className="small">
                <strong>{t.prazos.reasoning}</strong>
              </p>
              <Reasoning steps={preview.steps} />
              <p className="warning small">{t.prazos.holidayWarning}</p>
            </div>
          )}
          <div className="actions">
            <button type="submit" className={preview ? "secondary" : ""}>
              {t.prazos.calculate}
            </button>
            {preview && (
              <button type="button" onClick={save}>
                {t.prazos.save}
              </button>
            )}
            <button type="button" className="secondary" onClick={() => setShowForm(false)}>
              {t.common.cancel}
            </button>
          </div>
        </form>
      )}

      {proposals.length === 0 ? (
        <p className="muted">{t.prazos.empty}</p>
      ) : (
        <ul className="plain-list">
          {proposals.map((p) => (
            <ProposalItem
              key={p.id}
              proposal={p}
              canConfirm={canConfirm}
              onDecided={async () => {
                setProposals(await fetchProposals());
                onChange();
              }}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function ProposalItem({
  proposal,
  canConfirm,
  onDecided,
}: {
  proposal: Proposal;
  canConfirm: boolean;
  onDecided: () => void;
}) {
  const [date, setDate] = useState(proposal.proposed_date);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function decide(decision: "confirmado" | "rejeitado") {
    const { error: apiError } = await api.POST("/api/deadline-proposals/{proposal_id}/decision", {
      params: { path: { proposal_id: proposal.id } },
      body: {
        decision,
        confirmed_date: decision === "confirmado" ? date : null,
        note: note.trim() || null,
      },
    });
    if (apiError) {
      setError(errorMessage(apiError));
      return;
    }
    setError(null);
    onDecided();
  }

  return (
    <li className="proposal">
      <div className="page-header">
        <strong>{proposal.title}</strong>
        <span className={`badge prazo-${proposal.status}`}>{t.prazos.status[proposal.status]}</span>
      </div>
      <p>
        {proposal.status === "confirmado" && proposal.confirmed_date ? (
          <>{fill(t.prazos.confirmedFor, { date: formatDate(proposal.confirmed_date) })}</>
        ) : (
          <>
            {t.prazos.proposedDate}: <strong>{formatDate(proposal.proposed_date)}</strong>
          </>
        )}
        <span className="muted small">
          {" "}
          · {t.prazos.triggerKinds[proposal.trigger_kind]} em {formatDate(proposal.trigger_date)} ·{" "}
          {proposal.days} {t.prazos.units[proposal.unit].toLowerCase()}
        </span>
      </p>
      <details>
        <summary>{t.prazos.reasoning}</summary>
        <Reasoning steps={proposal.steps} />
      </details>
      {proposal.decided_at && (
        <p className="small approval">
          {fill(t.prazos.decidedBy, {
            status: t.prazos.status[proposal.status],
            name: proposal.decided_by_name ?? "",
            date: formatDateTime(proposal.decided_at),
          })}
          {proposal.decision_note && <>: “{proposal.decision_note}”</>}
        </p>
      )}
      {canConfirm && proposal.status === "proposto" && (
        <div className="decision">
          <label>
            {t.prazos.confirmedDate}
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </label>
          <input
            placeholder={t.prazos.note}
            value={note}
            maxLength={1000}
            onChange={(e) => setNote(e.target.value)}
          />
          <button type="button" onClick={() => decide("confirmado")}>
            {t.prazos.confirm}
          </button>
          <button type="button" className="secondary" onClick={() => decide("rejeitado")}>
            {t.prazos.reject}
          </button>
        </div>
      )}
      <ErrorText message={error} />
    </li>
  );
}
