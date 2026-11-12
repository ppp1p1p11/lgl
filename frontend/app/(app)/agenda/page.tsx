"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { type Task, TaskList } from "@/components/Tasks";
import { api } from "@/lib/api/client";
import { t } from "@/lib/i18n";

const STATUSES = Object.keys(t.tarefas.status) as Task["status"][];

export default function AgendaPage() {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [status, setStatus] = useState<Task["status"]>("aberta");
  const [mine, setMine] = useState(false);

  const fetchTasks = useCallback(async () => {
    const { data } = await api.GET("/api/tasks", { params: { query: { status, mine } } });
    return data ?? [];
  }, [status, mine]);

  useEffect(() => {
    fetchTasks().then(setTasks);
  }, [fetchTasks]);

  return (
    <>
      <div className="page-header">
        <h1>{t.agenda.title}</h1>
        <Link className="button secondary" href="/agenda/feriados">
          {t.agenda.holidays}
        </Link>
      </div>
      <p className="muted">{t.agenda.intro}</p>
      <div className="toolbar">
        <label>
          {t.processos.fields.status}
          <select value={status} onChange={(e) => setStatus(e.target.value as Task["status"])}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t.tarefas.status[s]}
              </option>
            ))}
          </select>
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />{" "}
          {t.tarefas.mine}
        </label>
      </div>
      {tasks === null ? (
        <p className="muted">{t.common.loading}</p>
      ) : (
        <TaskList tasks={tasks} showMatter onChange={() => fetchTasks().then(setTasks)} />
      )}
    </>
  );
}
