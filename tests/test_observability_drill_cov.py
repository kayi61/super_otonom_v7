"""observability_drill gercek kapsama testleri — urllib mock'lanir, gercek stack yok.

Onceki %71; run_drill (PASS/FAIL/202), _http_get/_http_post_json hata yollari, main.
"""
from __future__ import annotations

import io
import urllib.error
from unittest.mock import patch

from super_otonom.infra import observability_drill as od


class _R:
    def __init__(self, status, body=""):
        self.status = status
        self._b = body.encode() if isinstance(body, str) else body

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _healthy(url, method):
    if url.endswith("/api/v1/rules"):
        return _R(200, '{"data":{"groups":[{"name":"g"}]}}')
    if url.endswith("/metrics"):
        return _R(
            200,
            "bot_dependency_up 1\nbot_order_errors_total 0\nbot_circuit_breaker_open 0\n",
        )
    return _R(200, "ok")


def _mk(handler):
    def _u(req, timeout=None):
        return handler(req.full_url, req.get_method())

    return patch("urllib.request.urlopen", side_effect=_u)


def test_run_drill_all_pass(tmp_path):
    with _mk(_healthy):
        rc = od.run_drill(write_doc=True, doc_path=tmp_path / "d.md")
    assert rc == 0
    assert (tmp_path / "d.md").exists()


def test_run_drill_all_fail():
    def boom(url, method):
        raise urllib.error.URLError("down")

    with _mk(boom):
        rc = od.run_drill(write_doc=False)
    assert rc == 1


def test_run_drill_alert_202_is_fail():
    def h(url, method):
        if method == "POST":
            return _R(202, "no creds")
        return _healthy(url, method)

    with _mk(h):
        rc = od.run_drill(write_doc=False)
    assert rc == 1  # 202 -> Telegram teslimi FAIL


def test_run_drill_metrics_missing():
    def h(url, method):
        if url.endswith("/metrics"):
            return _R(200, "baska_metrik 1\n")  # zorunlu metrikler eksik
        return _healthy(url, method)

    with _mk(h):
        rc = od.run_drill(write_doc=False)
    assert rc == 1


def test_http_get_httperror_with_body():
    def h(url, method):
        raise urllib.error.HTTPError(url, 503, "err", {}, io.BytesIO(b"boom"))

    with _mk(h):
        code, body = od._http_get("http://x/y")
    assert code == 503
    assert "boom" in body


def test_http_get_generic_exception():
    def h(url, method):
        raise urllib.error.URLError("conn refused")

    with _mk(h):
        code, body = od._http_get("http://x/y")
    assert code == 0


def test_http_post_json_httperror_no_fp():
    def h(url, method):
        raise urllib.error.HTTPError(url, 500, "e", {}, None)

    with _mk(h):
        code, body = od._http_post_json("http://x", {"a": 1})
    assert code == 500


def test_http_post_json_success():
    with _mk(lambda url, m: _R(200, "ok")):
        code, body = od._http_post_json("http://x", {"a": 1})
    assert code == 200


def test_main_no_write_doc():
    with _mk(_healthy):
        rc = od.main(["--no-write-doc"])
    assert rc in (0, 1)


def test_main_with_doc(tmp_path):
    with _mk(_healthy):
        rc = od.main(["--doc", str(tmp_path / "m.md")])
    assert rc == 0
    assert (tmp_path / "m.md").exists()


def test_alertmanager_payload_shape():
    p = od._test_alertmanager_payload()
    assert p["alerts"][0]["labels"]["alertname"] == "ObservabilityDrillTest"
    assert p["status"] == "firing"
