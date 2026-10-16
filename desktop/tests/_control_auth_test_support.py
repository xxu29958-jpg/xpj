"""Shared preparation for the existing  control auth consumers."""

from __future__ import annotations

import http.client

from backend_manager.control_server import (
    ControlServer,
)


def _bootstrap_cookie_header(server: ControlServer, tmp_path) -> str:
    import re as _re
    import urllib.parse as _urlparse

    bootstrap_path = tmp_path / "bootstrap.html"
    server.prepare_web_bootstrap(bootstrap_path)
    document = bootstrap_path.read_text(encoding="utf-8")
    match = _re.search(r'name="bootstrap_token" value="([^"]+)"', document)
    assert match is not None
    body = _urlparse.urlencode({"bootstrap_token": match.group(1)}).encode()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
    connection.request(
        "POST",
        "/api/bootstrap",
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response = connection.getresponse()
    assert response.status == 200
    cookies = response.headers.get_all("Set-Cookie")
    response.read()
    connection.close()
    assert cookies is not None
    return "; ".join(cookie.partition(";")[0] for cookie in cookies)
