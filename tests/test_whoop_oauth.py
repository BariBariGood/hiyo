from pathlib import Path

from hiyo.whoop_oauth import WhoopOAuth


def test_whoop_status_does_not_expose_tokens_without_connection(tmp_path, monkeypatch):
    monkeypatch.delenv("WHOOP_CLIENT_ID", raising=False)
    monkeypatch.delenv("WHOOP_CLIENT_SECRET", raising=False)
    status = __import__("asyncio").run(WhoopOAuth(tmp_path / "oauth.json").refresh_status())
    assert status == {"connected": False, "configured": False, "data_status": "not_connected"}


def test_begin_stores_state_only_server_side(tmp_path, monkeypatch):
    monkeypatch.setenv("WHOOP_CLIENT_ID", "client-id")
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", "secret")
    oauth = WhoopOAuth(tmp_path / "oauth.json")
    url = oauth.begin("https://hiyo.example/api/whoop/callback")
    assert "client_secret" not in url
    stored = Path(tmp_path / "oauth.json").read_text()
    assert "client-id" not in stored or "client_secret" not in stored
    assert "pending_state" in stored
