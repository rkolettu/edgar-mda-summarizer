import threading
from concurrent.futures import Future
from types import SimpleNamespace

import psycopg
import pytest

from research import ingest, interpret, llm, store
from tests.test_research_audit import company, model  # noqa: F401 - fixtures
from tests.test_research_ingest import nvda_sec  # noqa: F401 - fixture
from tests.test_research_interpret import company as narrative_company, model as narrative_model  # noqa: F401
from tests.test_research_snapshot import company_sec  # noqa: F401 - fixture


@pytest.mark.parametrize("error", [None, llm.ModelUnavailable("busy", quota=False, busy=True), TimeoutError("model timeout")])
def test_long_model_wait_keeps_database_active_and_preserves_result(monkeypatch, error):
    future = Future()
    result = object()
    queries = []
    owner = threading.get_ident()

    def execute(sql):
        assert threading.get_ident() == owner
        queries.append(sql)

    def wait(futures, timeout):
        assert tuple(futures) == (future,) and timeout == 60
        if len(queries) < 6:  # six minutes without actually sleeping
            return set(), {future}
        if error is None:
            future.set_result(result)
        else:
            future.set_exception(error)
        return {future}, set()

    monkeypatch.setattr(interpret, "wait", wait)
    conn = SimpleNamespace(execute=execute)
    if error is None:
        assert interpret._model_result(conn, future) is result
    else:
        with pytest.raises(type(error)) as exc:
            interpret._model_result(conn, future)
        assert exc.value is error
    assert queries == ["SELECT 1"] * 6


def test_failed_database_heartbeat_is_not_hidden(monkeypatch):
    failure = psycopg.OperationalError("connection lost")

    def execute(sql):
        raise failure

    monkeypatch.setattr(interpret, "wait", lambda *a, **kw: (set(), set()))
    with pytest.raises(psycopg.OperationalError) as exc:
        interpret._model_result(SimpleNamespace(execute=execute), Future())
    assert exc.value is failure


def test_generate_runs_model_off_the_database_thread(monkeypatch):
    owner = threading.get_ident()
    result = object()
    calls = []

    def generate(*args, **kwargs):
        assert threading.get_ident() != owner
        calls.append((args, kwargs))
        return result

    monkeypatch.setattr(llm, "generate", generate)
    assert interpret._generate(SimpleNamespace(execute=lambda sql: None), "audit", deadline=123) is result
    assert calls == [(("audit",), {"deadline": 123})]


@pytest.fixture
def slow_connection(research_conn, monkeypatch):
    owner = threading.get_ident()
    queries = []
    waits = {}
    real_wait = interpret.wait

    class Connection:
        def execute(self, sql, *args, **kwargs):
            assert threading.get_ident() == owner
            if sql == "SELECT 1":
                queries.append(sql)
            return research_conn.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(research_conn, name)

    def wait(futures, timeout):
        future, = futures
        count = waits.get(future, 0)
        waits[future] = count + 1
        if count < 6:  # simulate each model call taking longer than Neon's idle limit
            return set(), {future}
        return real_wait(futures, timeout=timeout)

    monkeypatch.setattr(interpret, "wait", wait)
    return Connection(), queries


def test_delayed_extraction_and_synthesis_persist_and_release_locks(slow_connection, narrative_company, narrative_model):
    conn, queries = slow_connection
    assert interpret.run(conn, narrative_company["company_id"]) is True
    assert len(queries) == 18  # two extractions and one synthesis
    assert conn.execute("SELECT count(*) FROM analysis_runs WHERE status = 'running'").fetchone()[0] == 0
    assert store.load_snapshot(conn, narrative_company["company_id"])["payload"]["insights"]["status"] == "ready"


@pytest.mark.parametrize("failed_stage", [None, "synthesize", "audit"])
def test_delayed_upgrade_preserves_fallbacks_and_completes_job(
    slow_connection, company, model, monkeypatch, failed_stage
):
    conn, queries = slow_connection
    company_id = company["company_id"]
    interpret.run(conn, company_id)
    conn.execute("UPDATE model_outputs SET model = 'fallback' WHERE stage IN ('synthesize', 'audit')")
    original = interpret.stored_outputs(conn, company_id)
    real_generate = llm.generate

    def generate(stage, *args, **kwargs):
        if stage == failed_stage:
            raise llm.ModelUnavailable("model timed out", quota=False, busy=True)
        return real_generate(stage, *args, **kwargs)

    monkeypatch.setattr(llm, "generate", generate)
    queries.clear()
    assert ingest._interpret(conn, company_id) is True
    assert len(queries) == 12  # synthesis and audit, including their failure paths
    assert conn.execute("SELECT count(*) FROM analysis_runs WHERE status = 'running'").fetchone()[0] == 0
    if failed_stage:
        remaining = interpret.stored_outputs(conn, company_id)
        key = next(key for key in original if key[1] == failed_stage)
        assert remaining[key] == original[key]
        assert conn.execute("SELECT status FROM analysis_runs WHERE stage = %s ORDER BY run_id DESC LIMIT 1",
                            (failed_stage,)).fetchone()[0] == "failed"
