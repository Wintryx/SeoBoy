"""Offline project overview built from an existing audit run."""

from __future__ import annotations

import csv
import html
from pathlib import Path
from typing import TYPE_CHECKING, Any

from seoboy.analysis.audit_data import RunData
from seoboy.reporting.gsc_report import latest_page_rows
from seoboy.shared.urls import relative_url
from seoboy.shared.util import format_local, parse_utc

if TYPE_CHECKING:
    from seoboy.reporting.run_report import ReportData, StoredAction


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _link(url: str | None, label: str | None = None) -> str:
    if not url:
        return "–"
    text = _e(label or url)
    if url.startswith(("http://", "https://")):
        return f'<a href="{_e(url)}" rel="noreferrer">{text}</a>'
    return text


def _display(data: RunData, url: str) -> str:
    try:
        return relative_url(url, data.config.allowed_hosts)
    except ValueError:
        return url


def _pct(clicks: int, impressions: int) -> str:
    return "–" if impressions <= 0 else f"{clicks / impressions * 100:.1f} %"


def _number(value: Any, digits: int = 1) -> str:
    return "–" if value is None else f"{float(value):.{digits}f}"


def _delta(current: int, previous: int | None) -> str:
    if previous is None:
        return "–"
    value = current - previous
    return f"+{value}" if value > 0 else str(value)


def _action_urls(report: ReportData, action: StoredAction) -> list[str]:
    urls: list[str] = []
    for key in action.finding_keys:
        result = report.result_map.get(key)
        if result is None:
            continue
        for url_id, _relation in result.urls:
            url = report.data.url_string(url_id)
            if url and url not in urls:
                urls.append(url)
    return urls


def _changes(config: Any) -> list[dict[str, str]]:
    if config.config_path is None:
        return []
    path = Path(config.config_path).parent / "changes.csv"
    if not path.is_file():
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except OSError:
        return []
    result: list[dict[str, str]] = []
    for row in rows[-20:]:
        result.append(
            {
                "date": str(row.get("date") or ""),
                "scope": str(row.get("scope") or ""),
                "url": str(row.get("url") or ""),
                "summary": str(row.get("summary") or ""),
            }
        )
    return result


def _page_metrics(data: RunData) -> dict[str, dict[str, Any]]:
    return {row["url"]: row for row in latest_page_rows(data)}


def _page_rows(data: RunData) -> list[dict[str, Any]]:
    metrics = _page_metrics(data)
    rows: list[dict[str, Any]] = []
    for info in data.urls.values():
        if info.state != "finished":
            continue
        observation = data.observation(info.url_id)
        signals = observation.signals if observation is not None else {}
        canonical = signals.get("canonical") or []
        metric = metrics.get(info.url)
        rows.append(
            {
                "url": info.url,
                "display": _display(data, info.url),
                "status": data.final_status(info.url_id),
                "title": observation.title if observation is not None else "",
                "page_type": info.page_type or "unknown",
                "business_value": info.business_value,
                "canonical": canonical[0] if isinstance(canonical, list) and canonical else None,
                "noindex": bool(signals.get("noindex")),
                "clicks": int(metric["clicks"]) if metric else None,
                "impressions": int(metric["impressions"]) if metric else None,
                "position": metric.get("position") if metric else None,
                "coverage": metric.get("coverage") if metric else None,
            }
        )
    rows.sort(
        key=lambda row: (
            -int(row["impressions"] or 0),
            0 if row["business_value"] == "high" else 1,
            row["display"],
        )
    )
    return rows


def _monitor_rows(data: RunData) -> list[dict[str, Any]]:
    try:
        rows = data.connection.execute(
            "SELECT watch_key, url, state, reason_code, last_seen, confirmed_at, recovered_at "
            "FROM monitor_events WHERE project_id = ? "
            "ORDER BY CASE state WHEN 'confirmed' THEN 0 WHEN 'suspect' THEN 1 ELSE 2 END, url",
            (data.config.project_id,),
        ).fetchall()
    except Exception:
        return []
    return [dict(row) for row in rows]


def _status(value: int | None) -> str:
    if value is None:
        return "–"
    if 200 <= value < 300:
        return f'<span class="ok">{value}</span>'
    if 300 <= value < 400:
        return f'<span class="warn">{value}</span>'
    return f'<span class="bad">{value}</span>'


