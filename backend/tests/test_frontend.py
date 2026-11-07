import re
from pathlib import Path

import pytest

from core.security import OPERATOR_UI_VALUE
from tickets.status import TicketStatus

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
SCRIPTS = sorted((FRONTEND / "js").glob("*.js"))
PAGES = sorted(FRONTEND.glob("*.html"))
HTML_SINKS = re.compile(
    r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(|new Function"
)


@pytest.mark.parametrize("path", SCRIPTS + PAGES, ids=lambda path: path.name)
def test_untrusted_text_never_goes_through_an_html_sink(path: Path) -> None:
    """SPEC §10: customer, model and KB text is inserted with textContent only."""
    assert HTML_SINKS.findall(path.read_text()) == []


@pytest.mark.parametrize("path", PAGES, ids=lambda path: path.name)
def test_pages_load_scripts_from_files_only(path: Path) -> None:
    """The nginx Content-Security-Policy allows no inline script."""
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", path.read_text(), re.S)

    assert scripts
    for attributes, body in scripts:
        assert 'src="/js/' in attributes
        assert body.strip() == ""


def test_the_ui_knows_every_status() -> None:
    source = (FRONTEND / "js" / "format.js").read_text()
    listed = re.search(r"STATUSES = \[(.*?)\]", source, re.S).group(1)

    assert re.findall(r'"(\w+)"', listed) == [status.value for status in TicketStatus]


def test_operator_actions_carry_the_csrf_header_and_json() -> None:
    source = (FRONTEND / "js" / "api.js").read_text()

    assert f'"X-Requested-By": "{OPERATOR_UI_VALUE}"' in source
    assert '"Content-Type": "application/json"' in source


def test_nginx_serves_kb_links_and_sends_a_strict_policy() -> None:
    config = (FRONTEND / "nginx.conf").read_text()

    assert "location ~ ^/kb/[^/]+$" in config
    assert "try_files /kb.html =404;" in config
    assert "script-src 'self';" in config
    assert "frame-ancestors 'none'" in config
