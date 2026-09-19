from argos.dashboard.pages import quality


class ClientWithoutToken:
    admin_token = None


def test_quality_page_stops_before_api_calls_without_admin_token(monkeypatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(quality.st, "info", messages.append)

    quality.render_quality(ClientWithoutToken())  # type: ignore[arg-type]

    assert messages == ["Enter the admin token in the sidebar to inspect operational data."]
