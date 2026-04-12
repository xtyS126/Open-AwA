from fastapi import HTTPException

import db.models as models


class _DummySession:
    def __init__(self):
        self.rollback_called = 0
        self.close_called = 0

    def rollback(self):
        self.rollback_called += 1

    def close(self):
        self.close_called += 1


class _BoundLogger:
    def __init__(self, sink):
        self._sink = sink

    def info(self, message):
        self._sink.append(("info", message))

    def warning(self, message):
        self._sink.append(("warning", message))

    def error(self, message):
        self._sink.append(("error", message))

    def opt(self, **kwargs):
        return self


class _DummyLogger:
    def __init__(self, sink):
        self._sink = sink

    def bind(self, **kwargs):
        return _BoundLogger(self._sink)


def test_get_db_logs_info_for_auth_http_exception(monkeypatch):
    """401/403 鉴权异常不应被记录为数据库 ERROR。"""
    logs = []
    session = _DummySession()
    monkeypatch.setattr(models, "SessionLocal", lambda: session)
    monkeypatch.setattr(models, "logger", _DummyLogger(logs))

    gen = models.get_db()
    assert next(gen) is session

    try:
        gen.throw(HTTPException(status_code=401, detail="Could not validate credentials"))
    except HTTPException:
        pass

    assert session.rollback_called == 1
    assert session.close_called == 1
    assert any(level == "info" for level, _ in logs)
    assert not any(level == "error" for level, _ in logs)


def test_get_db_logs_error_for_unexpected_exception(monkeypatch):
    """非 HTTP 异常仍应按数据库异常记录 ERROR。"""
    logs = []
    session = _DummySession()
    monkeypatch.setattr(models, "SessionLocal", lambda: session)
    monkeypatch.setattr(models, "logger", _DummyLogger(logs))

    gen = models.get_db()
    assert next(gen) is session

    try:
        gen.throw(RuntimeError("db exploded"))
    except RuntimeError:
        pass

    assert session.rollback_called == 1
    assert session.close_called == 1
    assert any(level == "error" for level, _ in logs)
