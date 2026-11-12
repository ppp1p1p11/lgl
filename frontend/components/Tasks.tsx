"use client";

import Link from "next/link";
import { useState } from "react";

import { ErrorText } from "@/components/ErrorText";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorMessage } from "@/lib/errors";
import { formatDate, todayIso } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useCan } from "@/lib/session";

export type Task = components["schemas"]["TaskOut"];
type Person = { user_id: string; name: string };

/** A list of tasks with the actions to conclude, reopen or cancel each one. */
export function TaskList({
  tasks,
  showMatter = false,
  onChange,
}: {
  tasks: Task[];
  showMatter?: boolean;
  onChange: () => void;
}) {
  const canManage = useCan("manage_tasks");
  const today = todayIso();

  async function setStatus(task: Task, status: Task["status"]) {
    await api.PATCH("/api/tasks/{task_id}", {
      params: { path: { task_id: task.id } },
      body: { status },
    });
    onChange();
  }

  if (tasks.length === 0) return <p className="muted">{t.tarefas.empty}</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>{t.tarefas.name}</th>
            {showMatter && <th>{t.tarefas.matter}</th>}
            <th>{t.tarefas.due}</th>
            <th>{t.tarefas.assignee}</th>
            <th>{t.processos.fields.status}</th>
            {canManage && <th>{t.common.actions}</th>}
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => {
            const overdue =
              task.status === "aberta" && task.due_date != null && task.due_date < today;
            return (
              <tr key={task.id}>
                <td>
                  {task.title}
                  {task.origin === "prazo" && (
                    <span className="badge"> {t.tarefas.origin.prazo}</span>
                  )}
                  {task.notes && <div className="muted small">{task.notes}</div>}
                </td>
                {showMatter && (
                  <td>
                    <Link href={`/processos/${task.matter_id}`}>{task.matter_title}</Link>
                  </td>
                )}
                <td>
                  {task.due_date ? formatDate(task.due_date) : t.common.none}
                  {overdue && <span className="badge danger"> {t.tarefas.overdue}</span>}
                </td>
                <td>{task.assignee_name ?? t.tarefas.nobody}</td>
                <td>
                  <span className={`badge tarefa-${task.status}`}>
                    {t.tarefas.status[task.status]}
                  </span>
                </td>
                {canManage && (
                  <td className="row-actions">
                    {task.status === "aberta" ? (
                      <>
                        <button type="button" onClick={() => setStatus(task, "concluida")}>
                          {t.tarefas.done}
                        </button>
                        <button
                          type="button"
                          className="link"
                          onClick={() => setStatus(task, "cancelada")}
                        >
                          {t.tarefas.cancel}
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => setStatus(task, "aberta")}
                      >
                        {t.tarefas.reopen}
                      </button>
                    )}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Tasks of one processo, with a form to add a task. */
export function MatterTasks({
  matterId,
  tasks,
  people,
  onChange,
}: {
  matterId: string;
  tasks: Task[];
  people: Person[];
  onChange: () => void;
}) {
  const canManage = useCan("manage_tasks");
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onAdd(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const { error: apiError } = await api.POST("/api/matters/{matter_id}/tasks", {
      params: { path: { matter_id: matterId } },
      body: {
        title: String(form.get("title")),
        due_date: String(form.get("due_date") ?? "") || null,
        assignee_user_id: String(form.get("assignee") ?? "") || null,
        notes: String(form.get("notes") ?? "").trim() || null,
      },
    });
    if (apiError) {
      setError(errorMessage(apiError));
      return;
    }
    setError(null);
    setShowForm(false);
    onChange();
  }

  return (
    <section className="card">
      <div className="page-header">
        <h2>{t.tarefas.title}</h2>
        {canManage && !showForm && (
          <button type="button" className="secondary" onClick={() => setShowForm(true)}>
            {t.tarefas.new}
          </button>
        )}
      </div>
      {showForm && (
        <form onSubmit={onAdd} className="subform">
          <div className="grid">
            <label>
              {t.tarefas.name}
              <input name="title" required minLength={3} maxLength={300} />
            </label>
            <label>
              {t.tarefas.due} <span className="muted">({t.common.optional})</span>
              <input name="due_date" type="date" />
            </label>
            <label>
              {t.tarefas.assignee}
              <select name="assignee" defaultValue="">
                <option value="">{t.tarefas.nobody}</option>
                {people.map((p) => (
                  <option key={p.user_id} value={p.user_id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t.tarefas.notes} <span className="muted">({t.common.optional})</span>
              <input name="notes" maxLength={2000} />
            </label>
          </div>
          <ErrorText message={error} />
          <div className="actions">
            <button type="submit">{t.common.add}</button>
            <button type="button" className="secondary" onClick={() => setShowForm(false)}>
              {t.common.cancel}
            </button>
          </div>
        </form>
      )}
      <TaskList tasks={tasks} onChange={onChange} />
    </section>
  );
}