def write_project_overview(folder: Path, report: ReportData) -> Path:
    """Write a self-contained, offline HTML overview next to the reports."""
    data = report.data
    run = data.run
    actions = [
        action
        for action in report.actions
        if action.status not in {"done", "ignored"}
    ]
    top_actions = actions[:3]
    pages = _page_rows(data)
    changes = _changes(data.config)
    monitor_rows = _monitor_rows(data)
    checked = sum(1 for info in data.urls.values() if info.state == "finished")
    findings = sum(1 for result in report.results if result.outcome == "finding")
    open_p2 = sum(1 for action in actions if action.priority == 2)
    type_options = sorted({row["page_type"] for row in pages})
    status_options = sorted({str(row["status"]) for row in pages if row["status"] is not None})

    action_html: list[str] = []
    for action in top_actions:
        urls = _action_urls(report, action)
        url_text = ", ".join(_e(_display(data, url)) for url in urls[:4]) or "–"
        action_html.append(
            f"""
            <article class="action p{action.priority}">
              <div class="action-head"><span class="badge">P{action.priority}</span>
                <h3>{_e(action.title)}</h3></div>
              <p>{_e(action.proposed_fix)}</p>
              <p class="muted">Betroffen: {url_text}</p>
              <p class="muted">Prüfen: {_e(action.verification)}</p>
            </article>
            """
        )
    if not action_html:
        action_html.append('<p class="empty">Keine offenen Maßnahmen.</p>')

    page_html: list[str] = []
    for row in pages:
        page_html.append(
            f"""
            <tr data-type="{_e(row['page_type'])}" data-status="{_e(row['status'])}">
              <td>{_link(row['url'], row['display'])}</td>
              <td>{_status(row['status'])}</td>
              <td>{_e(row['page_type'])}</td>
              <td>{_e(row['title'])}</td>
              <td>{'ja' if row['noindex'] else 'nein'}</td>
              <td>{_e(row['canonical'] or '–')}</td>
              <td>{'–' if row['clicks'] is None else row['clicks']}</td>
              <td>{'–' if row['impressions'] is None else row['impressions']}</td>
              <td>{_number(row['position'])}</td>
              <td>{'–' if row['coverage'] is None else f"{row['coverage'] * 100:.1f} %"}</td>
            </tr>
            """
        )

    monitor_html = "".join(
        f"<tr><td>{_link(row['url'], _display(data, row['url']))}</td>"
        f'<td class="{_e(row["state"])}">{_e(row["state"])}</td>'
        f"<td>{_e(row['reason_code'] or '–')}</td>"
        f"<td>{_e(row['last_seen'])}</td></tr>"
        for row in monitor_rows
    ) or '<tr><td colspan="4" class="muted">Noch keine Monitor-Messung. Mit <code>seoboy monitor check</code> starten.</td></tr>'

    changes_html = "".join(
        f"<li><strong>{_e(item['date'])}</strong> · {_e(item['scope'])}"
        f"{' · ' + _link(item['url']) if item['url'] else ''}<br>{_e(item['summary'])}</li>"
        for item in changes
    ) or '<li class="muted">Keine Änderungsnotizen (changes.csv).</li>'

    generated = format_local(parse_utc(run["started_at"])) if run.get("started_at") else "–"
    title = f"SeoBoy – {data.config.project_id}"
    html_text = f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<style>
:root {{ color-scheme: light dark; --bg:#f6f7f9; --card:#fff; --text:#1b1f24; --muted:#5d6673; --line:#d9dee6; --accent:#0b6bcb; --ok:#176b3a; --warn:#8a5a00; --bad:#a32626; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#14171b; --card:#1d2228; --text:#e8edf4; --muted:#a8b2bf; --line:#343c47; --accent:#69aef7; --ok:#74d39a; --warn:#f0c36b; --bad:#ff8b8b; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.55 system-ui,Segoe UI,Roboto,sans-serif; }}
main {{ max-width:1200px; margin:0 auto; padding:28px 18px 64px; }}
h1 {{ font-size:1.8rem; margin:0 0 4px; }} h2 {{ margin-top:2rem; }} h3 {{ margin:0; font-size:1rem; }}
.muted {{ color:var(--muted); }} .empty {{ color:var(--muted); }}
header {{ border-bottom:1px solid var(--line); padding-bottom:18px; margin-bottom:18px; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:18px 0; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; }}
.card strong {{ display:block; font-size:1.5rem; }}
.action {{ background:var(--card); border:1px solid var(--line); border-left:6px solid var(--accent); border-radius:8px; padding:12px 14px; margin:10px 0; }}
.action.p1 {{ border-left-color:var(--bad); }} .action.p2 {{ border-left-color:var(--warn); }}
.action-head {{ display:flex; gap:10px; align-items:center; }}
.badge {{ background:var(--accent); color:#fff; border-radius:5px; padding:1px 7px; font-weight:700; font-size:.8rem; }}
table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); }}
th,td {{ text-align:left; padding:8px; border-bottom:1px solid var(--line); vertical-align:top; }}
th {{ position:sticky; top:0; background:var(--card); }}
tr:last-child td {{ border-bottom:0; }}
td:nth-child(2),td:nth-child(7),td:nth-child(8),td:nth-child(9),td:nth-child(10) {{ white-space:nowrap; }}
.ok {{ color:var(--ok); font-weight:700; }} .warn {{ color:var(--warn); font-weight:700; }} .bad {{ color:var(--bad); font-weight:700; }}
.toolbar {{ display:flex; gap:10px; flex-wrap:wrap; margin:12px 0; }}
select {{ padding:7px 9px; border:1px solid var(--line); border-radius:7px; background:var(--card); color:var(--text); }}
a {{ color:var(--accent); }}
ul.changes {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px 18px 12px 32px; }}
footer {{ margin-top:28px; color:var(--muted); font-size:.85rem; }}
@media (max-width:760px) {{ table {{ display:block; overflow-x:auto; }} }}
</style>
</head>
<body><main>
<header>
  <h1>{_e(data.config.project_id)}</h1>
  <p class="muted">Projektübersicht · Lauf <code>{_e(run.get('run_id'))}</code> · {_e(run.get('status'))}<br>
  Erstellt: {_e(generated)} · Start-URL: {_link(data.config.start_url)}</p>
