#!/usr/bin/env python3
"""
Culinara AI Agent Dashboard
Calm, editorial-style interface to run and review the 3-agent team.
Run: python3 dashboard.py  →  http://localhost:3102
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime, date
from pathlib import Path

from flask import Blueprint, Flask, jsonify, render_template_string, request, Response

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared import (
    load_memory, load_all_data, REPORTS_DIR, MEMORY_DIR, DATA_DIR,
    today_str, day_of_week, is_sunday,
)

app = Flask(__name__)

run_status = {
    "running": False,
    "last_run": None,
    "last_error": None,
    "progress": "",
    "log": [],
    "completed": [],
}

# ── HTML ─────────────────────────────────────────────────────────────────────

DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Culinara — Agent Intelligence</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=Playfair+Display:ital,wght@0,400;0,600;1,400&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #FAFAF8;
    --surface: #FFFFFF;
    --border: #E8E6E1;
    --text: #1A1A1A;
    --text-secondary: #6B6560;
    --text-muted: #9B958F;
    --accent: #C45E3E;
    --accent-soft: rgba(196,94,62,0.08);
    --green: #3D8B5F;
    --green-soft: rgba(61,139,95,0.08);
    --amber: #B8860B;
    --amber-soft: rgba(184,134,11,0.08);
    --serif: 'Playfair Display', Georgia, serif;
    --sans: 'Inter', -apple-system, system-ui, sans-serif;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: var(--sans);
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
  }

  /* ── Navigation ── */
  nav {
    padding: 28px 0;
    border-bottom: 1px solid var(--border);
    margin-bottom: 60px;
  }
  .nav-inner {
    max-width: 900px;
    margin: 0 auto;
    padding: 0 32px;
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }
  .logo {
    font-family: var(--serif);
    font-size: 22px;
    font-weight: 400;
    letter-spacing: -0.02em;
    color: var(--text);
  }
  .logo span { font-weight: 600; }
  .nav-links {
    display: flex;
    gap: 28px;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--text-secondary);
  }
  .nav-links a {
    color: inherit;
    text-decoration: none;
    transition: color 0.2s;
    cursor: pointer;
  }
  .nav-links a:hover { color: var(--text); }
  .nav-links a.active { color: var(--accent); }

  /* ── Container ── */
  .container {
    max-width: 900px;
    margin: 0 auto;
    padding: 0 32px 80px;
  }

  /* ── Hero / Status ── */
  .hero {
    text-align: center;
    margin-bottom: 64px;
  }
  .hero h1 {
    font-family: var(--serif);
    font-size: 38px;
    font-weight: 400;
    letter-spacing: -0.02em;
    margin-bottom: 12px;
    color: var(--text);
  }
  .hero h1 em {
    font-style: italic;
    color: var(--accent);
  }
  .hero .subtitle {
    font-size: 14px;
    color: var(--text-muted);
    font-weight: 400;
    letter-spacing: 0.02em;
  }

  /* ── Run Button ── */
  .run-section {
    display: flex;
    flex-direction: column;
    align-items: center;
    margin-bottom: 64px;
    gap: 16px;
  }
  .run-btn {
    font-family: var(--sans);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--text);
    background: transparent;
    border: 1.5px solid var(--text);
    padding: 14px 48px;
    cursor: pointer;
    transition: all 0.3s ease;
  }
  .run-btn:hover {
    background: var(--text);
    color: var(--bg);
  }
  .run-btn:disabled {
    opacity: 0.3;
    cursor: wait;
  }
  .run-btn.running {
    border-color: var(--accent);
    color: var(--accent);
    animation: breathe 2s ease-in-out infinite;
  }
  @keyframes breathe {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
  }
  .progress-text {
    font-size: 12px;
    color: var(--text-muted);
    min-height: 18px;
  }

  /* ── Agent Status Row ── */
  .agents {
    display: flex;
    justify-content: center;
    gap: 48px;
    margin-bottom: 64px;
    padding: 32px 0;
    border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
  }
  .agent {
    text-align: center;
  }
  .agent-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--border);
    margin: 0 auto 10px;
    transition: background 0.4s ease;
  }
  .agent-dot.active { background: var(--amber); animation: breathe 1.5s infinite; }
  .agent-dot.done { background: var(--green); animation: none; }
  .agent-name {
    font-family: var(--serif);
    font-size: 18px;
    font-weight: 400;
    margin-bottom: 3px;
  }
  .agent-role {
    font-size: 11px;
    color: var(--text-muted);
    letter-spacing: 0.06em;
  }

  /* ── Section Headers ── */
  .section-header {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--text-muted);
    margin-bottom: 24px;
  }

  /* ── Stats Row ── */
  .stats {
    display: flex;
    gap: 1px;
    background: var(--border);
    border: 1px solid var(--border);
    margin-bottom: 64px;
  }
  .stat {
    flex: 1;
    background: var(--surface);
    padding: 24px;
    text-align: center;
  }
  .stat-value {
    font-family: var(--serif);
    font-size: 28px;
    font-weight: 400;
    margin-bottom: 4px;
  }
  .stat-label {
    font-size: 10px;
    color: var(--text-muted);
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }

  /* ── Reports ── */
  .reports-list {
    margin-bottom: 64px;
  }
  .report-item {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding: 18px 0;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    transition: padding-left 0.2s ease;
  }
  .report-item:first-child { border-top: 1px solid var(--border); }
  .report-item:hover {
    padding-left: 8px;
  }
  .report-item .name {
    font-size: 15px;
    font-weight: 500;
  }
  .report-item .date {
    font-size: 12px;
    color: var(--text-muted);
  }

  /* ── Report Viewer ── */
  .report-overlay {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(26,26,26,0.15);
    backdrop-filter: blur(4px);
    z-index: 100;
    justify-content: center;
    align-items: flex-start;
    padding: 48px 24px;
    overflow-y: auto;
  }
  .report-overlay.open { display: flex; }
  .report-panel {
    background: var(--surface);
    max-width: 720px;
    width: 100%;
    padding: 48px;
    border: 1px solid var(--border);
    position: relative;
  }
  .report-panel .close {
    position: absolute;
    top: 20px;
    right: 24px;
    font-size: 12px;
    color: var(--text-muted);
    cursor: pointer;
    font-family: var(--sans);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    border: none;
    background: none;
  }
  .report-panel .close:hover { color: var(--text); }
  .report-panel h2 {
    font-family: var(--serif);
    font-size: 24px;
    font-weight: 400;
    margin-bottom: 28px;
  }
  .report-body {
    font-size: 14px;
    line-height: 1.8;
    color: var(--text-secondary);
    white-space: pre-wrap;
  }
  .report-body h1 {
    font-family: var(--serif);
    font-size: 22px;
    font-weight: 400;
    color: var(--text);
    margin: 28px 0 12px;
  }
  .report-body h2 {
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--text);
    margin: 24px 0 8px;
  }
  .report-body h3 {
    font-size: 14px;
    font-weight: 600;
    color: var(--accent);
    margin: 16px 0 6px;
  }
  .report-body strong { color: var(--text); }

  /* ── Knowledge Base ── */
  .knowledge {
    margin-bottom: 64px;
  }
  .kb-columns {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 24px;
  }
  .kb-col h3 {
    font-size: 13px;
    font-weight: 500;
    margin-bottom: 4px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .kb-col .count {
    font-size: 11px;
    color: var(--accent);
    font-weight: 600;
  }
  .kb-col .tier {
    font-size: 10px;
    color: var(--text-muted);
    letter-spacing: 0.04em;
    margin-bottom: 16px;
  }
  .kb-entry {
    font-size: 12.5px;
    color: var(--text-secondary);
    line-height: 1.6;
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
  }
  .kb-entry:last-child { border: none; }

  /* ── Log ── */
  .log-section { margin-bottom: 64px; }
  .log-area {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 11px;
    line-height: 1.8;
    color: var(--text-muted);
    max-height: 180px;
    overflow-y: auto;
    padding: 16px 0;
    border-top: 1px solid var(--border);
  }
  .log-area .success { color: var(--green); }
  .log-area .error { color: var(--accent); }
  .log-area .agent { color: var(--text); }

  /* ── Footer ── */
  footer {
    text-align: center;
    padding: 32px 0;
    border-top: 1px solid var(--border);
    font-size: 11px;
    color: var(--text-muted);
    letter-spacing: 0.06em;
  }
</style>
</head>
<body>

<nav>
  <div class="nav-inner">
    <div class="logo"><span>Culinara</span></div>
    <div class="nav-links">
      <a class="active" onclick="scrollTo(0,0)">Agents</a>
      <a onclick="document.getElementById('reports-section').scrollIntoView({behavior:'smooth'})">Reports</a>
      <a onclick="document.getElementById('knowledge-section').scrollIntoView({behavior:'smooth'})">Knowledge</a>
    </div>
  </div>
</nav>

<div class="container">

  <!-- Hero -->
  <div class="hero">
    <h1>Your <em>intelligence</em> team</h1>
    <div class="subtitle">Three AI agents analyzing Bott&#275; every day, learning every run.</div>
  </div>

  <!-- Run -->
  <div class="run-section">
    <button class="run-btn" id="runBtn" onclick="runAgents()">Run Analysis</button>
    <div class="progress-text" id="progressText"></div>
  </div>

  <!-- Agent Status -->
  <div class="agents">
    <div class="agent">
      <div class="agent-dot" id="dot-jon_snow"></div>
      <div class="agent-name">Jon Snow</div>
      <div class="agent-role">Money & Margins</div>
    </div>
    <div class="agent">
      <div class="agent-dot" id="dot-miles_teller"></div>
      <div class="agent-name">Miles Teller</div>
      <div class="agent-role">Operations & Kitchen</div>
    </div>
    <div class="agent">
      <div class="agent-dot" id="dot-mac_miller"></div>
      <div class="agent-name">Mac Miller</div>
      <div class="agent-role">Intelligence & Vision</div>
    </div>
  </div>

  <!-- Stats -->
  <div class="stats">
    <div class="stat">
      <div class="stat-value" id="totalRuns">&mdash;</div>
      <div class="stat-label">Runs</div>
    </div>
    <div class="stat">
      <div class="stat-value" style="color:var(--green);" id="totalCost">&mdash;</div>
      <div class="stat-label">API Cost</div>
    </div>
    <div class="stat">
      <div class="stat-value" id="kbEntries">&mdash;</div>
      <div class="stat-label">Learnings</div>
    </div>
    <div class="stat">
      <div class="stat-value" style="font-size:16px;" id="lastRunTime">&mdash;</div>
      <div class="stat-label">Last Run</div>
    </div>
  </div>

  <!-- Reports -->
  <div class="reports-list" id="reports-section">
    <div class="section-header">Reports</div>
    <div id="reportsGrid">
      <div class="report-item" style="opacity:0.4;cursor:default;">
        <span class="name">No reports yet</span>
        <span class="date">Run the agents to get started</span>
      </div>
    </div>
  </div>

  <!-- Knowledge Base -->
  <div class="knowledge" id="knowledge-section">
    <div class="section-header">Knowledge Base</div>
    <div class="kb-columns">
      <div class="kb-col">
        <h3>Hypotheses <span class="count" id="kbHypCount">0</span></h3>
        <div class="tier">Early observations</div>
        <div id="kbHypotheses"><div class="kb-entry" style="color:var(--text-muted);font-style:italic;">Waiting for first run</div></div>
      </div>
      <div class="kb-col">
        <h3>Patterns <span class="count" id="kbPatCount">0</span></h3>
        <div class="tier">Confirmed 3+ times</div>
        <div id="kbPatterns"><div class="kb-entry" style="color:var(--text-muted);font-style:italic;">Promoted from hypotheses</div></div>
      </div>
      <div class="kb-col">
        <h3>Rules <span class="count" id="kbRuleCount">0</span></h3>
        <div class="tier">Validated 2+ weeks</div>
        <div id="kbRules"><div class="kb-entry" style="color:var(--text-muted);font-style:italic;">Graduated from patterns</div></div>
      </div>
    </div>
  </div>

  <!-- Log -->
  <div class="log-section">
    <div class="section-header">Activity</div>
    <div class="log-area" id="logBox">
      <div>Waiting for first run...</div>
    </div>
  </div>

</div>

<!-- Report Overlay -->
<div class="report-overlay" id="reportOverlay" onclick="if(event.target===this)closeReport()">
  <div class="report-panel">
    <button class="close" onclick="closeReport()">Close</button>
    <h2 id="reportTitle"></h2>
    <div class="report-body" id="reportContent"></div>
  </div>
</div>

<footer>Culinara Intelligence &middot; Bott&#275; Restaurant</footer>

<script>
let polling = null;

async function runAgents() {
  const btn = document.getElementById('runBtn');
  btn.disabled = true;
  btn.className = 'run-btn running';
  btn.textContent = 'Analyzing...';

  try {
    const res = await fetch('api/run', { method: 'POST' });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    polling = setInterval(pollStatus, 1500);
  } catch(e) {
    btn.disabled = false;
    btn.className = 'run-btn';
    btn.textContent = 'Run Analysis';
    document.getElementById('progressText').textContent = e.message;
  }
}

async function pollStatus() {
  try {
    const res = await fetch('api/status');
    const data = await res.json();
    document.getElementById('progressText').textContent = data.progress || '';

    ['jon_snow','miles_teller','mac_miller'].forEach(a => {
      const dot = document.getElementById('dot-' + a);
      const shortName = a.split('_')[0]; // jon, miles, mac
      if (data.progress && data.progress.toLowerCase().includes(shortName)) {
        dot.className = 'agent-dot active';
      } else if (data.completed && data.completed.includes(a)) {
        dot.className = 'agent-dot done';
      }
    });

    if (data.log && data.log.length) {
      const logBox = document.getElementById('logBox');
      logBox.innerHTML = data.log.map(l => {
        const cls = l.includes('ERROR') ? 'error' : l.includes('saved') ? 'success' : l.includes('Running') ? 'agent' : '';
        return '<div class="' + cls + '">' + l + '</div>';
      }).join('');
      logBox.scrollTop = logBox.scrollHeight;
    }

    if (!data.running) {
      clearInterval(polling);
      const btn = document.getElementById('runBtn');
      btn.disabled = false;
      btn.className = 'run-btn';
      btn.textContent = 'Run Analysis';

      ['jon_snow','miles_teller','mac_miller'].forEach(a => {
        document.getElementById('dot-' + a).className = 'agent-dot';
      });

      loadReports();
      loadKnowledgeBase();
      loadStats();

      if (data.last_error) {
        document.getElementById('progressText').textContent = data.last_error;
      }
    }
  } catch(e) { console.error(e); }
}

async function loadReports() {
  try {
    const res = await fetch('api/reports');
    const data = await res.json();
    const grid = document.getElementById('reportsGrid');
    if (!data.reports || !data.reports.length) return;

    grid.innerHTML = data.reports.map(r =>
      `<div class="report-item" onclick="viewReport('${r.path}', '${r.name}')">
        <span class="name">${r.name}</span>
        <span class="date">${r.date}</span>
      </div>`
    ).join('');
  } catch(e) { console.error(e); }
}

async function viewReport(path, name) {
  try {
    const res = await fetch('api/report?path=' + encodeURIComponent(path));
    const data = await res.json();
    document.getElementById('reportTitle').textContent = name;
    let html = data.content
      .replace(/^### (.*$)/gm, '<h3>$1</h3>')
      .replace(/^## (.*$)/gm, '<h2>$1</h2>')
      .replace(/^# (.*$)/gm, '<h1>$1</h1>')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/^- \[ \]/gm, '&#9744;')
      .replace(/^- /gm, '&bull; ')
      .replace(/\n\n/g, '<br><br>');
    document.getElementById('reportContent').innerHTML = html;
    document.getElementById('reportOverlay').classList.add('open');
  } catch(e) { console.error(e); }
}

function closeReport() {
  document.getElementById('reportOverlay').classList.remove('open');
}

async function loadKnowledgeBase() {
  try {
    const res = await fetch('api/knowledge');
    const data = await res.json();
    document.getElementById('kbHypCount').textContent = data.hypotheses ? data.hypotheses.length : 0;
    document.getElementById('kbPatCount').textContent = data.patterns ? data.patterns.length : 0;
    document.getElementById('kbRuleCount').textContent = data.rules ? data.rules.length : 0;

    if (data.hypotheses && data.hypotheses.length) {
      document.getElementById('kbHypotheses').innerHTML = data.hypotheses.slice(-5).map(h =>
        '<div class="kb-entry">' + (h.finding || JSON.stringify(h)) + '</div>'
      ).join('');
    }
    if (data.patterns && data.patterns.length) {
      document.getElementById('kbPatterns').innerHTML = data.patterns.slice(-5).map(p =>
        '<div class="kb-entry">' + (p.finding || JSON.stringify(p)) + '</div>'
      ).join('');
    }
    if (data.rules && data.rules.length) {
      document.getElementById('kbRules').innerHTML = data.rules.slice(-5).map(r =>
        '<div class="kb-entry">' + (r.finding || JSON.stringify(r)) + '</div>'
      ).join('');
    }
  } catch(e) { console.error(e); }
}

async function loadStats() {
  try {
    const res = await fetch('api/stats');
    const data = await res.json();
    document.getElementById('totalRuns').textContent = data.total_runs || '0';
    document.getElementById('totalCost').textContent = '$' + (data.total_cost || 0).toFixed(2);
    document.getElementById('kbEntries').textContent = data.kb_entries || '0';
    const lr = data.last_run;
    document.getElementById('lastRunTime').textContent = lr && lr !== 'Never'
      ? new Date(lr).toLocaleDateString('en-US', {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'})
      : 'Never';
  } catch(e) { console.error(e); }
}

loadReports();
loadKnowledgeBase();
loadStats();
</script>
</body>
</html>
"""


