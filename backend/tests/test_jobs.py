import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from legalos.audit.models import AuditEvent
from legalos.jobs import handlers  # noqa: F401  (registers handlers)
from legalos.jobs.models import Job
from legalos.jobs.queue import _HANDLERS, enqueue, retry_delay_seconds, run_one
from tests.conftest import app_db


def _job(owner_engine: Engine) -> Job:
    with Session(owner_engine) as db:
        return db.scalars(select(Job)).one()


def test_job_runs_in_its_firm_context(make_firm, make_member, owner_engine) -> None:
    a = make_firm("Alfa")
    m = make_member(a)
    with app_db(tenant_id=a, user_id=m.user_id) as db:
        enqueue(db, "system.ping", tenant_id=a, enqueued_by=m.user_id)

    assert run_one("test-worker") is True
    assert run_one("test-worker") is False  # queue is empty

    job = _job(owner_engine)
    assert job.status == "succeeded" and job.attempts == 1 and job.finished_at is not None
    with Session(owner_engine) as db:
        event = db.scalars(select(AuditEvent).where(AuditEvent.action == "system.ping")).one()
    assert event.tenant_id == a and event.actor_user_id == m.user_id


@pytest.fixture
def failing_handler():
    def boom(db, job):
        raise RuntimeError("falha simulada")

    _HANDLERS["test.boom"] = boom
    yield
    del _HANDLERS["test.boom"]


def test_failed_job_is_retried_then_dead(failing_handler, make_firm, owner_engine) -> None:
    a = make_firm("Alfa")
    with app_db(tenant_id=a) as db:
        enqueue(db, "test.boom", tenant_id=a, max_attempts=2)

    assert run_one("w") is True
    job = _job(owner_engine)
    assert job.status == "queued" and job.attempts == 1
    assert job.last_error == "RuntimeError: falha simulada"
    assert run_one("w") is False  # not ready until the backoff delay passes

    with Session(owner_engine) as db, db.begin():
        db.execute(text("UPDATE jobs SET run_after = now()"))
    assert run_one("w") is True
    job = _job(owner_engine)
    assert job.status == "dead" and job.attempts == 2


def test_unknown_job_kind_fails(make_firm, owner_engine) -> None:
    a = make_firm("Alfa")
    with app_db(tenant_id=a) as db:
        enqueue(db, "does.not.exist", tenant_id=a)
    run_one("w")
    assert "No handler registered" in (_job(owner_engine).last_error or "")


def test_stale_running_job_is_reclaimed(make_firm, owner_engine) -> None:
    a = make_firm("Alfa")
    with app_db(tenant_id=a) as db:
        enqueue(db, "system.ping", tenant_id=a)
    with Session(owner_engine) as db, db.begin():
        db.execute(
            text(
                "UPDATE jobs SET status='running', locked_by='dead-worker',"
                " locked_at = now() - interval '1 hour', attempts = 1"
            )
        )
    assert run_one("w") is True
    job = _job(owner_engine)
    assert job.status == "succeeded" and job.attempts == 2


def test_app_role_cannot_change_job_state_directly(make_firm) -> None:
    a = make_firm("Alfa")
    with app_db(tenant_id=a) as db:
        enqueue(db, "system.ping", tenant_id=a)
    from sqlalchemy.exc import ProgrammingError

    with pytest.raises(ProgrammingError, match="permission denied"), app_db(tenant_id=a) as db:
        db.execute(text("UPDATE jobs SET status = 'succeeded'"))


def test_retry_backoff() -> None:
    assert [retry_delay_seconds(n) for n in (1, 2, 3)] == [30, 60, 120]
    assert retry_delay_seconds(50) == 3600
