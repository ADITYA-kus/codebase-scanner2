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
  const tabGraphEl = document.getElementById("tab-graph");
  const graphControlsEl = document.getElementById("graph-controls");
  const graphViewEl = document.getElementById("graph-view");
  const graphModeEl = document.getElementById("graph-mode");
  const graphDepthEl = document.getElementById("graph-depth");
  const graphHideBuiltinsEl = document.getElementById("graph-hide-builtins");
  const graphHideExternalEl = document.getElementById("graph-hide-external");
  const graphSearchEl = document.getElementById("graph-search");
  const recentSymbolsEl = document.getElementById("recent-symbols");
  const recentFilesEl = document.getElementById("recent-files");
  const recentSymbolsWrapEl = document.getElementById("recent-symbols-wrap");
  const recentFilesWrapEl = document.getElementById("recent-files-wrap");

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
    graphViewEl.classList.add("muted");
    fileViewEl.textContent = message || "Select a file from the tree.";
    symbolViewEl.textContent = "Select a symbol to view summary and usages.";
    graphViewEl.textContent = "Select a symbol to view graph.";
    recentSymbols = [];
    recentFiles = [];
    lastSymbol = "";
    renderRecents();
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
    activeTab = tab === "graph" ? "graph" : "details";
    const isGraph = activeTab === "graph";
    if (tabDetailsEl) tabDetailsEl.classList.toggle("active", !isGraph);
    if (tabGraphEl) tabGraphEl.classList.toggle("active", isGraph);
    if (symbolViewEl) symbolViewEl.classList.toggle("hidden", isGraph);
    if (graphViewEl) graphViewEl.classList.toggle("hidden", !isGraph);
    if (graphControlsEl) graphControlsEl.classList.toggle("hidden", !isGraph);
    if (isGraph) {
      loadGraph();
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
        ${incoming.length ? incoming.slice(0, 200).map((e) => `<div class="graph-edge-row">${nodePill(e.from)} <span class="edge-arrow">→</span> <span class="path">${esc(e.count)}x</span></div>`).join("") : "<div class='muted'>No incoming callers in current depth/filter.</div>"}
        <div class="divider"></div>
        <div class="section-title">Outgoing Callees (${outgoing.length})</div>
        ${outgoing.length ? outgoing.slice(0, 200).map((e) => `<div class="graph-edge-row">${nodePill(e.to)} <span class="path">${esc(e.count)}x</span></div>`).join("") : "<div class='muted'>No outgoing callees in current depth/filter.</div>"}
        ${mode === "file" ? `<div class="divider"></div><div class="section-title">Internal File Edges (${internal.length})</div>${internal.length ? internal.slice(0, 200).map((e) => `<div class="graph-edge-row">${nodePill(e.from)} <span class="edge-arrow">→</span> ${nodePill(e.to)} <span class="path">${esc(e.count)}x</span></div>`).join("") : "<div class='muted'>No internal edges in current depth/filter.</div>"}` : ""}
        <div class="divider"></div>
        <div class="section-title">Subgraph Stats</div>
        <div class="path">Nodes: ${nodes.length} · Edges: ${edges.length} · Depth: ${data.depth}</div>
      </div>
    `;

    graphViewEl.querySelectorAll(".graph-node.graph-clickable").forEach((el) => {
      el.addEventListener("click", () => {
        const next = el.getAttribute("data-node-id");
        if (next) loadSymbol(next);
      });
    });
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
      graphViewEl.textContent = (e && (e.error || e.message)) || "Graph unavailable.";
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
  }

  async function selectWorkspace(repoHash) {
    if (!repoHash) return;
    await fetchJson("/api/workspace/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_hash: repoHash }),
    });
    activeRepoHash = repoHash;
    await refreshForActiveRepo();
  }

  async function addWorkspaceRepo() {
    const value = window.prompt("Enter local repo path");
    const repoPath = String(value || "").trim();
    if (!repoPath) return;
    await fetchJson("/api/workspace/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: repoPath }),
    });
    await loadWorkspace();
    await refreshForActiveRepo();
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
      const msg = (e && (e.message || e.error)) || "Metadata unavailable";
      if (repoNameEl) repoNameEl.textContent = "No repo";
      metaEl.textContent = msg;
      recentSymbols = [];
      recentFiles = [];
      lastSymbol = "";
      renderRecents();
      clearWorkspaceView(msg);
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
      treeStatusEl.textContent = (e && (e.error || e.message)) || "Failed to load tree";
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
        <div class="search-secondary">${esc(r.module)}${r.file ? ` · ${esc(r.file)}:${esc(r.line)}` : ""}</div>
      </button>
    `).join("");

    searchResultsEl.innerHTML = `
      ${rows}
      ${truncated ? "<div class='search-more'>Showing first 20…</div>" : ""}
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
        try {
          await addWorkspaceRepo();
        } catch (e) {
          window.alert((e && (e.message || e.error)) || "Failed to add repo");
        }
      });
    }
  }

  function bindGraphControls() {
    if (tabDetailsEl) tabDetailsEl.addEventListener("click", () => setActiveTab("details"));
    if (tabGraphEl) tabGraphEl.addEventListener("click", () => setActiveTab("graph"));
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
  }

  async function loadFile(relFilePath) {
    activeFilePath = relFilePath;
    highlightActiveFile();
    graphDataCache.clear();
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
      fileViewEl.textContent = (e && (e.error || e.message)) || "Failed to load file intelligence";
    }
  }

  function delay(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function renderEmptyState(text) {
    return `<div class="empty-state">✓ ${esc(text)}</div>`;
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
              <span class="conn-arrow">↗</span><span class="connection-link" data-fqn="${esc(c.fqn)}">${esc(c.fqn)}</span>
              <span class="path">${esc(c.file)}:${esc(c.line)}</span>
            </div>
          `, "No callers found")}
          <div id="calls-section" class="divider"></div>
          <div class="section-title">Calls</div>
          ${renderConnectionBlock(calls, (c) => `
            <div>
              ${c.clickable
                ? `<span class="conn-arrow">↗</span><span class="connection-link" data-fqn="${esc(c.fqn)}">${esc(c.name)}</span>`
                : `<span class="connection-muted">${esc(c.name)}</span>`
              }
              <span class="path">(${esc(c.count)}×)</span>
            </div>
          `, "No calls found")}
          <div class="divider"></div>
          <div class="section-title">Top Callees</div>
          ${renderConnectionBlock(calls.slice(0, 10), (c) => `
            <div>
              <span class="${c.clickable ? "connection-link" : "connection-muted"}" ${c.clickable ? `data-fqn="${esc(c.fqn)}"` : ""}>${esc(c.name)}</span>
              <span class="path">(${esc(c.count)}×)</span>
            </div>
          `, "No callees found")}
          <div id="used-in-section" class="divider"></div>
          <div class="section-title">Used in</div>
          ${renderConnectionBlock(usedIn, (u) => `
            <div>
              <span class="conn-arrow">↗</span><span class="connection-link" data-fqn="${esc(u.fqn)}">${esc(u.fqn)}</span>
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
    } catch (e) {
      symbolViewEl.classList.add("muted");
      symbolViewEl.textContent = (e && (e.error || e.message)) || "Failed to load symbol intelligence";
    }
  }

  async function refreshForActiveRepo() {
    clearWorkspaceView("Loading workspace...");
    const okMeta = await loadMeta();
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
    bindGraphControls();
    setActiveTab("details");
    try {
      await loadWorkspace();
      await refreshForActiveRepo();
    } catch (e) {
      metaEl.textContent = (e && (e.message || e.error)) || "Workspace unavailable";
      clearWorkspaceView(metaEl.textContent);
    }
  }

  init();
})();
