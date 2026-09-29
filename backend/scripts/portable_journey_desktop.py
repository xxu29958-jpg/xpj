"""The real Desktop HTTP bridge against the isolated PostgreSQL application.

This qualifies transport and browser delivery, not the held Windows lifecycle.
Only the already-paired controller context is supplied by the fixture.
"""

import secrets
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def desktop_browser(browser, backend_url, ledger_id):
    from tests.test_desktop_web_bridge_session import _mint_principal

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "desktop"))
    from backend_manager.control_server import ControlServer
    from backend_manager.web_bff import BridgeContext

    principal = _mint_principal(ledger_id=ledger_id)

    class Controller:
        def is_manager_shutting_down(self):
            return False

        def product_bridge_context(self):
            return BridgeContext(backend_url, principal.token)

        def note_product_bridge_auth_failure(self, status, token):
            assert token == principal.token and status in {200, 401, 403}
            return status == 401

    with tempfile.TemporaryDirectory(prefix="portable-desktop-") as directory:
        root = Path(directory)
        ui = root / "manager.html"
        ui.write_text("__CONTROL_TOKEN__", encoding="utf-8")
        manager = ControlServer("127.0.0.1", 0, controller=Controller(), token=secrets.token_urlsafe(32),
            instance_secret=secrets.token_urlsafe(32), ui_html=ui)
        thread = threading.Thread(target=manager.serve_forever)
        thread.start()
        context = browser.new_context(viewport={"width": 1280, "height": 960})
        try:
            page = context.new_page()
            page.goto(manager.prepare_web_bootstrap(root / "bootstrap.html"))
            origin = f"http://127.0.0.1:{manager.server_address[1]}"
            page.wait_for_url(origin + "/**")
            yield page, origin
        finally:
            context.close()
            manager.shutdown()
            manager.server_close()
            thread.join(timeout=5)