# ── API Routes ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/run", methods=["POST"])
def api_run():
    if run_status["running"]:
        return jsonify({"error": "Already running"}), 409

    run_status["running"] = True
    run_status["last_error"] = None
    run_status["progress"] = "Starting..."
    run_status["log"] = []
    run_status["completed"] = []

    def run_in_bg():
        try:
            import jon_snow
            import miles_teller
            import mac_miller
            from shared import get_client, estimate_cost, append_to_log, save_memory, now_str

            client = get_client()

            run_status["progress"] = "Running Jon Snow..."
            run_status["log"].append(f"[{now_str()}] Starting Jon Snow — Money & Margins")
            snow_result = jon_snow.run(client=client)
            run_status["log"].append(f"[{now_str()}] Jon Snow report saved — ${snow_result['cost']:.4f}")
            run_status["completed"] = ["jon_snow"]

            run_status["progress"] = "Running Miles Teller..."
            run_status["log"].append(f"[{now_str()}] Starting Miles Teller — Operations & Kitchen")
            teller_result = miles_teller.run(client=client, margin_report=snow_result["report"])
            run_status["log"].append(f"[{now_str()}] Miles Teller report saved — ${teller_result['cost']:.4f}")
            run_status["completed"] = ["jon_snow", "miles_teller"]

            run_status["progress"] = "Running Mac Miller..."
            run_status["log"].append(f"[{now_str()}] Starting Mac Miller — Intelligence & Vision")
            miller_result = mac_miller.run(
                client=client,
                margin_report=snow_result["report"],
                prep_report=teller_result["report"],
            )
            run_status["log"].append(f"[{now_str()}] Mac Miller briefing saved — ${miller_result['cost']:.4f}")
            run_status["completed"] = ["jon_snow", "miles_teller", "mac_miller"]

            total_cost = snow_result["cost"] + teller_result["cost"] + miller_result["cost"]
            run_status["log"].append(f"[{now_str()}] Complete — ${total_cost:.4f}")
            run_status["progress"] = f"Complete — ${total_cost:.4f}"
            run_status["last_run"] = now_str()

            cost_tracker = load_memory("cost_tracker.json")
            if not isinstance(cost_tracker, dict):
                cost_tracker = {"total_cost": 0, "total_runs": 0, "runs": []}
            cost_tracker["total_cost"] = round(cost_tracker.get("total_cost", 0) + total_cost, 6)
            cost_tracker["total_runs"] = cost_tracker.get("total_runs", 0) + 1
            cost_tracker["last_run"] = now_str()
            if "runs" not in cost_tracker:
                cost_tracker["runs"] = []
            cost_tracker["runs"].append({"date": now_str(), "cost": round(total_cost, 6)})
            save_memory("cost_tracker.json", cost_tracker)

        except Exception as e:
            run_status["last_error"] = str(e)
            run_status["log"].append(f"ERROR: {str(e)}")
            run_status["progress"] = f"Error: {str(e)[:80]}"
            traceback.print_exc()
        finally:
            run_status["running"] = False

    threading.Thread(target=run_in_bg, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/status")
def api_status():
    return jsonify({
        "running": run_status["running"],
        "progress": run_status["progress"],
        "last_run": run_status.get("last_run"),
        "last_error": run_status.get("last_error"),
        "log": run_status["log"][-20:],
        "completed": run_status.get("completed", []),
    })


@app.route("/api/reports")
def api_reports():
    reports = []
    if REPORTS_DIR.exists():
        for day_dir in sorted(REPORTS_DIR.iterdir(), reverse=True):
            if day_dir.is_dir():
                for f in sorted(day_dir.iterdir()):
                    if f.suffix == ".md":
                        reports.append({
                            "name": f.stem.replace("_", " ").title(),
                            "date": day_dir.name,
                            "path": str(f),
                        })
    return jsonify({"reports": reports[:15]})


@app.route("/api/report")
def api_report():
    path = request.args.get("path", "")
    if not path or not Path(path).exists():
        return jsonify({"error": "Not found"}), 404
    if not str(Path(path).resolve()).startswith(str(REPORTS_DIR.resolve())):
        return jsonify({"error": "Access denied"}), 403
    with open(path, "r") as f:
        content = f.read()
    return jsonify({"content": content})


@app.route("/api/knowledge")
def api_knowledge():
    kb = load_memory("knowledge_base.json")
    if not isinstance(kb, dict):
        kb = {}
    return jsonify({
        "hypotheses": kb.get("hypotheses", []),
        "patterns": kb.get("patterns", []),
        "rules": kb.get("rules", []),
    })


@app.route("/api/stats")
def api_stats():
    cost_tracker = load_memory("cost_tracker.json")
    kb = load_memory("knowledge_base.json")
    if not isinstance(cost_tracker, dict):
        cost_tracker = {}
    if not isinstance(kb, dict):
        kb = {}
    kb_total = (
        len(kb.get("hypotheses", []))
        + len(kb.get("patterns", []))
        + len(kb.get("rules", []))
    )
    return jsonify({
        "total_runs": cost_tracker.get("total_runs", 0),
        "total_cost": cost_tracker.get("total_cost", 0),
        "kb_entries": kb_total,
        "last_run": cost_tracker.get("last_run", "Never"),
    })


def create_dashboard_blueprint():
    """Create a Blueprint for mounting the dashboard under /agents/ in the main app."""
    bp = Blueprint("agents_bp", __name__)

    @bp.route("/")
    def bp_index():
        return render_template_string(DASHBOARD_HTML)

    @bp.route("/api/run", methods=["POST"])
    def bp_run():
        return api_run()

    @bp.route("/api/status")
    def bp_status():
        return api_status()

    @bp.route("/api/reports")
    def bp_reports():
        return api_reports()

    @bp.route("/api/report")
    def bp_report():
        return api_report()

    @bp.route("/api/knowledge")
    def bp_knowledge():
        return api_knowledge()

    @bp.route("/api/stats")
    def bp_stats():
        return api_stats()

    return bp


if __name__ == "__main__":
    print()
    print("  Culinara Intelligence")
    print("  http://localhost:3102")
    print()
    app.run(host="0.0.0.0", port=3102, debug=False)
