/* docgen wizard — frontend logic */

(function () {
  "use strict";

  // ---- State ----
  let fileTree = [];
  let flatFiles = [];
  let selectedFiles = new Set();
  let segments = []; // setup segment slots
  let prodSegments = []; // production segment data
  let activeSegmentId = null;
  let activeSetupSegId = null;
  let prodFocusPaths = [];
  let appState = { segments: {} };
  let scanExtensions = null;
  let filterText = "";

  // ---- View switching ----
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
      document.getElementById("view-" + btn.dataset.view).classList.remove("hidden");
      if (btn.dataset.view === "production") loadProductionView();
    });
  });

  // ---- Tab switching ----
  document.addEventListener("click", (e) => {
    if (!e.target.classList.contains("tab-btn")) return;
    const bar = e.target.closest(".tab-bar") || e.target.parentElement;
    const parent = bar.parentElement;
    bar.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    e.target.classList.add("active");
    parent.querySelectorAll(":scope > .tab-content").forEach((tc) => {
      tc.classList.toggle("active", tc.dataset.tab === e.target.dataset.tab);
    });
  });

  // ================================================================
  // SETUP VIEW
  // ================================================================

  async function loadFileTree() {
    const mdOnly = document.getElementById("md-only")?.checked;
    const qs = mdOnly ? "?extensions=.md" : "";
    const res = await fetch("/api/scan" + qs);
    const data = await res.json();
    fileTree = data.tree;
    flatFiles = data.files;
    scanExtensions = data.extensions || [];
    renderTreeFiltered();
  }

  function pathMatchesFilter(path) {
    if (!filterText) return true;
    return path.toLowerCase().includes(filterText.toLowerCase());
  }

  function filterTree(nodes) {
    const out = [];
    for (const node of nodes) {
      if (node.type === "file") {
        if (pathMatchesFilter(node.path)) out.push(node);
      } else {
        const children = filterTree(node.children || []);
        if (children.length || pathMatchesFilter(node.path || node.name)) {
          out.push({ ...node, children });
        }
      }
    }
    return out;
  }

  function renderTreeFiltered() {
    const container = document.getElementById("file-tree");
    renderTree(filterTree(fileTree), container);
  }

  function renderTree(nodes, container) {
    container.innerHTML = "";
    for (const node of nodes) {
      if (node.type === "dir") {
        const dirEl = document.createElement("div");
        dirEl.className = "tree-item";
        const label = document.createElement("div");
        label.className = "tree-dir open";
        label.textContent = node.name;
        label.addEventListener("click", () => {
          label.classList.toggle("open");
        });
        dirEl.appendChild(label);
        const children = document.createElement("div");
        children.className = "tree-children";
        renderTree(node.children, children);
        dirEl.appendChild(children);
        container.appendChild(dirEl);
      } else {
        const fileEl = document.createElement("div");
        fileEl.className = "tree-item tree-file";
        fileEl.draggable = true;
        fileEl.addEventListener("dragstart", (e) => {
          e.dataTransfer.setData("text/plain", node.path);
        });
        const lbl = document.createElement("label");
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.dataset.path = node.path;
        cb.checked = selectedFiles.has(node.path);
        cb.addEventListener("change", () => {
          if (cb.checked) selectedFiles.add(node.path);
          else selectedFiles.delete(node.path);
          updateGenerateBtn();
        });
        lbl.appendChild(cb);
        lbl.appendChild(document.createTextNode(" " + node.name));
        fileEl.appendChild(lbl);
        if (node.snippet) {
          const snip = document.createElement("span");
          snip.className = "snippet";
          snip.textContent = node.snippet.split("\n")[0].slice(0, 80);
          snip.title = node.snippet;
          fileEl.appendChild(snip);
        }
        container.appendChild(fileEl);
      }
    }
  }

  function updateGenerateBtn() {
    const hasSeg = segments.length > 0;
    const hasFiles = selectedFiles.size > 0 || segments.some((s) => s.files.length > 0);
    document.getElementById("btn-generate").disabled = !hasSeg || !hasFiles;
    document.getElementById("btn-save-focus").disabled = !hasSeg;
  }

  // ---- Segment slots ----
  let segCounter = 0;

  document.getElementById("btn-add-segment").addEventListener("click", () => {
    segCounter++;
    const seg = {
      id: "seg-" + segCounter,
      name: String(segCounter).padStart(2, "0"),
      files: Array.from(selectedFiles),
    };
    segments.push(seg);
    activeSetupSegId = seg.id;
    renderSegmentSlots();
    updateGenerateBtn();
  });

  document.getElementById("btn-auto-group").addEventListener("click", () => {
    if (selectedFiles.size === 0) return;
    const groups = {};
    for (const p of selectedFiles) {
      const dir = p.includes("/") ? p.split("/").slice(0, -1).join("/") : "root";
      (groups[dir] = groups[dir] || []).push(p);
    }
    segments = [];
    segCounter = 0;
    for (const [dir, files] of Object.entries(groups).sort()) {
      segCounter++;
      const name = dir.replace(/\//g, "-").replace(/[^a-zA-Z0-9-]/g, "") || "root";
      segments.push({
        id: "seg-" + segCounter,
        name: String(segCounter).padStart(2, "0") + "-" + name,
        files,
      });
    }
    activeSetupSegId = segments[0]?.id || null;
    renderSegmentSlots();
    updateGenerateBtn();
  });

  document.getElementById("btn-assign-selected").addEventListener("click", () => {
    if (!activeSetupSegId || selectedFiles.size === 0) return;
    const seg = segments.find((s) => s.id === activeSetupSegId);
    if (!seg) return;
    for (const p of selectedFiles) {
      if (!seg.files.includes(p)) seg.files.push(p);
    }
    renderSegmentSlots();
    updateGenerateBtn();
  });

  function renderSegmentSlots() {
    const container = document.getElementById("segment-slots");
    container.innerHTML = "";
    for (const seg of segments) {
      const slot = document.createElement("div");
      slot.className = "segment-slot" + (seg.id === activeSetupSegId ? " active" : "");
      slot.dataset.segId = seg.id;
      slot.addEventListener("click", () => {
        activeSetupSegId = seg.id;
        renderSegmentSlots();
      });
      slot.addEventListener("dragover", (e) => e.preventDefault());
      slot.addEventListener("drop", (e) => {
        e.preventDefault();
        const path = e.dataTransfer.getData("text/plain");
        if (path && !seg.files.includes(path)) {
          seg.files.push(path);
          renderSegmentSlots();
          updateGenerateBtn();
        }
      });
      const header = document.createElement("div");
      header.className = "seg-header";
      const inp = document.createElement("input");
      inp.type = "text";
      inp.value = seg.name;
      inp.addEventListener("input", () => { seg.name = inp.value; });
      inp.addEventListener("click", (e) => e.stopPropagation());
      header.appendChild(inp);
      const rmBtn = document.createElement("button");
      rmBtn.className = "btn-remove-seg";
      rmBtn.textContent = "×";
      rmBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        segments = segments.filter((s) => s.id !== seg.id);
        if (activeSetupSegId === seg.id) activeSetupSegId = segments[0]?.id || null;
        renderSegmentSlots();
        updateGenerateBtn();
      });
      header.appendChild(rmBtn);
      slot.appendChild(header);
      const filesDiv = document.createElement("div");
      filesDiv.className = "seg-files";
      for (const f of seg.files) {
        const tag = document.createElement("span");
        tag.className = "seg-file-tag";
        tag.textContent = f.split("/").pop();
        tag.title = f;
        tag.addEventListener("click", (e) => {
          e.stopPropagation();
          seg.files = seg.files.filter((x) => x !== f);
          renderSegmentSlots();
          updateGenerateBtn();
        });
        filesDiv.appendChild(tag);
      }
      if (!seg.files.length) {
        const empty = document.createElement("span");
        empty.className = "hint";
        empty.textContent = "Drop focus files here";
        filesDiv.appendChild(empty);
      }
      slot.appendChild(filesDiv);
      container.appendChild(slot);
    }
  }

  function segmentIdFromName(name) {
    const m = String(name).match(/^(\d{2})/);
    return m ? m[1] : name;
  }

  async function saveFocusForSegments() {
    const status = document.getElementById("generate-status");
    status.textContent = "Saving focus files…";
    let ok = 0;
    for (const seg of segments) {
      const files = seg.files.length > 0 ? seg.files : Array.from(selectedFiles);
      const sid = segmentIdFromName(seg.name);
      const res = await fetch("/api/segments/" + encodeURIComponent(sid) + "/focus", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths: files, also_manim: true, yaml_generate: true }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        status.textContent = "Error saving " + sid + ": " + (data.error || res.status);
        return;
      }
      ok++;
    }
    status.textContent = "Saved focus files for " + ok + " segment(s) → hints + yaml-generate.";
  }

  document.getElementById("btn-save-focus").addEventListener("click", () => {
    saveFocusForSegments();
  });

  // ---- Generate narration ----
  document.getElementById("btn-generate").addEventListener("click", async () => {
    const btn = document.getElementById("btn-generate");
    const status = document.getElementById("generate-status");
    btn.disabled = true;
    status.textContent = "Saving focus + generating…";

    await saveFocusForSegments();

    const guidance = document.getElementById("guidance").value;
    const drafts = [];

    for (const seg of segments) {
      const files = seg.files.length > 0 ? seg.files : Array.from(selectedFiles);
      const sid = segmentIdFromName(seg.name);
      status.textContent = "Generating " + seg.name + "...";
      try {
        const res = await fetch("/api/generate-narration", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source_paths: files,
            guidance,
            segment_name: seg.name,
            segment_id: sid,
          }),
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        drafts.push({ name: seg.name, text: data.narration, path: data.path });
      } catch (err) {
        drafts.push({ name: seg.name, text: "ERROR: " + err.message, path: null });
      }
    }

    renderDrafts(drafts);
    status.textContent = "Done — " + drafts.length + " drafts generated.";
    btn.disabled = false;
  });

  function renderDrafts(drafts) {
    const container = document.getElementById("drafts-container");
    container.innerHTML = "";
    document.getElementById("draft-review").classList.remove("hidden");
    for (const d of drafts) {
      const card = document.createElement("div");
      card.className = "draft-card";
      card.innerHTML =
        "<h3>" + escHtml(d.name) + "</h3>" +
        '<textarea rows="10">' + escHtml(d.text) + "</textarea>" +
        '<div class="draft-actions">' +
        '<button class="btn btn-secondary btn-save-draft" data-name="' + escHtml(d.name) + '">Save edits</button>' +
        "</div>";
      container.appendChild(card);
    }
    container.querySelectorAll(".btn-save-draft").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const name = btn.dataset.name;
        const text = btn.closest(".draft-card").querySelector("textarea").value;
        await fetch("/api/narration/" + encodeURIComponent(name), {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        btn.textContent = "Saved!";
        setTimeout(() => { btn.textContent = "Save edits"; }, 1500);
      });
    });
  }

  document.getElementById("file-filter")?.addEventListener("input", (e) => {
    filterText = e.target.value || "";
    renderTreeFiltered();
  });
  document.getElementById("md-only")?.addEventListener("change", () => loadFileTree());

  // ================================================================
  // PRODUCTION VIEW
  // ================================================================

  async function loadProductionView() {
    const [segRes, stateRes] = await Promise.all([
      fetch("/api/segments"), fetch("/api/state"),
    ]);
    prodSegments = (await segRes.json()).segments || [];
    appState = (await stateRes.json()) || { segments: {} };
    renderSegmentList();
    if (activeSegmentId) loadSegment(activeSegmentId);
  }

  function renderSegmentList() {
    const list = document.getElementById("segment-list");
    list.innerHTML = "";
    let approved = 0;
    for (const seg of prodSegments) {
      const st = appState.segments?.[seg.id]?.status || seg.status || "draft";
      if (st === "approved") approved++;
      const li = document.createElement("li");
      li.dataset.id = seg.id;
      if (seg.id === activeSegmentId) li.classList.add("active");
      const badge = document.createElement("span");
      badge.className = "badge badge-" + st.replace(/\s+/g, "-");
      badge.textContent = st;
      li.appendChild(badge);
      li.appendChild(document.createTextNode(" " + seg.id));
      if (seg.focus_paths?.length) {
        const fc = document.createElement("span");
        fc.className = "focus-count";
        fc.textContent = seg.focus_paths.length + " files";
        li.appendChild(fc);
      }
      li.addEventListener("click", () => loadSegment(seg.id));
      list.appendChild(li);
    }
    const total = prodSegments.length;
    const pct = total > 0 ? (approved / total) * 100 : 0;
    document.getElementById("progress-bar").style.width = pct + "%";
    document.getElementById("progress-text").textContent = approved + " / " + total + " approved";
  }

  function renderFocusList() {
    const list = document.getElementById("focus-path-list");
    if (!list) return;
    list.innerHTML = "";
    if (!prodFocusPaths.length) {
      const li = document.createElement("li");
      li.className = "hint";
      li.textContent = "No focus files yet — add paths below.";
      list.appendChild(li);
      return;
    }
    for (const p of prodFocusPaths) {
      const li = document.createElement("li");
      li.className = "focus-path-item";
      const span = document.createElement("code");
      span.textContent = p;
      li.appendChild(span);
      const rm = document.createElement("button");
      rm.className = "btn-remove-seg";
      rm.textContent = "×";
      rm.title = "Remove";
      rm.addEventListener("click", () => {
        prodFocusPaths = prodFocusPaths.filter((x) => x !== p);
        renderFocusList();
      });
      li.appendChild(rm);
      list.appendChild(li);
    }
  }

  async function loadSegment(segId) {
    activeSegmentId = segId;
    document.getElementById("no-segment-selected").classList.add("hidden");
    document.getElementById("segment-review").classList.remove("hidden");
    document.getElementById("review-segment-title").textContent = "Segment " + segId;
    renderSegmentList();

    const seg = prodSegments.find((s) => s.id === segId);
    const st = appState.segments?.[segId]?.status || seg?.status || "draft";
    const badge = document.getElementById("review-status-badge");
    badge.className = "badge badge-" + st.replace(/\s+/g, "-");
    badge.textContent = st;

    try {
      const res = await fetch("/api/narration/" + encodeURIComponent(segId));
      const data = await res.json();
      document.getElementById("narration-editor").value = data.text || "";
    } catch { document.getElementById("narration-editor").value = ""; }

    try {
      const fres = await fetch("/api/segments/" + encodeURIComponent(segId) + "/focus");
      const fdata = await fres.json();
      prodFocusPaths = Array.isArray(fdata.paths) ? fdata.paths.slice() : (seg?.focus_paths || []).slice();
    } catch {
      prodFocusPaths = (seg?.focus_paths || []).slice();
    }
    renderFocusList();
    document.getElementById("focus-save-status").textContent = "";

    const audioEl = document.getElementById("audio-player");
    const audioStatus = document.getElementById("audio-status");
    if (seg?.audio_path) {
      audioEl.src = "/media/" + seg.audio_path;
      audioEl.classList.remove("hidden");
      audioStatus.textContent = seg.audio_path;
    } else {
      audioEl.removeAttribute("src");
      audioStatus.textContent = "No audio generated yet.";
    }

    const videoEl = document.getElementById("video-player");
    const videoStatus = document.getElementById("video-status");
    if (seg?.recording_path) {
      videoEl.src = "/media/" + seg.recording_path;
      videoStatus.textContent = seg.recording_path;
    } else {
      videoEl.removeAttribute("src");
      videoStatus.textContent = "No recording yet.";
    }

    document.getElementById("validation-results").innerHTML = '<p class="hint">Run validate to see results.</p>';
    renderAssetGraph(seg?.assets);
  }

  function renderAssetGraph(assets) {
    const list = document.getElementById("asset-step-list");
    if (!list) return;
    list.innerHTML = "";
    const steps = assets?.steps || [];
    if (!steps.length) {
      const li = document.createElement("li");
      li.className = "hint";
      li.textContent = "No asset status yet.";
      list.appendChild(li);
      return;
    }
    // Prefer one chip per logical stage (skip duplicate scene-spec when showing retime).
    const prefer = new Set(["tts", "timestamps", "scene-retime", "manim", "compose", "validate"]);
    for (const s of steps) {
      if (!prefer.has(s.step) && s.step !== "scene-spec") continue;
      if (s.step === "scene-spec") continue; // shown via retime chip; LLM is explicit button
      const li = document.createElement("li");
      const st = s.status === "n/a" ? "na" : s.status;
      li.className = "asset-chip " + st;
      li.title = s.detail || "";
      li.textContent = s.step + ": " + s.status;
      list.appendChild(li);
    }
    // Highlight redo buttons by data-step
    const byStep = Object.fromEntries(steps.map((s) => [s.step, s]));
    document.querySelectorAll(".video-actions [data-step]").forEach((btn) => {
      const step = btn.getAttribute("data-step");
      const info = byStep[step];
      btn.classList.remove("step-stale", "step-missing", "step-fresh");
      if (!info) return;
      if (info.status === "stale") btn.classList.add("step-stale");
      else if (info.status === "missing") btn.classList.add("step-missing");
      else if (info.status === "fresh") btn.classList.add("step-fresh");
      btn.title = (btn.title ? btn.title + " — " : "") + (info.detail || info.status);
    });
  }

  document.getElementById("btn-add-focus-path")?.addEventListener("click", () => {
    const inp = document.getElementById("focus-path-input");
    const p = (inp.value || "").trim();
    if (!p) return;
    if (!prodFocusPaths.includes(p)) prodFocusPaths.push(p);
    inp.value = "";
    renderFocusList();
  });

  document.getElementById("btn-save-prod-focus")?.addEventListener("click", async () => {
    if (!activeSegmentId) return;
    const status = document.getElementById("focus-save-status");
    status.textContent = "Saving…";
    const res = await fetch(
      "/api/segments/" + encodeURIComponent(activeSegmentId) + "/focus",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          paths: prodFocusPaths,
          also_manim: true,
          yaml_generate: true,
        }),
      }
    );
    const data = await res.json();
    if (!res.ok || data.error) {
      status.textContent = "Error: " + (data.error || res.status);
      return;
    }
    status.textContent = "Saved " + (data.paths?.length || 0) + " path(s)" +
      (data.hint_path ? " → " + data.hint_path : "");
    await loadProductionView();
  });

  // ---- Narration save / regenerate ----
  document.getElementById("btn-save-narration").addEventListener("click", async () => {
    if (!activeSegmentId) return;
    const text = document.getElementById("narration-editor").value;
    await fetch("/api/narration/" + encodeURIComponent(activeSegmentId), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
  });

  async function generateOrReviseNarration(mode) {
    if (!activeSegmentId) return;
    const notes = document.getElementById("revision-notes").value;
    const guidance = document.getElementById("guidance")?.value || "";
    const current = document.getElementById("narration-editor").value || "";
    const seg = prodSegments.find((s) => s.id === activeSegmentId);
    const regenBtn = document.getElementById("btn-regen-narration");
    const reviseBtn = document.getElementById("btn-revise-narration");
    const activeBtn = mode === "revise" ? reviseBtn : regenBtn;
    const idleLabel = mode === "revise" ? "Revise narration" : "Regenerate";
    if (mode === "revise" && !notes.trim()) {
      alert("Revision notes are required to revise in place.");
      return;
    }
    if (mode === "revise" && !current.trim()) {
      alert("Editor is empty — use Regenerate for a full draft, or paste a script first.");
      return;
    }
    activeBtn.textContent = mode === "revise" ? "Revising..." : "Regenerating...";
    regenBtn.disabled = true;
    reviseBtn.disabled = true;
    try {
      const body = {
        source_paths: prodFocusPaths.length ? prodFocusPaths : (seg?.focus_paths || []),
        guidance,
        segment_name: seg?.name || activeSegmentId,
        segment_id: activeSegmentId,
        revision_notes: notes,
        mode,
      };
      if (mode === "revise") body.current_narration = current;
      const res = await fetch("/api/generate-narration", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      if (data.narration) document.getElementById("narration-editor").value = data.narration;
    } catch (err) { alert("Error: " + err.message); }
    regenBtn.textContent = "Regenerate";
    reviseBtn.textContent = "Revise narration";
    regenBtn.disabled = false;
    reviseBtn.disabled = false;
  }

  document.getElementById("btn-regen-narration").addEventListener("click", () => generateOrReviseNarration("generate"));
  document.getElementById("btn-revise-narration")?.addEventListener("click", () => generateOrReviseNarration("revise"));

  // ---- Pipeline step buttons ----
  async function runStep(step) {
    if (!activeSegmentId) return;
    const res = await fetch("/api/run/" + step + "/" + encodeURIComponent(activeSegmentId), { method: "POST" });
    const data = await res.json();
    if (data.error) alert(step + " error: " + data.error);
    else await loadProductionView();
    return data;
  }

  async function runFrom(step) {
    if (!activeSegmentId) return null;
    const status = document.getElementById("rebuild-status");
    if (status) status.textContent = "Running from " + step + "…";
    const llm = step === "scene-spec";
    const res = await fetch(
      "/api/run-from/" + encodeURIComponent(step) + "/" + encodeURIComponent(activeSegmentId),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ llm_scene_spec: llm }),
      }
    );
    const data = await res.json();
    if (!res.ok || data.error) {
      if (status) status.textContent = "Failed at " + (data.failed_step || step);
      alert((data.failed_step || step) + " error: " + (data.error || res.status));
    } else {
      if (status) status.textContent = "Done (" + (data.ran || []).length + " steps)";
      const validateRun = (data.ran || []).find((r) => r.step === "validate" && r.report);
      if (validateRun?.report) {
        document.getElementById("validation-results").innerHTML =
          "<pre>" + escHtml(JSON.stringify(validateRun.report, null, 2)) + "</pre>";
      }
      await loadProductionView();
    }
    return data;
  }

  document.getElementById("btn-redo-tts")?.addEventListener("click", () => runStep("tts"));
  document.getElementById("btn-redo-tts-video")?.addEventListener("click", () => runStep("tts"));
  document.getElementById("btn-redo-timestamps")?.addEventListener("click", () => runStep("timestamps"));
  document.getElementById("btn-redo-scene-retime")?.addEventListener("click", () => runStep("scene-retime"));
  document.getElementById("btn-redo-scene-spec")?.addEventListener("click", () => runStep("scene-spec"));
  document.getElementById("btn-redo-manim").addEventListener("click", () => runStep("manim"));
  document.getElementById("btn-redo-compose").addEventListener("click", () => runStep("compose"));
  document.getElementById("btn-run-validate").addEventListener("click", async () => {
    const data = await runStep("validate");
    if (data?.report) {
      document.getElementById("validation-results").innerHTML =
        "<pre>" + escHtml(JSON.stringify(data.report, null, 2)) + "</pre>";
    }
  });

  document.getElementById("btn-rebuild-from")?.addEventListener("click", async () => {
    const sel = document.getElementById("rebuild-from-select");
    const step = sel?.value || "scene-retime";
    await runFrom(step);
  });

  document.getElementById("btn-redo-all").addEventListener("click", async () => {
    if (!activeSegmentId) return;
    await runFrom("tts");
  });

  // ---- Status buttons ----
  async function setSegmentStatus(status) {
    if (!activeSegmentId) return;
    if (!appState.segments) appState.segments = {};
    appState.segments[activeSegmentId] = appState.segments[activeSegmentId] || {};
    appState.segments[activeSegmentId].status = status;
    if (status === "needs-work") {
      const note = prompt("Rework note (optional):");
      if (note) appState.segments[activeSegmentId].revision_notes = note;
    }
    await fetch("/api/state", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(appState),
    });
    renderSegmentList();
    loadSegment(activeSegmentId);
    if (status === "approved") navigateSegment(1);
  }

  document.getElementById("btn-approve").addEventListener("click", () => setSegmentStatus("approved"));
  document.getElementById("btn-flag-rework").addEventListener("click", () => setSegmentStatus("needs-work"));

  // ---- Navigation ----
  function navigateSegment(dir) {
    if (!activeSegmentId || prodSegments.length === 0) return;
    const idx = prodSegments.findIndex((s) => s.id === activeSegmentId);
    const next = idx + dir;
    if (next >= 0 && next < prodSegments.length) loadSegment(prodSegments[next].id);
  }
  document.getElementById("btn-prev-seg").addEventListener("click", () => navigateSegment(-1));
  document.getElementById("btn-next-seg").addEventListener("click", () => navigateSegment(1));

  // ---- Helpers ----
  function escHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  // ---- Init ----
  loadFileTree();
})();