</header>

<section class="cards">
  <div class="card"><span class="muted">Geprüfte Seiten</span><strong>{checked}</strong></div>
  <div class="card"><span class="muted">Befunde</span><strong>{findings}</strong></div>
  <div class="card"><span class="muted">Offene Maßnahmen</span><strong>{len(actions)}</strong></div>
  <div class="card"><span class="muted">Offene P2</span><strong>{open_p2}</strong></div>
</section>

<h2>Was zuerst?</h2>
{''.join(action_html)}

<h2>Buchungs- und wichtige Seiten</h2>
<p class="muted">GSC-Werte stammen aus dem letzten verfügbaren page_query-Segment; die Abdeckung zeigt den Anteil erklärbarer Suchanfrage-Impressionen. Seiten ohne GSC-Zeile bleiben sichtbar.</p>
<div class="toolbar">
  <label>Seitentyp <select id="type"><option value="">alle</option>{''.join(f'<option value="{_e(value)}">{_e(value)}</option>' for value in type_options)}</select></label>
  <label>HTTP-Status <select id="status"><option value="">alle</option>{''.join(f'<option value="{_e(value)}">{_e(value)}</option>' for value in status_options)}</select></label>
</div>
<table id="pages">
<thead><tr><th>Zielseite</th><th>Status</th><th>Typ</th><th>Titel</th><th>Noindex</th><th>Canonical</th><th>Klicks</th><th>Impressionen</th><th>Ø Pos.</th><th>Abdeckung</th></tr></thead>
<tbody>{''.join(page_html)}</tbody>
</table>

<h2>URL-Monitor</h2>
<p class="muted">Leichte Checks aus der Monitor-Tabelle. Bestätigte Ereignisse benötigen zwei vergleichbare Fehlmessungen; eine erfolgreiche Messung markiert die Wiederherstellung.</p>
<table><thead><tr><th>URL</th><th>Zustand</th><th>Grund</th><th>Letzte Messung</th></tr></thead><tbody>{monitor_html}</tbody></table>

<h2>Änderungsnotizen</h2>
<ul class="changes">{changes_html}</ul>

<h2>Datenqualität</h2>
<ul>
  <li>Laufstatus: <strong>{_e(run.get('status'))}</strong>{' – ' + _e(run.get('stop_reason')) if run.get('stop_reason') else ''}</li>
  <li>GSC-Segmente: {len(data.datasets)} Datensätze; Seitenmetriken: {len(latest_page_rows(data))}</li>
  <li>Befunde mit Ausnahme: {sum(1 for result in report.results if result.exception is not None)}</li>
  <li>Offene Maßnahmen mit Status „erledigt/ignoriert“ werden hier ausgeblendet.</li>
</ul>

<footer>Offline erzeugt von SeoBoy. Rohbefunde: <a href="02_TECHNICAL_SEO_AUDIT.md">technischer Audit</a> · <a href="01_ACTION_PLAN_PRIORITIZED.md">Maßnahmenplan</a>. Keine externen Assets, keine Website-Änderung.</footer>
</main>
<script>
(function () {{
  var type = document.getElementById('type');
  var status = document.getElementById('status');
  function apply() {{
    var rows = document.querySelectorAll('#pages tbody tr');
    rows.forEach(function (row) {{
      var okType = !type.value || row.dataset.type === type.value;
      var okStatus = !status.value || row.dataset.status === status.value;
      row.style.display = okType && okStatus ? '' : 'none';
    }});
  }}
  type.addEventListener('change', apply);
  status.addEventListener('change', apply);
}})();
</script>
</body></html>
"""
    path = folder / "PROJECT_OVERVIEW.html"
    path.write_text(html_text, encoding="utf-8", newline="\n")
    return path
