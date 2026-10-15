"""Log-injection hardening: CR/LF in text-format logs must not produce extra lines."""

from ff_feed import obs


def test_text_log_is_single_line(monkeypatch, capsys):
    monkeypatch.setenv("FF_LOG_FORMAT", "text")
    log = obs.configure_logging()
    log.info("request", extra={"ff": {"service": "x", "path": "/a\nFAKE level=ERROR\r b"}})
    out = capsys.readouterr().out
    assert out.endswith("\n") and len(out.splitlines()) == 1
    assert "\r" not in out and " " not in out
