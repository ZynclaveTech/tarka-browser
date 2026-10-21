"""M4 Task 8: list the hosts a Chromium net log shows the browser contacting,
and check them against Tark's allowed-hosts list (spec §5.3)."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from net_hosts import contacted_hosts, load_allowed, main, strangers  # noqa: E402

TYPES = {"HOST_RESOLVER_MANAGER_REQUEST": 1, "URL_REQUEST_START_JOB": 2,
         "QUIC_SESSION": 3, "HTTP_TRANSACTION_SEND_REQUEST_HEADERS": 4}


def log(*events):
    return {"constants": {"logEventTypes": TYPES},
            "events": [{"type": TYPES[t], "params": p} for t, p in events]}


def test_hosts_come_from_dns_requests_and_quic_sessions():
    netlog = log(("HOST_RESOLVER_MANAGER_REQUEST", {"host": "https://shodhya.com"}),
                 ("URL_REQUEST_START_JOB", {"url": "https://api.shodhya.com/suggest?q=a"}),
                 ("QUIC_SESSION", {"host": "cdn.jsdelivr.net"}))
    assert set(contacted_hosts(netlog)) == {"shodhya.com", "api.shodhya.com", "cdn.jsdelivr.net"}


def test_urls_inside_headers_are_not_contacts():
    # A response header naming a host (report-to, CSP report-uri) is not a request.
    netlog = log(("HTTP_TRANSACTION_SEND_REQUEST_HEADERS",
                  {"headers": ["report-to: {\"url\":\"https://a.nel.cloudflare.com/report\"}"]}))
    assert contacted_hosts(netlog) == {}


def test_browser_internal_schemes_are_not_contacts():
    netlog = log(("URL_REQUEST_START_JOB", {"url": "chrome-extension://abc/background.html"}),
                 ("URL_REQUEST_START_JOB", {"url": "chrome://newtab/"}),
                 ("URL_REQUEST_START_JOB", {"url": "data:text/plain,x"}),
                 ("URL_REQUEST_START_JOB", {"url": "wss://shodhya.com/live"}))
    assert set(contacted_hosts(netlog)) == {"shodhya.com"}


def test_counts_each_contact():
    netlog = log(("URL_REQUEST_START_JOB", {"url": "https://shodhya.com/a"}),
                 ("URL_REQUEST_START_JOB", {"url": "https://shodhya.com/b"}))
    assert contacted_hosts(netlog)["shodhya.com"] == 2


def test_loopback_is_not_a_contact():
    netlog = log(("URL_REQUEST_START_JOB", {"url": "http://127.0.0.1:8766/x"}),
                 ("HOST_RESOLVER_MANAGER_REQUEST", {"host": "http://localhost:9222"}))
    assert contacted_hosts(netlog) == {}


def test_allowed_list_ignores_comments_and_blank_lines(tmp_path):
    f = tmp_path / "allowed.txt"
    f.write_text("# §5.3\nshodhya.com\n\n  api.shodhya.com  # suggestions\n")
    assert load_allowed(f) == {"shodhya.com", "api.shodhya.com"}


def test_strangers_are_hosts_not_on_the_list():
    assert strangers({"shodhya.com": 3, "evil.example": 1}, {"shodhya.com"}) == ["evil.example"]


def test_main_exits_nonzero_when_a_stranger_appears(tmp_path, capsys):
    netlog = tmp_path / "netlog.json"
    netlog.write_text(json.dumps(log(("URL_REQUEST_START_JOB", {"url": "https://evil.example/"}),
                                     ("URL_REQUEST_START_JOB", {"url": "https://shodhya.com/"}))))
    allowed = tmp_path / "allowed.txt"
    allowed.write_text("shodhya.com\n")
    assert main([str(netlog), "--allowed", str(allowed)]) == 1
    assert "evil.example" in capsys.readouterr().out
    allowed.write_text("shodhya.com\nevil.example\n")
    assert main([str(netlog), "--allowed", str(allowed)]) == 0


def _settings_page_hosts():
    """Hosts the Settings page lists: the rows that every patch in the series
    touching tark_contacted_hosts.cc adds (the settings patch makes the list,
    later patches add their own rows)."""
    import re
    root = pathlib.Path(__file__).resolve().parents[2]
    hosts = set()
    for name in (root / "patches/series").read_text().split():
        patch = (root / "patches" / name).read_text()
        added, current = [], ""
        for line in patch.splitlines():
            if line.startswith("+++ "):
                current = line
            elif line.startswith("+") and current.endswith("/tark_contacted_hosts.cc"):
                added.append(line[1:])
        added = "\n".join(added)
        if added:
            for row in re.findall(r'\{"tarkConnects\w+",\s*IDS_\w+,\s*((?:u"[^"]*"\s*)+)\}', added):
                text = "".join(re.findall(r'u"([^"]*)"', row))
                hosts |= {h.strip() for h in text.split(",") if h.strip()}
    return hosts


def test_settings_page_hosts_include_later_patches_rows():
    assert {"shodhya.com", "pgl.yoyo.org", "gettarka.com"} <= _settings_page_hosts()


def test_allowed_list_matches_the_settings_page():
    root = pathlib.Path(__file__).resolve().parents[2]
    assert load_allowed(root / "utils/allowed_hosts.txt") == _settings_page_hosts()
