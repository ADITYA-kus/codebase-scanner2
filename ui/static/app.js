(function () {
  const metaEl = document.getElementById("meta");
  const repoNameEl = document.getElementById("repo-name");
  const repoSelectEl = document.getElementById("repo-select");
  const addRepoBtnEl = document.getElementById("add-repo-btn");
  const treeStatusEl = document.getElementById("tree-status");
  const treeEl = document.getElementById("tree");
  const fileViewEl = document.getElementById("file-view");
  const symbolViewEl = document.getElementById("symbol-view");
  const searchInputEl = document.getElementById("symbol-search-input");
  const searchResultsEl = document.getElementById("symbol-search-results");
  const tabDetailsEl = document.getElementById("tab-details");
  const tabImpactEl = document.getElementById("tab-impact");
  const tabGraphEl = document.getElementById("tab-graph");
  const tabArchitectureEl = document.getElementById("tab-architecture");
  const graphControlsEl = document.getElementById("graph-controls");
  const impactControlsEl = document.getElementById("impact-controls");
  const impactDepthEl = document.getElementById("impact-depth");
  const impactMaxNodesEl = document.getElementById("impact-max-nodes");
  const impactViewEl = document.getElementById("impact-view");
  const graphViewEl = document.getElementById("graph-view");
  const architectureViewEl = document.getElementById("architecture-view");
  const graphModeEl = document.getElementById("graph-mode");
  const graphDepthEl = document.getElementById("graph-depth");
  const graphHideBuiltinsEl = document.getElementById("graph-hide-builtins");
  const graphHideExternalEl = document.getElementById("graph-hide-external");
  const graphSearchEl = document.getElementById("graph-search");
  const recentSymbolsEl = document.getElementById("recent-symbols");
  const recentFilesEl = document.getElementById("recent-files");
  const recentSymbolsWrapEl = document.getElementById("recent-symbols-wrap");
  const recentFilesWrapEl = document.getElementById("recent-files-wrap");
  const repoListContentEl = document.getElementById("repo-list-content");
  const addRepoInlineEl = document.getElementById("add-repo-inline");
  const repoInlineCloseEl = document.getElementById("repo-inline-close");
  const repoTabLocalEl = document.getElementById("repo-tab-local");
  const repoTabGithubEl = document.getElementById("repo-tab-github");
  const repoFormLocalEl = document.getElementById("repo-form-local");
  const repoFormGithubEl = document.getElementById("repo-form-github");
  const localRepoPathEl = document.getElementById("local-repo-path");
  const localDisplayNameEl = document.getElementById("local-display-name");
  const ghRepoUrlEl = document.getElementById("gh-repo-url");
  const ghRefEl = document.getElementById("gh-ref");
  const ghModeEl = document.getElementById("gh-mode");
  const ghTokenEl = document.getElementById("gh-token");
  const privateModeIndicatorEl = document.getElementById("private-mode-indicator");
  const repoOpenAfterAddEl = document.getElementById("repo-open-after-add");
  const repoModalErrorEl = document.getElementById("repo-modal-error");
  const repoAddBtnEl = document.getElementById("repo-add-btn");
  const repoCancelBtnEl = document.getElementById("repo-cancel-btn");
  const toastEl = document.getElementById("toast");
  const privacySummaryEl = document.getElementById("privacy-summary");
  const privacyExpiringEl = document.getElementById("privacy-expiring");
  const privacyResultEl = document.getElementById("privacy-result");
  const policyDefaultTtlEl = document.getElementById("policy-default-ttl");
  const policyWorkspaceTtlEl = document.getElementById("policy-workspace-ttl");
  const policySaveBtnEl = document.getElementById("policy-save-btn");
  const cleanupDryBtnEl = document.getElementById("cleanup-dry-btn");
  const cleanupNowBtnEl = document.getElementById("cleanup-now-btn");
  const deleteRepoCacheBtnEl = document.getElementById("delete-repo-cache-btn");
  const autoCleanOnRemoveEl = document.getElementById("auto-clean-on-remove");

  const fileCache = new Map();
  const symbolCache = new Map();
  let repoDir = "";
  let repoName = "";
  let activeSymbolFqn = "";
  let activeFilePath = "";
  let searchTimer = null;
  let currentSearchResults = [];
  let workspaceRepos = [];
  let activeRepoHash = "";
  let recentSymbols = [];
  let recentFiles = [];
  let lastSymbol = "";
  let activeTab = "details";
  let graphDataCache = new Map();
  let impactDataCache = new Map();
  let architectureCache = null;
  let repoSummary = null;
  let repoSummaryUpdatedAt = "";
  let repoSummaryStatus = "idle"; // idle|loading|ready|missing|error
  let repoSummaryError = "";
  let riskRadar = null;
  let riskRadarUpdatedAt = "";
  let riskRadarStatus = "idle"; // idle|loading|ready|missing|error
  let riskRadarError = "";
  let dataPrivacyCache = null;
  let repoRegistry = [];
  let autoCleanOnRemove = false;

  function withRepo(path) {
    return new URL(path, window.location.origin).toString();
  }

  async function fetchJson(path, options) {
    const res = await fetch(withRepo(path), options);
    const data = await res.json();
    if (!res.ok || data.ok === false) throw data;
    return data;
  }

  function esc(v) {
    return String(v ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
    })[ch]);
  }

  function redactSecrets(v) {
    let value = String(v || "");
    value = value.replace(/\bgh[pousr]_[A-Za-z0-9_]{8,}\b/g, (m) => `${m.slice(0, 4)}************`);
    value = value.replace(/\bBearer\s+[^\s]+/gi, "Bearer ********");
    value = value.replace(/\bBasic\s+[^\s]+/gi, "Basic ********");
    value = value.replace(/(https?:\/\/)([^/\s:@]+):([^@\s/]+)@/gi, "$1***:***@");
    value = value.replace(/\b(token|api[_-]?key|password)\s*[:=]\s*[^\s'"`]+/gi, "$1=[REDACTED]");
    return value;
  }

  function formatBytes(v) {
    const n = Number(v || 0);
    if (!Number.isFinite(n) || n <= 0) return "0 B";
    if (n < 1024) return `${Math.round(n)} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
    return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }

  function stripMarkdown(text) {
    return String(text || "")
      .replace(/```/g, "")
      .replace(/[*#`]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function relPath(p) {
    const path = String(p || "").replace(/\\/g, "/");
    const root = String(repoDir || "").replace(/\\/g, "/");
    if (root && path.toLowerCase().startsWith(root.toLowerCase() + "/")) {
      return path.slice(root.length + 1);
    }
    return path;
  }

  function normalizeTree(raw) {
    if (!raw) return null;
    if (raw.tree) return raw.tree;
    if (raw.name && raw.type) return raw;
    if (Array.isArray(raw)) return { name: "repo", type: "directory", path: "", children: raw };
    if (raw.root) return raw.root;
    return { name: "repo", type: "directory", path: "", children: [] };
  }

  function parseSymbolParts(fqn) {
    const parts = String(fqn || "").split(".");
    const symbol = parts[parts.length - 1] || "";
    const prev = parts[parts.length - 2] || "";
    const className = prev && prev[0] === prev[0].toUpperCase() ? prev : "";
    const display = className ? `${className}.${symbol}` : symbol;
    return { className, symbol, display };
  }

  function currentRepoEntry() {
    return (repoRegistry || []).find((r) => String(r.repo_hash) === String(activeRepoHash)) || null;
  }

  function analyzeCommandForRepo(repo) {
    const r = repo || currentRepoEntry();
    if (!r) return "python cli.py api analyze --path <repo>";
    if (String(r.source || "filesystem") === "github" && r.repo_url) {
      const ref = r.ref || "main";
      const mode = r.mode || "zip";
      return `python cli.py api analyze --github ${r.repo_url} --ref ${ref} --mode ${mode}`;
    }
    return `python cli.py api analyze --path ${r.repo_path || "<repo>"}`;
  }

  function renderMissingAnalysisCta(msg) {
    const cmd = analyzeCommandForRepo();
    return `
      <div class="missing-analysis-cta">
        <div class="symbol-name">Analysis not found</div>
        <div>No analysis data found for this repo. Click "Run Analysis Now" or run:</div>
        <div class="impact-command">${esc(cmd)}</div>
        <div class="repo-row-actions">
          <button id="run-analysis-now-btn" class="repo-btn small" type="button">Run Analysis Now</button>
        </div>
        <div class="path">${esc(msg || "After it finishes, refresh this page.")}</div>
      </div>
    `;
  }

  function clearWorkspaceView(message) {
    fileCache.clear();
    symbolCache.clear();
    activeFilePath = "";
    activeSymbolFqn = "";
    closeSearchDropdown();
    treeEl.innerHTML = "";
    treeStatusEl.textContent = "";
    fileViewEl.classList.add("muted");
    symbolViewEl.classList.add("muted");
    impactViewEl.classList.add("muted");
    graphViewEl.classList.add("muted");
    architectureViewEl.classList.add("muted");
    fileViewEl.textContent = message || "Select a file from the tree.";
    symbolViewEl.textContent = "Select a symbol to view summary and usages.";
    impactViewEl.textContent = "Select a symbol to view impact.";
    graphViewEl.textContent = "Select a symbol to view graph.";
    architectureViewEl.textContent = "Select a repository to view architecture insights.";
    recentSymbols = [];
    recentFiles = [];
    lastSymbol = "";
    architectureCache = null;
    repoSummary = null;
    repoSummaryUpdatedAt = "";
    repoSummaryStatus = "idle";
    repoSummaryError = "";
    riskRadar = null;
    riskRadarUpdatedAt = "";
    riskRadarStatus = "idle";
    riskRadarError = "";
    renderRecents();
  }

  function bindRunAnalysisNowButton() {
    const btn = document.getElementById("run-analysis-now-btn");
    if (!btn) return;
    btn.addEventListener("click", async () => {
      if (!activeRepoHash) return;
      await analyzeRepoByHash(activeRepoHash);
    });
  }

  function showMissingAnalysisState(message) {
    const cta = renderMissingAnalysisCta(message);
    fileViewEl.classList.remove("muted");
    symbolViewEl.classList.remove("muted");
    impactViewEl.classList.remove("muted");
    graphViewEl.classList.remove("muted");
    fileViewEl.innerHTML = cta;
    symbolViewEl.innerHTML = cta;
    impactViewEl.innerHTML = cta;
    graphViewEl.innerHTML = cta;
    bindRunAnalysisNowButton();
  }

  function graphParams() {
    return {
      mode: String(graphModeEl && graphModeEl.value ? graphModeEl.value : "symbol"),
      depth: Number(graphDepthEl && graphDepthEl.value ? graphDepthEl.value : 1),
      hideBuiltins: !!(graphHideBuiltinsEl && graphHideBuiltinsEl.checked),
      hideExternal: !!(graphHideExternalEl && graphHideExternalEl.checked),
      search: String(graphSearchEl && graphSearchEl.value ? graphSearchEl.value : "").trim().toLowerCase(),
    };
  }

  function setActiveTab(tab) {
    activeTab = tab === "graph" || tab === "architecture" || tab === "impact" ? tab : "details";
    const isImpact = activeTab === "impact";
    const isGraph = activeTab === "graph";
    const isArchitecture = activeTab === "architecture";
    if (tabDetailsEl) tabDetailsEl.classList.toggle("active", activeTab === "details");
    if (tabImpactEl) tabImpactEl.classList.toggle("active", isImpact);
    if (tabGraphEl) tabGraphEl.classList.toggle("active", isGraph);
    if (tabArchitectureEl) tabArchitectureEl.classList.toggle("active", isArchitecture);
    if (symbolViewEl) symbolViewEl.classList.toggle("hidden", activeTab !== "details");
    if (impactViewEl) impactViewEl.classList.toggle("hidden", !isImpact);
    if (graphViewEl) graphViewEl.classList.toggle("hidden", !isGraph);
    if (architectureViewEl) architectureViewEl.classList.toggle("hidden", !isArchitecture);
    if (graphControlsEl) graphControlsEl.classList.toggle("hidden", !isGraph);
    if (impactControlsEl) impactControlsEl.classList.toggle("hidden", !isImpact);
    if (isGraph) {
      loadGraph();
    }
    if (isImpact) {
      loadImpact();
    }
    if (isArchitecture) {
      loadArchitecture();
    }
  }

  function shortLabel(fqn) {
    const parts = String(fqn || "").split(".");
    if (parts.length >= 2) return `${parts[parts.length - 2]}.${parts[parts.length - 1]}`;
    return parts[parts.length - 1] || fqn;
  }

  function basename(path) {
    return String(path || "").replace(/\\/g, "/").split("/").pop() || "";
  }

  function renderSymbolList(rows, symbolsMap, emptyText) {
    if (!rows.length) return `<div class="muted">${esc(emptyText)}</div>`;
    return rows.slice(0, 25).map((entry) => {
      const fqn = typeof entry === "string" ? entry : entry.fqn;
      const info = symbolsMap[fqn] || {};
      const location = info.location || {};
      return `<button class="arch-row" data-fqn="${esc(fqn)}">
        <span class="arch-name">${esc(shortLabel(fqn))}</span>
        <span class="path">in:${esc(info.fan_in ?? 0)} out:${esc(info.fan_out ?? 0)} ${esc(basename(location.file || ""))}</span>
      </button>`;
    }).join("");
  }

  function repoSummarySection() {
    const cmd = `python cli.py api repo_summary --repo ${repoName || "<repo>"}`;
    const refreshBtn = "<button id='repo-summary-refresh' class='repo-refresh-btn' type='button'>Refresh summary</button>";
    if (repoSummaryStatus === "loading") {
      return `<div class="card"><div class="section-title">Repo Summary</div>${refreshBtn}<div class="path">Loading summary...</div></div>`;
    }
    if (repoSummaryStatus === "missing") {
      return `<div class="card arch-missing"><div class="section-title">Repo Summary</div>${refreshBtn}<div>Repo summary not generated yet.</div><div class="path">${esc(cmd)}</div></div>`;
    }
    if (repoSummaryStatus === "error") {
      return `<div class="card arch-missing"><div class="section-title">Repo Summary</div>${refreshBtn}<div>${esc(repoSummaryError || "Failed to load repo summary.")}</div><div class="path">Run analyze, then: ${esc(cmd)}</div></div>`;
    }
    if (repoSummaryStatus !== "ready" || !repoSummary) {
      return `<div class="card"><div class="section-title">Repo Summary</div>${refreshBtn}<div class="path">Summary is idle. Click refresh.</div></div>`;
    }

    const payload = repoSummary || {};
    const summary = payload.summary || {};
    const bullets = Array.isArray(summary.bullets) ? summary.bullets.slice(0, 7) : [];
    const notes = Array.isArray(summary.notes) ? summary.notes.slice(0, 5) : [];
    return `
      <div class="card">
        <div class="section-title">Repo Summary</div>
        ${refreshBtn}
        <div class="arch-one-liner">${esc(summary.one_liner || "")}</div>
        ${bullets.length ? `<ul class="arch-bullets">${bullets.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : "<div class='muted'>No bullets available.</div>"}
        ${notes.length ? `<div class="section-title">Notes</div><ul class="arch-bullets">${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
        <div class="path">provider: ${esc(payload.provider || "none")} | cached: ${esc(String(payload.cached))} | updated: ${esc(repoSummaryUpdatedAt || "unknown")}</div>
      </div>
    `;
  }

  async function loadRepoSummary(force) {
    if (!force && repoSummaryStatus === "ready" && repoSummary) return;
    repoSummaryStatus = "loading";
    repoSummaryError = "";
    try {
      const data = await fetchJson("/api/repo_summary");
      repoSummary = data.repo_summary || null;
      repoSummaryUpdatedAt = data.updated_at || "";
      repoSummaryStatus = "ready";
    } catch (e) {
      repoSummary = null;
      repoSummaryUpdatedAt = "";
      if (e && e.error === "MISSING_REPO_SUMMARY") {
        repoSummaryStatus = "missing";
        repoSummaryError = "";
      } else {
        repoSummaryStatus = "error";
        repoSummaryError = redactSecrets((e && (e.message || e.error)) || "Repo summary load failed");
      }
    }
  }

  function riskPillClass(risk) {
    const v = String(risk || "").toLowerCase();
    if (v === "high") return "risk-pill high";
    if (v === "medium") return "risk-pill medium";
    return "risk-pill low";
  }

  function riskRadarSection() {
    const cmd = `python cli.py api risk_radar --repo ${repoName || "<repo>"}`;
    if (riskRadarStatus === "loading") {
      return `<div class="card"><div class="section-title">Risk Radar</div><div class="path">Loading risk radar...</div></div>`;
    }
    if (riskRadarStatus === "missing") {
      return `<div class="card arch-missing"><div class="section-title">Risk Radar</div><div>Risk radar not generated yet.</div><div class="path">${esc(cmd)}</div></div>`;
    }
    if (riskRadarStatus === "error") {
      return `<div class="card arch-missing"><div class="section-title">Risk Radar</div><div>${esc(riskRadarError || "Failed to load risk radar.")}</div><div class="path">Run analyze, then: ${esc(cmd)}</div></div>`;
    }
    if (riskRadarStatus !== "ready" || !riskRadar) {
      return `<div class="card"><div class="section-title">Risk Radar</div><div class="path">No risk data loaded.</div></div>`;
    }

    const payload = riskRadar || {};
    const hotspots = Array.isArray(payload.hotspots) ? payload.hotspots.slice(0, 5) : [];
    const riskyFiles = Array.isArray(payload.risky_files) ? payload.risky_files.slice(0, 5) : [];
    const refactors = Array.isArray(payload.refactor_targets) ? payload.refactor_targets.slice(0, 6) : [];

    const hotspotsHtml = hotspots.length
      ? hotspots.map((h) => `
        <button class="arch-row risk-hotspot-row" data-fqn="${esc(h.fqn)}">
          <span class="arch-name">${esc(shortLabel(h.fqn))}</span>
          <span class="${riskPillClass(h.risk)}">${esc(h.risk)}</span>
          <span class="path">score:${esc(h.score)} in:${esc(h.fan_in)} out:${esc(h.fan_out)}</span>
          ${Array.isArray(h.reasons) && h.reasons.length ? `<span class="path">${esc(h.reasons[0])}</span>` : ""}
        </button>
      `).join("")
      : "<div class='muted'>No hotspots detected.</div>";

    const filesHtml = riskyFiles.length
      ? riskyFiles.map((f) => `
        <div class="risk-file-row">
          <span class="arch-name">${esc(basename(f.file || ""))}</span>
          <span class="${riskPillClass(f.risk)}">${esc(f.risk)}</span>
          <span class="path">score:${esc(f.score)} edges:${esc(f.edges)}</span>
        </div>
      `).join("")
      : "<div class='muted'>No risky files detected.</div>";

    const refactorHtml = refactors.length
      ? refactors.map((r) => `
        <div class="risk-target">
          <div class="arch-name">${esc(r.title || "")}</div>
          <div class="path">${esc(r.why || "")}</div>
          ${(Array.isArray(r.targets) && r.targets.length) ? `<div class="path">targets: ${esc(r.targets.join(", "))}</div>` : ""}
        </div>
      `).join("")
      : "<div class='muted'>No refactor targets suggested.</div>";

    return `
      <div class="card">
        <div class="section-title">Risk Radar</div>
        <div class="path">updated: ${esc(riskRadarUpdatedAt || "unknown")}</div>
        <div class="divider"></div>
        <div class="section-title">Top Hotspots</div>
        ${hotspotsHtml}
        <div class="divider"></div>
        <div class="section-title">Top Risky Files</div>
        ${filesHtml}
        <div class="divider"></div>
        <div class="section-title">Refactor Targets</div>
        ${refactorHtml}
      </div>
    `;
  }

  async function loadRiskRadar(force) {
    if (!force && riskRadarStatus === "ready" && riskRadar) return;
    riskRadarStatus = "loading";
    riskRadarError = "";
    try {
      const data = await fetchJson("/api/risk_radar");
      riskRadar = data.risk_radar || null;
      riskRadarUpdatedAt = data.updated_at || "";
      riskRadarStatus = "ready";
    } catch (e) {
      riskRadar = null;
      riskRadarUpdatedAt = "";
      if (e && e.error === "MISSING_RISK_RADAR") {
        riskRadarStatus = "missing";
        riskRadarError = "";
      } else {
        riskRadarStatus = "error";
        riskRadarError = redactSecrets((e && (e.message || e.error)) || "Risk radar load failed");
      }
    }
  }

  async function loadArchitecture() {
    if (!architectureViewEl) return;
    architectureViewEl.classList.remove("muted");
    architectureViewEl.innerHTML = "<div class='card'>Loading architecture insights...</div>";
    try {
      if (!architectureCache) architectureCache = await fetchJson("/api/architecture");
      await loadRepoSummary(false);
      await loadRiskRadar(false);
      const arch = architectureCache.architecture_metrics || {};
      const dep = architectureCache.dependency_cycles || {};
      const repo = arch.repo || {};
      const symbolsMap = arch.symbols || {};

      const orchestrators = (repo.orchestrators && repo.orchestrators.length ? repo.orchestrators : (repo.top_fan_out || []).map((x) => x.fqn || x)).filter(Boolean);
      const critical = (repo.critical_symbols && repo.critical_symbols.length ? repo.critical_symbols : (repo.top_fan_in || []).map((x) => x.fqn || x)).filter(Boolean);
      const dead = (repo.dead_symbols || []).filter(Boolean);
      const cycles = dep.cycles || [];

      architectureViewEl.innerHTML = `
        ${repoSummarySection()}
        ${riskRadarSection()}
        <div class="arch-grid">
          <div class="kpi-card"><div class="kpi-label">Orchestrators</div><div class="kpi-value">${orchestrators.length}</div></div>
          <div class="kpi-card"><div class="kpi-label">Critical APIs</div><div class="kpi-value">${critical.length}</div></div>
          <div class="kpi-card"><div class="kpi-label">Dead Symbols</div><div class="kpi-value">${dead.length}</div></div>
          <div class="kpi-card"><div class="kpi-label">Dependency Cycles</div><div class="kpi-value">${dep.cycle_count || 0}</div></div>
        </div>
        <div class="card">
          <div class="section-title">Top Orchestrators</div>
          ${renderSymbolList(orchestrators, symbolsMap, "No orchestrators detected.")}
        </div>
        <div class="card">
          <div class="section-title">Top Critical Symbols</div>
          ${renderSymbolList(critical, symbolsMap, "No critical symbols detected.")}
        </div>
        <div class="card">
          <div class="section-title">Dead Symbols</div>
          ${renderSymbolList(dead, symbolsMap, "No dead symbols detected.")}
        </div>
        <div class="card">
          <div class="section-title">Dependency Cycles</div>
          ${dep.cycle_count ? cycles.slice(0, 50).map((c, i) => `<div class="cycle-row"><span>${esc(c.join(" -> "))}</span><button class="copy-cycle" data-cycle="${esc(c.join(" -> "))}">Copy</button></div>`).join("") : "<div class='ok-cycle'>No cycles detected OK</div>"}
        </div>
      `;

      const refreshBtn = architectureViewEl.querySelector("#repo-summary-refresh");
      if (refreshBtn) {
        refreshBtn.addEventListener("click", async () => {
          await loadRepoSummary(true);
          await loadArchitecture();
        });
      }
      architectureViewEl.querySelectorAll(".arch-row").forEach((el) => {
        el.addEventListener("click", async () => {
          const fqn = el.getAttribute("data-fqn");
          if (!fqn) return;
          setActiveTab("details");
          await loadSymbol(fqn);
        });
      });
      architectureViewEl.querySelectorAll(".copy-cycle[data-cycle]").forEach((el) => {
        el.addEventListener("click", async () => {
          const text = el.getAttribute("data-cycle") || "";
          try {
            await navigator.clipboard.writeText(text);
            el.textContent = "Copied";
            window.setTimeout(() => { el.textContent = "Copy"; }, 800);
          } catch (_e) {
            // noop
          }
        });
      });
    } catch (e) {
      architectureViewEl.classList.remove("muted");
      architectureViewEl.innerHTML = `
        <div class="card arch-missing">
          <div class="section-title">Architecture Insights Unavailable</div>
          <div>${esc((e && (e.message || e.error)) || "Missing architecture cache artifacts.")}</div>
          <div class="path">Run: python cli.py api analyze --path &lt;repo&gt;</div>
        </div>
      `;
    }
  }

  function renderGraphData(data) {
    const p = graphParams();
    const nodes = (data.nodes || []).slice();
    const edges = (data.edges || []).slice();
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const center = data.center || activeSymbolFqn;
    const mode = data.mode || "symbol";
    const seedNodes = new Set(data.seed_nodes || []);

    const matches = new Set(
      !p.search
        ? []
        : nodes.filter((n) => n.id.toLowerCase().includes(p.search) || String(n.label || "").toLowerCase().includes(p.search)).map((n) => n.id)
    );

    const incoming = [];
    const outgoing = [];
    const internal = [];
    for (const e of edges) {
      if (mode === "file") {
        const fromSeed = seedNodes.has(e.from);
        const toSeed = seedNodes.has(e.to);
        if (toSeed && !fromSeed) incoming.push(e);
        else if (fromSeed && !toSeed) outgoing.push(e);
        else if (fromSeed && toSeed) internal.push(e);
      } else {
        if (e.to === center) incoming.push(e);
        if (e.from === center) outgoing.push(e);
      }
    }

    function nodePill(nodeId) {
      const n = byId.get(nodeId) || { id: nodeId, label: nodeId, kind: "external", clickable: false };
      const cls = `graph-node kind-${n.kind} ${matches.has(nodeId) ? "graph-match" : ""} ${n.clickable ? "graph-clickable" : ""}`;
      const subtitle = n.subtitle ? `<div class="path">${esc(n.subtitle)}</div>` : "";
      return `<div class="${cls}" data-node-id="${esc(nodeId)}">
        <div>${esc(n.label || nodeId)}</div>
        ${subtitle}
      </div>`;
    }

    graphViewEl.classList.remove("muted");
    graphViewEl.innerHTML = `
      <div class="card graph-card">
        <div class="graph-legend">
          <span class="legend-item"><span class="dot local"></span>Local</span>
          <span class="legend-item"><span class="dot builtin"></span>Builtins</span>
          <span class="legend-item"><span class="dot external"></span>External</span>
        </div>
        <div class="section-title">${mode === "file" ? "Center File" : "Center"}</div>
        ${mode === "file" ? `<div class="path">${esc(center)}</div>` : nodePill(center)}
        ${mode === "file" ? `<div class="path">Seed symbols: ${seedNodes.size}</div>` : ""}
        <div class="divider"></div>
        <div class="section-title">Incoming Callers (${incoming.length})</div>
        ${incoming.length ? incoming.slice(0, 200).map((e) => `<div class="graph-edge-row">${nodePill(e.from)} <span class="edge-arrow">-></span> <span class="path">${esc(e.count)}x</span></div>`).join("") : "<div class='muted'>No incoming callers in current depth/filter.</div>"}
        <div class="divider"></div>
        <div class="section-title">Outgoing Callees (${outgoing.length})</div>
        ${outgoing.length ? outgoing.slice(0, 200).map((e) => `<div class="graph-edge-row">${nodePill(e.to)} <span class="path">${esc(e.count)}x</span></div>`).join("") : "<div class='muted'>No outgoing callees in current depth/filter.</div>"}
        ${mode === "file" ? `<div class="divider"></div><div class="section-title">Internal File Edges (${internal.length})</div>${internal.length ? internal.slice(0, 200).map((e) => `<div class="graph-edge-row">${nodePill(e.from)} <span class="edge-arrow">-></span> ${nodePill(e.to)} <span class="path">${esc(e.count)}x</span></div>`).join("") : "<div class='muted'>No internal edges in current depth/filter.</div>"}` : ""}
        <div class="divider"></div>
        <div class="section-title">Subgraph Stats</div>
        <div class="path">Nodes: ${nodes.length} | Edges: ${edges.length} | Depth: ${data.depth}</div>
      </div>
    `;

    graphViewEl.querySelectorAll(".graph-node.graph-clickable").forEach((el) => {
      el.addEventListener("click", () => {
        const next = el.getAttribute("data-node-id");
        if (next) loadSymbol(next);
      });
    });
  }

  function renderImpactList(nodes, emptyText) {
    if (!nodes || !nodes.length) return `<div class="muted">${esc(emptyText)}</div>`;
    return nodes.slice(0, 200).map((n) => {
      const isLocal = !String(n.fqn || "").startsWith("builtins.") && !String(n.fqn || "").startsWith("external::");
      if (isLocal) {
        return `
          <button class="arch-row impact-node-row" data-fqn="${esc(n.fqn)}">
            <span class="arch-name">${esc(shortLabel(n.fqn))}</span>
            <span class="impact-distance">d${esc(n.distance)}</span>
            <span class="path">in:${esc(n.fan_in)} out:${esc(n.fan_out)} ${esc(n.file ? relPath(n.file) : "")}:${esc(n.line)}</span>
          </button>
        `;
      }
      return `
        <div class="risk-file-row">
          <span class="arch-name">${esc(shortLabel(n.fqn))}</span>
          <span class="impact-distance">d${esc(n.distance)}</span>
          <span class="path">in:${esc(n.fan_in)} out:${esc(n.fan_out)} ${esc(n.file ? relPath(n.file) : "")}:${esc(n.line)}</span>
        </div>
      `;
    }).join("");
  }

  function renderImpactedFiles(items) {
    if (!items || !items.length) return "<div class='muted'>No impacted files.</div>";
    return items.slice(0, 15).map((x) => `
      <div class="impact-file-row">
        <span class="path">${esc(relPath(x.file || ""))}</span>
        <span class="impact-distance">${esc(x.count)}</span>
      </div>
    `).join("");
  }

  async function loadImpact(fqn) {
    if (!impactViewEl) return;
    const anchor = fqn || activeSymbolFqn;
    if (!anchor) {
      impactViewEl.classList.add("muted");
      impactViewEl.textContent = "Select a symbol to view impact.";
      return;
    }
    const depth = Number(impactDepthEl && impactDepthEl.value ? impactDepthEl.value : 2);
    const maxNodes = Number(impactMaxNodesEl && impactMaxNodesEl.value ? impactMaxNodesEl.value : 200);
    const key = `${anchor}|${depth}|${maxNodes}`;
    impactViewEl.classList.remove("muted");
    impactViewEl.innerHTML = "<div class='card'>Loading impact...</div>";
    try {
      let data = impactDataCache.get(key);
      if (!data) {
        data = await fetchJson(`/api/impact?target=${encodeURIComponent(anchor)}&depth=${depth}&max_nodes=${maxNodes}`);
        impactDataCache.set(key, data);
      }
      const up = data.upstream || { nodes: [], truncated: false };
      const down = data.downstream || { nodes: [], truncated: false };
      const files = data.impacted_files || { upstream: [], downstream: [] };
      const truncated = !!(up.truncated || down.truncated);
      const upstreamBadge = up.truncated ? " <span class='impact-section-badge'>TRUNCATED</span>" : "";
      const downstreamBadge = down.truncated ? " <span class='impact-section-badge'>TRUNCATED</span>" : "";

      impactViewEl.innerHTML = `
        <div class="card impact-card">
          <div class="section-title">Impact</div>
          <div class="path">Target: ${esc(anchor)} | depth: ${esc(data.depth)} | max_nodes: ${esc(data.max_nodes)}</div>
          ${truncated ? `<div class='impact-truncated-banner'>Warning: Results truncated (max_nodes=${esc(data.max_nodes)}). Displaying partial results.</div>` : ""}
          <div class="divider"></div>
          <div class="section-title">Upstream${upstreamBadge}</div>
          ${renderImpactList(up.nodes || [], "No upstream dependents in selected depth.")}
          <div class="divider"></div>
          <div class="section-title">Downstream${downstreamBadge}</div>
          ${renderImpactList(down.nodes || [], "No downstream dependencies in selected depth.")}
          <div class="divider"></div>
          <div class="section-title">Impacted Files (Upstream)</div>
          ${renderImpactedFiles(files.upstream || [])}
          <div class="divider"></div>
          <div class="section-title">Impacted Files (Downstream)</div>
          ${renderImpactedFiles(files.downstream || [])}
        </div>
      `;

      impactViewEl.querySelectorAll(".impact-node-row").forEach((el) => {
        el.addEventListener("click", async () => {
          const next = el.getAttribute("data-fqn");
          if (!next) return;
          setActiveTab("details");
          await loadSymbol(next);
        });
      });
    } catch (e) {
      const errCode = String((e && e.error) || "");
      if (errCode === "MISSING_ANALYSIS" || errCode === "CACHE_NOT_FOUND") {
        impactViewEl.classList.remove("muted");
        impactViewEl.innerHTML = `
          <div class="card arch-missing impact-empty-state">
            <div class="impact-empty-title">Analysis not found</div>
            <div>This repository hasn't been analyzed yet. Run analysis first.</div>
            <pre class="impact-command">python cli.py api analyze --path &lt;repo&gt;</pre>
            <div class="path">After it finishes, refresh this page.</div>
          </div>
        `;
        return;
      }
      impactViewEl.classList.add("muted");
      impactViewEl.textContent = redactSecrets((e && (e.error || e.message)) || "Impact unavailable.");
    }
  }

  async function loadGraph(fqn) {
    if (!graphViewEl) return;
    const p = graphParams();
    const graphMode = p.mode === "file" ? "file" : "symbol";
    const anchor = graphMode === "file" ? activeFilePath : (fqn || activeSymbolFqn);
    if (!anchor) {
      graphViewEl.classList.add("muted");
      graphViewEl.textContent = graphMode === "file"
        ? "Select a file to view file graph."
        : "Select a symbol to view graph.";
      return;
    }
    const key = `${graphMode}|${anchor}|${p.depth}|${p.hideBuiltins}|${p.hideExternal}`;
    graphViewEl.classList.remove("muted");
    graphViewEl.innerHTML = "<div class='card'>Loading graph...</div>";
    try {
      let data = graphDataCache.get(key);
      if (!data) {
        const targetParam = graphMode === "file"
          ? `file=${encodeURIComponent(anchor)}`
          : `fqn=${encodeURIComponent(anchor)}`;
        data = await fetchJson(`/api/graph?${targetParam}&depth=${p.depth}&hide_builtins=${p.hideBuiltins ? "true" : "false"}&hide_external=${p.hideExternal ? "true" : "false"}`);
        graphDataCache.set(key, data);
      }
      renderGraphData(data);
    } catch (e) {
      graphViewEl.classList.add("muted");
      graphViewEl.textContent = redactSecrets((e && (e.error || e.message)) || "Graph unavailable.");
    }
  }

  function renderRecentSymbols() {
    if (!recentSymbolsEl || !recentSymbolsWrapEl) return;
    const items = recentSymbols.slice(0, 8);
    if (!items.length) {
      recentSymbolsWrapEl.classList.add("hidden");
      recentSymbolsEl.className = "content muted";
      recentSymbolsEl.textContent = "";
      return;
    }
    recentSymbolsWrapEl.classList.remove("hidden");
    recentSymbolsEl.className = "content";
    recentSymbolsEl.innerHTML = items
      .map((fqn) => {
        const p = parseSymbolParts(fqn);
        return `<div><span class="symbol-link recent-link" data-fqn="${esc(fqn)}">${esc(p.display)}</span> <span class="path">${esc(fqn)}</span></div>`;
      })
      .join("");
    recentSymbolsEl.querySelectorAll(".recent-link").forEach((el) => {
      el.addEventListener("click", () => loadSymbol(el.getAttribute("data-fqn")));
    });
  }

  function renderRecentFiles() {
    if (!recentFilesEl || !recentFilesWrapEl) return;
    const items = recentFiles.slice(0, 8);
    if (!items.length) {
      recentFilesWrapEl.classList.add("hidden");
      recentFilesEl.className = "content muted";
      recentFilesEl.textContent = "";
      return;
    }
    recentFilesWrapEl.classList.remove("hidden");
    recentFilesEl.className = "content";
    recentFilesEl.innerHTML = items
      .map((file) => `<div><span class="symbol-link recent-file-link" data-file="${esc(file)}">${esc(file)}</span></div>`)
      .join("");
    recentFilesEl.querySelectorAll(".recent-file-link").forEach((el) => {
      el.addEventListener("click", () => loadFile(el.getAttribute("data-file")));
    });
  }

  function renderRecents() {
    renderRecentSymbols();
    renderRecentFiles();
  }

  async function loadUiState() {
    try {
      const data = await fetchJson("/api/ui_state");
      const state = data.state || {};
      recentSymbols = Array.isArray(state.recent_symbols) ? state.recent_symbols : [];
      recentFiles = Array.isArray(state.recent_files) ? state.recent_files : [];
      lastSymbol = String(state.last_symbol || "");
      renderRecents();
      return true;
    } catch (_e) {
      recentSymbols = [];
      recentFiles = [];
      lastSymbol = "";
      renderRecents();
      return false;
    }
  }

  async function updateUiState(payload) {
    try {
      await fetchJson("/api/ui_state/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload || {}),
      });
      await loadUiState();
    } catch (_e) {
      // Keep UI responsive even if persistence fails.
    }
  }

  function renderWorkspaceSelect() {
    if (!repoSelectEl) return;
    repoSelectEl.innerHTML = workspaceRepos
      .map((r) => `<option value="${esc(r.repo_hash)}" ${r.repo_hash === activeRepoHash ? "selected" : ""}>${esc(r.name)}</option>`)
      .join("");
  }

  async function loadWorkspace() {
    const ws = await fetchJson("/api/workspace");
    workspaceRepos = ws.repos || [];
    activeRepoHash = ws.active_repo_hash || "";
    renderWorkspaceSelect();
    await loadRepoRegistry();
    await loadDataPrivacy();
  }

  async function selectWorkspace(repoHash) {
    if (!repoHash) return;
    try {
      await fetchJson("/api/workspace/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_hash: repoHash }),
      });
    } catch (_e) {
      const candidate = (repoRegistry || []).find((r) => String(r.repo_hash) === String(repoHash));
      if (candidate && candidate.repo_path) {
        await fetchJson("/api/workspace/add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: candidate.repo_path }),
        });
        await fetchJson("/api/workspace/select", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ repo_hash: repoHash }),
        });
      } else {
        throw _e;
      }
    }
    activeRepoHash = repoHash;
    await refreshForActiveRepo();
  }

  async function addWorkspaceRepo() {
    if (!addRepoInlineEl) return;
    if (addRepoInlineEl.classList.contains("hidden")) {
      openRepoPanel("local");
      return;
    }
    closeRepoPanel(false);
  }

  function repoBadge(repo) {
    if (!repo) return "";
    if (!repo.has_analysis) return `<span class="repo-badge not-analyzed">Not analyzed</span>`;
    const daysLeft = Number(repo && repo.retention ? repo.retention.days_left : NaN);
    if (Number.isFinite(daysLeft) && daysLeft <= 3 && daysLeft >= 0) {
      return `<span class="repo-badge expiring">Expiring in ${Math.ceil(daysLeft)}d</span>`;
    }
    return `<span class="repo-badge analyzed">Analyzed</span>`;
  }

  function sourceLabel(repo) {
    if (!repo) return "filesystem";
    if (String(repo.source || "") === "github") return `github ${repo.mode || "zip"}`;
    return "filesystem";
  }

  function repoPolicyValue(repo) {
    const r = (repo && repo.retention) || {};
    const mode = String(r.mode || "ttl");
    const ttl = Number(r.ttl_days || 30);
    if (mode === "pinned") return "never";
    if (ttl <= 1) return "24h";
    if (ttl <= 7) return "7d";
    return "30d";
  }

  function renderRepoRegistry() {
    if (!repoListContentEl) return;
    const rows = Array.isArray(repoRegistry) ? repoRegistry : [];
    if (!rows.length) {
      repoListContentEl.innerHTML = "<div class='muted'>No repositories known yet.</div>";
      return;
    }
    repoListContentEl.innerHTML = rows.map((r) => `
      <div class="repo-row" data-repo-hash="${esc(r.repo_hash)}">
        <div class="repo-row-header">
          <div class="repo-row-name">${esc(r.name || r.repo_hash)}</div>
          ${repoBadge(r)}
        </div>
        <div class="path">${esc(r.source === "github" ? (r.repo_url || r.repo_path || "") : (r.repo_path || ""))}</div>
        <div class="path">Source: ${esc(sourceLabel(r))}</div>
        <div class="path">Cache size: ${esc(formatBytes(r.size_bytes || 0))} | Last analyzed: ${esc(r.last_updated || "unknown")}</div>
        <div class="path">${esc(r.cache_dir || "")}</div>
        ${r.source === "github" ? `<div class="path">Workspace: ${esc(r.repo_path || "")}</div>` : ""}
        <div class="repo-row-actions">
          <select class="repo-policy-select" data-repo-hash="${esc(r.repo_hash)}">
            <option value="never" ${repoPolicyValue(r) === "never" ? "selected" : ""}>Never auto-delete</option>
            <option value="24h" ${repoPolicyValue(r) === "24h" ? "selected" : ""}>Delete after 24 hours</option>
            <option value="7d" ${repoPolicyValue(r) === "7d" ? "selected" : ""}>Delete after 7 days</option>
            <option value="30d" ${repoPolicyValue(r) === "30d" ? "selected" : ""}>Delete after 30 days</option>
          </select>
          <button class="repo-btn small repo-policy-save-btn" type="button" data-repo-hash="${esc(r.repo_hash)}">Set Auto-Delete Policy</button>
        </div>
        <div class="repo-row-actions">
          <button class="repo-btn small repo-open-btn" type="button" data-repo-hash="${esc(r.repo_hash)}">Open</button>
          <button class="repo-btn small repo-analyze-btn" type="button" data-repo-hash="${esc(r.repo_hash)}">${r.has_analysis ? "Re-analyze" : "Analyze"}</button>
          <button class="repo-btn small danger repo-clear-btn" type="button" data-repo-hash="${esc(r.repo_hash)}">Delete Analysis Data</button>
          <button class="repo-btn small danger repo-delete-btn" type="button" data-repo-hash="${esc(r.repo_hash)}">Delete Repo Completely</button>
          <button class="repo-btn small repo-remove-btn" type="button" data-repo-hash="${esc(r.repo_hash)}">Remove from list</button>
        </div>
      </div>
    `).join("");

    repoListContentEl.querySelectorAll(".repo-open-btn").forEach((el) => {
      el.addEventListener("click", async () => {
        const repoHash = el.getAttribute("data-repo-hash");
        if (!repoHash) return;
        await selectWorkspace(repoHash);
      });
    });
    repoListContentEl.querySelectorAll(".repo-analyze-btn").forEach((el) => {
      el.addEventListener("click", async () => {
        const repoHash = el.getAttribute("data-repo-hash");
        if (!repoHash) return;
        await analyzeRepoByHash(repoHash);
      });
    });
    repoListContentEl.querySelectorAll(".repo-clear-btn").forEach((el) => {
      el.addEventListener("click", async () => {
        const repoHash = el.getAttribute("data-repo-hash");
        if (!repoHash) return;
        await clearRepoByHash(repoHash);
      });
    });
    repoListContentEl.querySelectorAll(".repo-delete-btn").forEach((el) => {
      el.addEventListener("click", async () => {
        const repoHash = el.getAttribute("data-repo-hash");
        if (!repoHash) return;
        await deleteRepoByHash(repoHash);
      });
    });
    repoListContentEl.querySelectorAll(".repo-remove-btn").forEach((el) => {
      el.addEventListener("click", async () => {
        const repoHash = el.getAttribute("data-repo-hash");
        if (!repoHash) return;
        await removeRepoFromList(repoHash);
      });
    });
    repoListContentEl.querySelectorAll(".repo-policy-save-btn").forEach((el) => {
      el.addEventListener("click", async () => {
        const repoHash = el.getAttribute("data-repo-hash");
        if (!repoHash) return;
        const select = repoListContentEl.querySelector(`.repo-policy-select[data-repo-hash="${CSS.escape(repoHash)}"]`);
        const policy = select ? String(select.value || "30d") : "30d";
        await setRepoPolicy(repoHash, policy);
      });
    });
  }

  async function loadRepoRegistry() {
    try {
      const data = await fetchJson("/api/repo_registry");
      repoRegistry = Array.isArray(data.repos) ? data.repos : [];
      renderRepoRegistry();
    } catch (_e) {
      repoRegistry = [];
      if (repoListContentEl) repoListContentEl.innerHTML = "<div class='muted'>Failed to load repo registry.</div>";
    }
  }

  async function analyzeRepoByHash(repoHash) {
    if (!repoHash) return;
    try {
      const data = await fetchJson("/api/repo_analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_hash: repoHash }),
      });
      if (!data.ok) {
        window.alert((data.analyze_result && (data.analyze_result.message || data.analyze_result.error)) || "Analyze failed");
      }
      await loadWorkspace();
      if (repoHash) {
        await selectWorkspace(repoHash);
      }
    } catch (e) {
      window.alert(redactSecrets((e && (e.message || e.error)) || "Analyze failed"));
    }
  }

  async function clearRepoByHash(repoHash) {
    if (!repoHash) return;
    if (!window.confirm(`Delete analysis data for repo hash ${repoHash}?`)) return;
    try {
      await fetchJson("/api/data_privacy/delete_analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_hash: repoHash, dry_run: false, yes: true }),
      });
      await loadRepoRegistry();
      await loadDataPrivacy();
      if (String(activeRepoHash) === String(repoHash)) {
        await refreshForActiveRepo();
      }
    } catch (e) {
      window.alert(redactSecrets((e && (e.message || e.error)) || "Delete analysis data failed"));
    }
  }

  async function deleteRepoByHash(repoHash) {
    if (!repoHash) return;
    if (!window.confirm("This will permanently remove analysis data and cloned/downloaded source.")) return;
    try {
      await fetchJson("/api/data_privacy/delete_repo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_hash: repoHash, dry_run: false, yes: true }),
      });
      await loadWorkspace();
      await refreshForActiveRepo();
      await loadDataPrivacy();
    } catch (e) {
      window.alert(redactSecrets((e && (e.message || e.error)) || "Delete failed"));
    }
  }

  async function removeRepoFromList(repoHash) {
    if (!repoHash) return;
    if (!window.confirm(`Remove repo ${repoHash} from UI list?`)) return;
    try {
      await fetchJson("/api/workspace/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_hash: repoHash }),
      });
      if (autoCleanOnRemove) {
        await fetchJson("/api/data_privacy/delete_analysis", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ repo_hash: repoHash, dry_run: false, yes: true }),
        });
      }
      await loadWorkspace();
      await refreshForActiveRepo();
    } catch (e) {
      window.alert(redactSecrets((e && (e.message || e.error)) || "Remove failed"));
    }
  }

  async function setRepoPolicy(repoHash, policyValue) {
    try {
      await fetchJson("/api/data_privacy/repo_policy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_hash: repoHash, policy: policyValue }),
      });
      await loadRepoRegistry();
      await loadDataPrivacy();
    } catch (e) {
      window.alert(redactSecrets((e && (e.message || e.error)) || "Policy update failed"));
    }
  }

  async function loadDataPrivacy() {
    if (!privacySummaryEl) return;
    privacySummaryEl.textContent = "Loading data retention...";
    privacyExpiringEl.innerHTML = "";
    try {
      const data = await fetchJson("/api/data_privacy");
      dataPrivacyCache = data;
      const policy = data.policy || {};
      if (policyDefaultTtlEl) policyDefaultTtlEl.value = String(policy.default_ttl_days ?? 30);
      if (policyWorkspaceTtlEl) policyWorkspaceTtlEl.value = String(policy.workspaces_ttl_days ?? 7);

      const oldest = data.oldest_repo ? ` | Oldest: ${String(data.oldest_repo.repo_path || data.oldest_repo.repo_hash || "")}` : "";
      const largest = data.largest_repo ? ` | Largest: ${formatBytes(data.largest_repo.size_bytes || 0)}` : "";
      privacySummaryEl.textContent = `Repos cached: ${data.repo_count || 0} | Total size: ${formatBytes(data.total_cache_size_bytes || 0)} | Last cleanup: ${data.last_cleanup_iso || "never"}${oldest}${largest}`;

      const expiring = Array.isArray(data.expiring_soon) ? data.expiring_soon : [];
      if (expiring.length) {
        privacyExpiringEl.innerHTML = expiring
          .slice(0, 5)
          .map((x) => {
            const target = String(x.repo_path || x.repo_hash || "repo");
            const days = Number(x.days_left);
            const label = Number.isFinite(days) ? `${Math.max(0, days).toFixed(1)} days` : "soon";
            return `<div class="privacy-warning">This repo cache will be auto-deleted in ${esc(label)}: ${esc(target)}</div>`;
          })
          .join("");
      } else {
        privacyExpiringEl.innerHTML = "<div class='muted'>No caches near expiration.</div>";
      }
    } catch (e) {
      const msg = redactSecrets((e && (e.message || e.error)) || "Failed to load data privacy status");
      privacySummaryEl.textContent = msg;
      privacyExpiringEl.innerHTML = "";
    }
  }

  async function saveRetentionPolicy() {
    const defaultTtl = Number(policyDefaultTtlEl && policyDefaultTtlEl.value ? policyDefaultTtlEl.value : 30);
    const workspaceTtl = Number(policyWorkspaceTtlEl && policyWorkspaceTtlEl.value ? policyWorkspaceTtlEl.value : 7);
    if (!Number.isFinite(defaultTtl) || defaultTtl < 0 || !Number.isFinite(workspaceTtl) || workspaceTtl < 0) {
      if (privacyResultEl) privacyResultEl.textContent = "Enter valid non-negative TTL values.";
      return;
    }
    try {
      const data = await fetchJson("/api/data_privacy/policy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          default_ttl_days: Math.floor(defaultTtl),
          workspaces_ttl_days: Math.floor(workspaceTtl),
        }),
      });
      if (privacyResultEl) privacyResultEl.textContent = `Policy saved: cache ${data.policy.default_ttl_days}d, workspaces ${data.policy.workspaces_ttl_days}d`;
      await loadDataPrivacy();
    } catch (e) {
      if (privacyResultEl) privacyResultEl.textContent = redactSecrets((e && (e.message || e.error)) || "Policy update failed.");
    }
  }

  async function runRetentionCleanup(dryRun) {
    try {
      if (!dryRun) {
        const ok = window.confirm("Run cleanup now? This deletes expired cache/workspace data.");
        if (!ok) return;
      }
      const data = await fetchJson("/api/data_privacy/cleanup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dry_run: !!dryRun,
          yes: !dryRun,
          apply: !dryRun,
        }),
      });
      if (privacyResultEl) {
        privacyResultEl.textContent = `caches_removed=${(data.caches_removed || []).length}, workspaces_removed=${(data.workspaces_removed || []).length}, freed~${formatBytes(data.freed_bytes_estimate || 0)}`;
      }
      await loadDataPrivacy();
      await loadWorkspace();
    } catch (e) {
      if (privacyResultEl) privacyResultEl.textContent = redactSecrets((e && (e.message || e.error)) || "Cleanup failed.");
    }
  }

  async function deleteActiveRepoCache() {
    if (!activeRepoHash) {
      if (privacyResultEl) privacyResultEl.textContent = "No active repo selected.";
      return;
    }
    const ok = window.confirm(`Delete cached data for repo hash ${activeRepoHash}?`);
    if (!ok) return;
    try {
      const data = await fetchJson("/api/data_privacy/delete_repo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_hash: activeRepoHash, dry_run: false, yes: true }),
      });
      if (privacyResultEl) privacyResultEl.textContent = `Deleted cache for ${data.repo_hash}. Freed~${formatBytes(data.freed_bytes_estimate || 0)}`;
      await loadWorkspace();
      await refreshForActiveRepo();
      await loadDataPrivacy();
    } catch (e) {
      if (privacyResultEl) privacyResultEl.textContent = redactSecrets((e && (e.message || e.error)) || "Delete failed.");
    }
  }

  function renderTreeNode(node, parentEl) {
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.className = `tree-item ${node.type === "file" ? "file" : "dir"}`;
    label.textContent = node.type === "file" ? node.name : `${node.name}/`;
    if (node.type === "file") {
      label.setAttribute("data-file-path", node.path || "");
    }
    li.appendChild(label);
    parentEl.appendChild(li);

    if (node.type === "file") {
      label.addEventListener("click", () => loadFile(node.path));
      return;
    }
    const children = node.children || [];
    if (!children.length) return;

    const ul = document.createElement("ul");
    li.appendChild(ul);
    children.forEach((child) => renderTreeNode(child, ul));
  }

  async function loadMeta() {
    try {
      const meta = await fetchJson("/api/meta");
      repoDir = meta.repo_dir || "";
      repoName = String(repoDir || "").replace(/\\/g, "/").split("/").filter(Boolean).pop() || "repo";
      if (repoNameEl) repoNameEl.textContent = repoName;
      const counts = meta.counts || {};
      metaEl.textContent = `${meta.repo_hash} | symbols ${counts.symbols || 0} | calls ${counts.resolved_calls || 0}`;
      return true;
    } catch (e) {
      const msg = redactSecrets((e && (e.message || e.error)) || "Metadata unavailable");
      if (repoNameEl) repoNameEl.textContent = "No repo";
      metaEl.textContent = msg;
      recentSymbols = [];
      recentFiles = [];
      lastSymbol = "";
      renderRecents();
      clearWorkspaceView(msg);
      if (e && String(e.error || "") === "CACHE_NOT_FOUND") {
        showMissingAnalysisState(msg);
      }
      return false;
    }
  }

  async function loadTree() {
    treeStatusEl.textContent = "";
    try {
      const data = await fetchJson("/api/tree");
      const tree = normalizeTree(data);
      treeEl.innerHTML = "";
      const ul = document.createElement("ul");
      treeEl.appendChild(ul);
      renderTreeNode(tree, ul);
      highlightActiveFile();
      return true;
    } catch (e) {
      treeEl.innerHTML = "";
      treeStatusEl.textContent = redactSecrets((e && (e.error || e.message)) || "Failed to load tree");
      if (e && String(e.error || "") === "CACHE_NOT_FOUND") {
        showMissingAnalysisState(redactSecrets((e && (e.message || e.error)) || "Missing analysis"));
      }
      return false;
    }
  }

  function renderSymbolGroup(symbols) {
    const classes = (symbols && symbols.classes) || [];
    const functions = (symbols && symbols.functions) || [];
    const moduleScope = (symbols && symbols.module_scope) || null;
    const hasScriptOnly = moduleScope && classes.length === 0 && functions.length === 0;

    const moduleHtml = moduleScope
      ? `<div class="block">
          <div class="section-title">Module Scope</div>
          <div>
            <span class="symbol-link ${moduleScope.fqn === activeSymbolFqn ? "active" : ""}" data-fqn="${esc(moduleScope.fqn)}">&lt;module&gt;</span>
            <span class="path">(${esc(moduleScope.outgoing_calls_count)} outgoing calls)</span>
          </div>
          ${hasScriptOnly ? "<div class='muted'>This file is a script with module-level code. Select &lt;module&gt; to inspect calls.</div>" : ""}
        </div>`
      : "";

    const classHtml = classes.length
      ? classes.map((c) => `
        <div class="symbol-class" data-class-name="${esc(c.name)}">
          <div class="symbol-name symbol-class-name">${esc(c.name)}</div>
          <div class="symbol-methods">
            ${(c.methods || []).map((m) => `
              <div class="symbol-method-row">
                <span class="method-prefix">|-</span>
                <span class="symbol-link ${m === activeSymbolFqn ? "active" : ""}" data-fqn="${esc(m)}">${esc(m.split(".").slice(-1)[0])}</span>
              </div>
            `).join("")}
          </div>
        </div>`).join("")
      : "<div class='muted'>None</div>";

    const fnHtml = functions.length
      ? functions.map((f) => `<div><span class="symbol-link ${f === activeSymbolFqn ? "active" : ""}" data-fqn="${esc(f)}">${esc(f.split(".").slice(-1)[0])}</span></div>`).join("")
      : "<div class='muted'>None</div>";

    return `
      ${moduleHtml}
      <div class="section-title">Classes</div>
      ${classHtml}
      <div class="section-title">Functions</div>
      ${fnHtml}
    `;
  }

  function bindSymbolLinks(container) {
    container.querySelectorAll(".symbol-link").forEach((el) => {
      el.addEventListener("click", () => loadSymbol(el.getAttribute("data-fqn")));
    });
  }

  function bindConnectionLinks(container) {
    container.querySelectorAll(".connection-link").forEach((el) => {
      el.addEventListener("click", () => loadSymbol(el.getAttribute("data-fqn")));
    });
  }

  function bindBreadcrumbs(container, currentFqn) {
    container.querySelectorAll(".crumb-link").forEach((el) => {
      const action = el.getAttribute("data-action");
      const value = el.getAttribute("data-value");
      el.addEventListener("click", async () => {
        if (action === "file" && value) {
          await loadFile(value);
          return;
        }
        if (action === "class" && value) {
          scrollClassIntoView(value);
          return;
        }
        if (action === "symbol" && value) {
          await loadSymbol(value);
          return;
        }
        if (action === "repo" && activeFilePath) {
          await loadFile(activeFilePath);
          return;
        }
        if (currentFqn) {
          await loadSymbol(currentFqn);
        }
      });
    });
  }

  function bindConnectionChips(container) {
    container.querySelectorAll(".chip").forEach((el) => {
      el.addEventListener("click", () => {
        const targetId = el.getAttribute("data-target");
        const target = targetId ? container.querySelector(`#${targetId}`) : null;
        if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  function scrollClassIntoView(className) {
    if (!className) return;
    const target = fileViewEl.querySelector(`.symbol-class[data-class-name="${CSS.escape(className)}"]`);
    if (target) {
      target.scrollIntoView({ block: "nearest", behavior: "smooth" });
      const classLabel = target.querySelector(".symbol-class-name");
      if (classLabel) {
        classLabel.classList.add("active-class");
        window.setTimeout(() => classLabel.classList.remove("active-class"), 800);
      }
    }
  }

  function highlightActiveSymbol() {
    const links = fileViewEl.querySelectorAll(".symbol-link");
    links.forEach((el) => {
      const isActive = el.getAttribute("data-fqn") === activeSymbolFqn;
      el.classList.toggle("active", isActive);
      if (isActive) {
        el.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    });
  }

  function highlightActiveFile() {
    const links = treeEl.querySelectorAll(".tree-item.file");
    links.forEach((el) => {
      const isActive = el.getAttribute("data-file-path") === activeFilePath;
      el.classList.toggle("active-file", isActive);
      if (isActive) {
        el.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    });
  }

  function closeSearchDropdown() {
    searchResultsEl.classList.add("hidden");
    searchResultsEl.innerHTML = "";
    currentSearchResults = [];
  }

  function renderSearchResults(results, truncated) {
    currentSearchResults = results || [];
    if (!currentSearchResults.length) {
      searchResultsEl.classList.add("hidden");
      searchResultsEl.innerHTML = "";
      return;
    }

    const rows = currentSearchResults.map((r) => `
      <button class="search-row" data-fqn="${esc(r.fqn)}" data-file="${esc(r.file)}">
        <div class="search-primary">${esc(r.display)}</div>
        <div class="search-secondary">${esc(r.module)}${r.file ? ` | ${esc(r.file)}:${esc(r.line)}` : ""}</div>
      </button>
    `).join("");

    searchResultsEl.innerHTML = `
      ${rows}
      ${truncated ? "<div class='search-more'>Showing first 20...</div>" : ""}
    `;
    searchResultsEl.classList.remove("hidden");

    searchResultsEl.querySelectorAll(".search-row").forEach((row) => {
      row.addEventListener("click", async () => {
        await selectSearchResult({
          fqn: row.getAttribute("data-fqn"),
          file: row.getAttribute("data-file"),
        });
      });
    });
  }

  async function runSymbolSearch(query) {
    const q = String(query || "").trim();
    if (!q) {
      closeSearchDropdown();
      return;
    }
    try {
      const data = await fetchJson(`/api/search?q=${encodeURIComponent(q)}&limit=20`);
      renderSearchResults(data.results || [], !!data.truncated);
    } catch (_e) {
      closeSearchDropdown();
    }
  }

  async function selectSearchResult(item) {
    closeSearchDropdown();
    if (!item || !item.fqn) return;
    if (item.file) {
      await loadFile(item.file);
    }
    await loadSymbol(item.fqn);
  }

  function bindSearchInput() {
    if (!searchInputEl) return;
    searchInputEl.addEventListener("input", () => {
      if (searchTimer) clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        runSymbolSearch(searchInputEl.value);
      }, 200);
    });

    searchInputEl.addEventListener("keydown", async (e) => {
      if (e.key === "Escape") {
        closeSearchDropdown();
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        if (currentSearchResults.length > 0) {
          await selectSearchResult(currentSearchResults[0]);
        }
      }
    });
  }

  function bindWorkspaceControls() {
    if (repoSelectEl) {
      repoSelectEl.addEventListener("change", async () => {
        const selected = repoSelectEl.value;
        if (selected && selected !== activeRepoHash) {
          await selectWorkspace(selected);
        }
      });
    }
    if (addRepoBtnEl) {
      addRepoBtnEl.addEventListener("click", async () => {
        await addWorkspaceRepo();
      });
    }
  }

  let repoInlineBound = false;
  let repoAddInFlight = false;
  let repoAddAbortController = null;

  function showToast(message, type) {
    if (!toastEl) return;
    toastEl.textContent = redactSecrets(String(message || ""));
    toastEl.classList.remove("hidden", "error");
    if (String(type || "") === "error") toastEl.classList.add("error");
    window.setTimeout(() => {
      toastEl.classList.add("hidden");
    }, 2200);
  }

  function updatePrivateModeIndicator() {
    if (!privateModeIndicatorEl) return;
    const hasToken = !!(ghTokenEl && String(ghTokenEl.value || "").trim());
    privateModeIndicatorEl.classList.toggle("hidden", !hasToken);
  }

  function setRepoPanelTab(tab) {
    const local = tab !== "github";
    if (repoTabLocalEl) repoTabLocalEl.classList.toggle("active", local);
    if (repoTabGithubEl) repoTabGithubEl.classList.toggle("active", !local);
    if (repoFormLocalEl) repoFormLocalEl.classList.toggle("hidden", !local);
    if (repoFormGithubEl) repoFormGithubEl.classList.toggle("hidden", local);
    validateRepoPanel();
  }

  function resetRepoPanelState() {
    if (localRepoPathEl) localRepoPathEl.value = "";
    if (localDisplayNameEl) localDisplayNameEl.value = "";
    if (ghRepoUrlEl) ghRepoUrlEl.value = "";
    if (ghRefEl) ghRefEl.value = "main";
    if (ghModeEl) ghModeEl.value = "zip";
    if (ghTokenEl) ghTokenEl.value = "";
    updatePrivateModeIndicator();
    if (repoOpenAfterAddEl) repoOpenAfterAddEl.checked = true;
    if (repoModalErrorEl) repoModalErrorEl.textContent = "";
    repoAddInFlight = false;
    repoAddAbortController = null;
    setRepoPanelLoading(false);
  }

  function setRepoPanelLoading(isLoading) {
    if (repoAddBtnEl) {
      repoAddBtnEl.disabled = !!isLoading;
      repoAddBtnEl.textContent = isLoading ? "Adding..." : "Add repo";
      repoAddBtnEl.classList.toggle("is-loading", !!isLoading);
    }
    if (repoCancelBtnEl) repoCancelBtnEl.disabled = false;
    if (repoInlineCloseEl) repoInlineCloseEl.disabled = false;
    validateRepoPanel();
  }

  function validateRepoPanel() {
    const githubActive = repoFormGithubEl && !repoFormGithubEl.classList.contains("hidden");
    let valid = false;
    let message = "";
    if (githubActive) {
      const url = String(ghRepoUrlEl && ghRepoUrlEl.value ? ghRepoUrlEl.value : "").trim();
      const ok = /^https:\/\/github\.com\/[^\/\s]+\/[^\/\s]+\/?(\.git)?$/i.test(url) || /^https:\/\/github\.com\/[^\/\s]+\/[^\/\s]+(\.git)?$/i.test(url);
      valid = !!url && ok;
      if (url && !ok) message = "Invalid GitHub URL.";
    } else {
      const path = String(localRepoPathEl && localRepoPathEl.value ? localRepoPathEl.value : "").trim();
      valid = !!path;
      if (!path) message = "Local path is required.";
    }
    if (repoModalErrorEl && !repoAddInFlight) repoModalErrorEl.textContent = redactSecrets(message);
    if (repoAddBtnEl) repoAddBtnEl.disabled = repoAddInFlight || !valid;
    return valid;
  }

  function openRepoPanel(tab) {
    if (!addRepoInlineEl) return;
    resetRepoPanelState();
    addRepoInlineEl.classList.remove("hidden");
    setRepoPanelTab(tab || "local");
    if (localRepoPathEl) localRepoPathEl.focus();
  }

  function closeRepoPanel(force) {
    if (!addRepoInlineEl) return;
    if (repoAddInFlight && !force) {
      const shouldClose = window.confirm("Request in progress. Close anyway?");
      if (!shouldClose) return;
      if (repoAddAbortController) {
        try { repoAddAbortController.abort(); } catch (_e) {}
      }
    }
    addRepoInlineEl.classList.add("hidden");
    resetRepoPanelState();
  }

  async function runAddRepository() {
    if (!validateRepoPanel()) return;
    const wasActiveRepo = activeRepoHash;
    const hadSelection = !!wasActiveRepo;
    const openAfterAdd = !!(repoOpenAfterAddEl && repoOpenAfterAddEl.checked);
    const githubActive = repoFormGithubEl && !repoFormGithubEl.classList.contains("hidden");

    repoAddInFlight = true;
    repoAddAbortController = new AbortController();
    setRepoPanelLoading(true);
    if (repoModalErrorEl) repoModalErrorEl.textContent = "";

    try {
      let data;
      if (githubActive) {
        const repoUrl = String(ghRepoUrlEl && ghRepoUrlEl.value ? ghRepoUrlEl.value : "").trim();
        const ref = String(ghRefEl && ghRefEl.value ? ghRefEl.value : "main").trim() || "main";
        const mode = String(ghModeEl && ghModeEl.value ? ghModeEl.value : "zip").trim() || "zip";
        const displayName = "";
        data = await fetchJson("/api/repo_import/github_add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ repo_url: repoUrl, ref, mode, display_name: displayName, open_after_add: openAfterAdd }),
          signal: repoAddAbortController.signal,
        });
      } else {
        const repoPath = String(localRepoPathEl && localRepoPathEl.value ? localRepoPathEl.value : "").trim();
        const displayName = String(localDisplayNameEl && localDisplayNameEl.value ? localDisplayNameEl.value : "").trim();
        data = await fetchJson("/api/repo_import/local", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ repo_path: repoPath, display_name: displayName, analyze: false, open_after_add: openAfterAdd }),
          signal: repoAddAbortController.signal,
        });
      }

      const addedName = (data && data.repo && data.repo.name) ? data.repo.name : "Repository";
      showToast(`Repo added: ${addedName}`, "success");
      closeRepoPanel(true);

      // Refresh/selection updates run after close so modal never blocks app interaction.
      try {
        await loadWorkspace();
        await loadRepoRegistry();
        if (!hadSelection || openAfterAdd) {
          if (data.repo_hash) {
            await selectWorkspace(data.repo_hash);
          }
        } else if (wasActiveRepo && data.repo_hash !== wasActiveRepo) {
          await selectWorkspace(wasActiveRepo);
        }
      } catch (_postSuccessErr) {
        // Keep app usable; repo add already succeeded.
      }
    } catch (e) {
      if (repoModalErrorEl) repoModalErrorEl.textContent = redactSecrets((e && (e.message || e.error)) || "Failed to add repository.");
      showToast(redactSecrets((e && (e.message || e.error)) || "Failed to add repository."), "error");
    } finally {
      if (ghTokenEl) ghTokenEl.value = "";
      updatePrivateModeIndicator();
      repoAddInFlight = false;
      repoAddAbortController = null;
      setRepoPanelLoading(false);
    }
  }

  function bindDataPrivacyControls() {
    try {
      autoCleanOnRemove = window.localStorage.getItem("codemap_auto_clean_on_remove") === "1";
    } catch (_e) {
      autoCleanOnRemove = false;
    }
    if (autoCleanOnRemoveEl) {
      autoCleanOnRemoveEl.checked = !!autoCleanOnRemove;
      autoCleanOnRemoveEl.addEventListener("change", () => {
        autoCleanOnRemove = !!autoCleanOnRemoveEl.checked;
        try {
          window.localStorage.setItem("codemap_auto_clean_on_remove", autoCleanOnRemove ? "1" : "0");
        } catch (_e) {
          // ignore
        }
      });
    }
    if (policySaveBtnEl) {
      policySaveBtnEl.addEventListener("click", () => {
        saveRetentionPolicy();
      });
    }
    if (cleanupDryBtnEl) {
      cleanupDryBtnEl.addEventListener("click", () => {
        runRetentionCleanup(true);
      });
    }
    if (cleanupNowBtnEl) {
      cleanupNowBtnEl.addEventListener("click", () => {
        runRetentionCleanup(false);
      });
    }
    if (deleteRepoCacheBtnEl) {
      deleteRepoCacheBtnEl.addEventListener("click", () => {
        deleteActiveRepoCache();
      });
    }
  }

  function bindRepoInlineControls() {
    if (repoInlineBound) return;
    repoInlineBound = true;
    if (repoInlineCloseEl) repoInlineCloseEl.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      closeRepoPanel(false);
    });
    if (repoCancelBtnEl) repoCancelBtnEl.addEventListener("click", (e) => {
      e.preventDefault();
      closeRepoPanel(false);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && addRepoInlineEl && !addRepoInlineEl.classList.contains("hidden")) {
        closeRepoPanel(false);
      }
    });
    if (repoTabLocalEl) repoTabLocalEl.addEventListener("click", () => setRepoPanelTab("local"));
    if (repoTabGithubEl) repoTabGithubEl.addEventListener("click", () => setRepoPanelTab("github"));
    if (repoAddBtnEl) repoAddBtnEl.addEventListener("click", () => runAddRepository());
    if (localRepoPathEl) localRepoPathEl.addEventListener("input", () => validateRepoPanel());
    if (ghRepoUrlEl) ghRepoUrlEl.addEventListener("input", () => validateRepoPanel());
    if (ghTokenEl) ghTokenEl.addEventListener("input", () => updatePrivateModeIndicator());
  }

  function bindGraphControls() {
    if (tabDetailsEl) tabDetailsEl.addEventListener("click", () => setActiveTab("details"));
    if (tabImpactEl) tabImpactEl.addEventListener("click", () => setActiveTab("impact"));
    if (tabGraphEl) tabGraphEl.addEventListener("click", () => setActiveTab("graph"));
    if (tabArchitectureEl) tabArchitectureEl.addEventListener("click", () => setActiveTab("architecture"));
    const rerender = () => {
      graphDataCache.clear();
      if (activeTab === "graph") loadGraph();
    };
    if (graphModeEl) graphModeEl.addEventListener("change", rerender);
    if (graphDepthEl) graphDepthEl.addEventListener("change", rerender);
    if (graphHideBuiltinsEl) graphHideBuiltinsEl.addEventListener("change", rerender);
    if (graphHideExternalEl) graphHideExternalEl.addEventListener("change", rerender);
    if (graphSearchEl) graphSearchEl.addEventListener("input", () => {
      if (activeTab === "graph") {
        const p = graphParams();
        const graphMode = p.mode === "file" ? "file" : "symbol";
        const anchor = graphMode === "file" ? activeFilePath : activeSymbolFqn;
        const key = `${graphMode}|${anchor}|${p.depth}|${p.hideBuiltins}|${p.hideExternal}`;
        const cached = graphDataCache.get(key);
        if (cached) renderGraphData(cached);
      }
    });
    const rerenderImpact = () => {
      impactDataCache.clear();
      if (activeTab === "impact") loadImpact();
    };
    if (impactDepthEl) impactDepthEl.addEventListener("change", rerenderImpact);
    if (impactMaxNodesEl) impactMaxNodesEl.addEventListener("change", rerenderImpact);
  }

  async function loadFile(relFilePath) {
    activeFilePath = relFilePath;
    highlightActiveFile();
    graphDataCache.clear();
    impactDataCache.clear();
    fileViewEl.classList.remove("muted");
    fileViewEl.textContent = "Loading file intelligence...";
    try {
      let data = fileCache.get(relFilePath);
      if (!data) {
        data = await fetchJson(`/api/file?path=${encodeURIComponent(relFilePath)}`);
        fileCache.set(relFilePath, data);
      }

      fileViewEl.innerHTML = `
        <div class="card">
          <div class="line"><span class="label">File</span><span class="path">${esc(data.file)}</span></div>
          <div class="line"><span class="label">Incoming usages</span><span>${data.incoming_usages_count}</span></div>
          <div class="line"><span class="label">Outgoing calls</span><span>${data.outgoing_calls_count}</span></div>
        </div>
        <div class="card">
          ${renderSymbolGroup(data.symbols)}
        </div>
      `;

      bindSymbolLinks(fileViewEl);
      highlightActiveSymbol();
      highlightActiveFile();
      await updateUiState({ opened_file: relFilePath });
      if (activeTab === "graph" && graphParams().mode === "file") {
        await loadGraph();
      }
    } catch (e) {
      fileViewEl.classList.add("muted");
      fileViewEl.textContent = redactSecrets((e && (e.error || e.message)) || "Failed to load file intelligence");
    }
  }

  function delay(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function renderEmptyState(text) {
    return `<div class="empty-state">OK ${esc(text)}</div>`;
  }

  function showSymbolLoading() {
    symbolViewEl.classList.remove("muted");
    symbolViewEl.innerHTML = `
      <div class="card shimmer-card">
        <div class="shimmer-line w60"></div>
        <div class="shimmer-line w90"></div>
        <div class="shimmer-line w75"></div>
      </div>
    `;
    const panel = symbolViewEl.closest(".panel");
    if (panel) panel.scrollTo({ top: 0, behavior: "smooth" });
  }

  function renderConnectionBlock(items, renderer, emptyText) {
    if (!items || !items.length) {
      return renderEmptyState(emptyText);
    }
    return items.map(renderer).join("");
  }

  async function loadSymbol(fqn) {
    activeSymbolFqn = fqn;
    highlightActiveSymbol();
    graphDataCache.clear();
    impactDataCache.clear();
    showSymbolLoading();
    try {
      const symbolPromise = (async () => {
        let symbolData = symbolCache.get(fqn);
        if (!symbolData) {
          symbolData = await fetchJson(`/api/symbol?fqn=${encodeURIComponent(fqn)}`);
          symbolCache.set(fqn, symbolData);
        }
        return symbolData;
      })();

      const [symbolData] = await Promise.all([symbolPromise, delay(150)]);

      const result = symbolData.result || {};
      const loc = result.location || {};
      const relFile = relPath(loc.file || "");
      if (relFile && relFile !== activeFilePath) {
        await loadFile(relFile);
      }

      const summary = stripMarkdown(result.one_liner || "");
      const notes = (result.details || []).filter((d) => String(d).startsWith("Returns:")).slice(0, 3).map(stripMarkdown);
      const symbolParts = parseSymbolParts(result.fqn || fqn);
      const locationText = `${relFile}:${loc.start_line || ""}`;
      const connections = result.connections || {};
      const calledBy = connections.called_by || [];
      const calls = connections.calls || [];
      const usedIn = (connections.used_in || []).slice().sort((a, b) => (a.file || "").localeCompare(b.file || ""));

      const crumbs = [
        { label: repoName || "repo", action: "repo", value: "" },
        { label: relFile, action: "file", value: relFile },
      ];
      if (symbolParts.className) {
        crumbs.push({ label: symbolParts.className, action: "class", value: symbolParts.className });
      }
      crumbs.push({ label: symbolParts.symbol, action: "symbol", value: result.fqn || fqn });

      symbolViewEl.innerHTML = `
        <div class="card symbol-card fade-panel">
          <div class="breadcrumbs">
            ${crumbs.map((c) => `<span class="crumb-link" data-action="${esc(c.action)}" data-value="${esc(c.value)}">${esc(c.label)}</span>`).join("<span class='crumb-sep'>></span>")}
          </div>
          <div class="chips">
            <button class="chip" data-target="called-by-section">Called by: ${calledBy.length}</button>
            <button class="chip" data-target="calls-section">Calls: ${calls.length}</button>
            <button class="chip" data-target="used-in-section">Used in: ${usedIn.length}</button>
          </div>
          <div class="symbol-title-main">${esc(symbolParts.display)}</div>
          <div class="path">FQN: ${esc(result.fqn || fqn)}</div>
          <div class="path">${esc(locationText)}</div>
          <div class="divider"></div>
          <div class="section-title">Summary</div>
          <div>${esc(summary)}</div>
          <div id="called-by-section" class="divider"></div>
          <div class="section-title">Called by</div>
          ${renderConnectionBlock(calledBy, (c) => `
            <div>
              <span class="conn-arrow">-></span><span class="connection-link" data-fqn="${esc(c.fqn)}">${esc(c.fqn)}</span>
              <span class="path">${esc(c.file)}:${esc(c.line)}</span>
            </div>
          `, "No callers found")}
          <div id="calls-section" class="divider"></div>
          <div class="section-title">Calls</div>
          ${renderConnectionBlock(calls, (c) => `
            <div>
              ${c.clickable
                ? `<span class="conn-arrow">-></span><span class="connection-link" data-fqn="${esc(c.fqn)}">${esc(c.name)}</span>`
                : `<span class="connection-muted">${esc(c.name)}</span>`
              }
              <span class="path">(${esc(c.count)}x)</span>
            </div>
          `, "No calls found")}
          <div class="divider"></div>
          <div class="section-title">Top Callees</div>
          ${renderConnectionBlock(calls.slice(0, 10), (c) => `
            <div>
              <span class="${c.clickable ? "connection-link" : "connection-muted"}" ${c.clickable ? `data-fqn="${esc(c.fqn)}"` : ""}>${esc(c.name)}</span>
              <span class="path">(${esc(c.count)}x)</span>
            </div>
          `, "No callees found")}
          <div id="used-in-section" class="divider"></div>
          <div class="section-title">Used in</div>
          ${renderConnectionBlock(usedIn, (u) => `
            <div>
              <span class="conn-arrow">-></span><span class="connection-link" data-fqn="${esc(u.fqn)}">${esc(u.fqn)}</span>
              <span class="path">${esc(u.file)}:${esc(u.line)}</span>
            </div>
          `, "No usages found")}
          <div class="divider"></div>
          <div class="section-title">Notes</div>
          ${notes.length ? notes.map((n) => `<div>${esc(n)}</div>`).join("") : "<div class='muted'>None</div>"}
        </div>
      `;

      bindConnectionLinks(symbolViewEl);
      bindBreadcrumbs(symbolViewEl, result.fqn || fqn);
      bindConnectionChips(symbolViewEl);
      highlightActiveSymbol();
      await updateUiState({ opened_symbol: (result.fqn || fqn), last_symbol: (result.fqn || fqn) });
      if (activeTab === "graph" && graphParams().mode === "symbol") {
        await loadGraph(result.fqn || fqn);
      }
      if (activeTab === "impact") {
        await loadImpact(result.fqn || fqn);
      }
    } catch (e) {
      symbolViewEl.classList.add("muted");
      symbolViewEl.textContent = redactSecrets((e && (e.error || e.message)) || "Failed to load symbol intelligence");
    }
  }

  async function refreshForActiveRepo() {
    clearWorkspaceView("Loading workspace...");
    architectureCache = null;
    repoSummary = null;
    repoSummaryUpdatedAt = "";
    repoSummaryStatus = "idle";
    repoSummaryError = "";
    riskRadar = null;
    riskRadarUpdatedAt = "";
    riskRadarStatus = "idle";
    riskRadarError = "";
    await loadRepoRegistry();
    const okMeta = await loadMeta();
    await loadDataPrivacy();
    if (!okMeta) return;
    await loadTree();
    await loadUiState();
    if (lastSymbol) {
      await loadSymbol(lastSymbol);
      return;
    }
    if (recentFiles.length) {
      await loadFile(recentFiles[0]);
    }
  }

  async function init() {
    bindSearchInput();
    bindWorkspaceControls();
    bindRepoInlineControls();
    bindDataPrivacyControls();
    bindGraphControls();
    setActiveTab("details");
    try {
      await loadWorkspace();
      await refreshForActiveRepo();
    } catch (e) {
      metaEl.textContent = redactSecrets((e && (e.message || e.error)) || "Workspace unavailable");
      clearWorkspaceView(metaEl.textContent);
    }
  }

  init();
})();

