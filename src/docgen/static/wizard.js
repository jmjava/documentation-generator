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
  let appState = { segments: {} };

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
    const res = await fetch("/api/scan");
    const data = await res.json();
    fileTree = data.tree;
    flatFiles = data.files;
    renderTree(fileTree, document.getElementById("file-tree"));
  }

  function renderTree(nodes, container) {
    container.innerHTML = "";
    for (const node of nodes) {
      if (node.type === "dir") {
        const dirEl = document.createElement("div");
        dirEl.className = "tree-item";
        const label = document.createElement("div");
        label.className = "tree-dir";
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
        const lbl = document.createElement("label");
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.dataset.path = node.path;
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
    document.getElementById("btn-generate").disabled =
      selectedFiles.size === 0 || segments.length === 0;
  }

  // ---- Segment slots ----
  let segCounter = 0;

  document.getElementById("btn-add-segment").addEventListener("click", () => {
    segCounter++;
    const seg = { id: "seg-" + segCounter, name: String(segCounter).padStart(2, "0"), files: [] };
    segments.push(seg);
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
      segments.push({ id: "seg-" + segCounter, name: String(segCounter).padStart(2, "0") + "-" + name, files });
    }
    renderSegmentSlots();
    updateGenerateBtn();
  });

  function renderSegmentSlots() {
    const container = document.getElementById("segment-slots");
    container.innerHTML = "";
    for (const seg of segments) {
      const slot = document.createElement("div");
      slot.className = "segment-slot";
      slot.dataset.segId = seg.id;
      slot.addEventListener("dragover", (e) => e.preventDefault());
      slot.addEventListener("drop", (e) => {
        e.preventDefault();
        const path = e.dataTransfer.getData("text/plain");
        if (path && !seg.files.includes(path)) {
          seg.files.push(path);
          renderSegmentSlots();
        }
      });
      const header = document.createElement("div");
      header.className = "seg-header";
      const inp = document.createElement("input");
      inp.type = "text";
      inp.value = seg.name;
      inp.addEventListener("input", () => { seg.name = inp.value; });
      header.appendChild(inp);
      const rmBtn = document.createElement("button");
      rmBtn.className = "btn-remove-seg";
      rmBtn.textContent = "×";
      rmBtn.addEventListener("click", () => {
        segments = segments.filter((s) => s.id !== seg.id);
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
        tag.addEventListener("click", () => {
          seg.files = seg.files.filter((x) => x !== f);
          renderSegmentSlots();
        });
        filesDiv.appendChild(tag);
      }
      slot.appendChild(filesDiv);
      container.appendChild(slot);
    }
  }

  // ---- Generate narration ----
  document.getElementById("btn-generate").addEventListener("click", async () => {
    const btn = document.getElementById("btn-generate");
    const status = document.getElementById("generate-status");
    btn.disabled = true;
    status.textContent = "Generating...";

    const guidance = document.getElementById("guidance").value;
    const drafts = [];

    for (const seg of segments) {
      const files = seg.files.length > 0 ? seg.files : Array.from(selectedFiles);
      status.textContent = "Generating " + seg.name + "...";
      try {
        const res = await fetch("/api/generate-narration", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_paths: files, guidance, segment_name: seg.name }),
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
      li.addEventListener("click", () => loadSegment(seg.id));
      list.appendChild(li);
    }
    const total = prodSegments.length;
    const pct = total > 0 ? (approved / total) * 100 : 0;
    document.getElementById("progress-bar").style.width = pct + "%";
    document.getElementById("progress-text").textContent = approved + " / " + total + " approved";
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

    // Load narration
    try {
      const res = await fetch("/api/narration/" + encodeURIComponent(segId));
      const data = await res.json();
      document.getElementById("narration-editor").value = data.text || "";
    } catch { document.getElementById("narration-editor").value = ""; }

    // Audio
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

    // Video
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
  }

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

  document.getElementById("btn-regen-narration").addEventListener("click", async () => {
    if (!activeSegmentId) return;
    const notes = document.getElementById("revision-notes").value;
    const guidance = document.getElementById("guidance")?.value || "";
    const seg = prodSegments.find((s) => s.id === activeSegmentId);
    const btn = document.getElementById("btn-regen-narration");
    btn.textContent = "Regenerating...";
    btn.disabled = true;
    try {
      const res = await fetch("/api/generate-narration", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_paths: [],
          guidance,
          segment_name: activeSegmentId,
          revision_notes: notes,
        }),
      });
      const data = await res.json();
      if (data.narration) document.getElementById("narration-editor").value = data.narration;
    } catch (err) { alert("Error: " + err.message); }
    btn.textContent = "Regenerate narration";
    btn.disabled = false;
  });

  // ---- Pipeline step buttons ----
  async function runStep(step) {
    if (!activeSegmentId) return;
    const res = await fetch("/api/run/" + step + "/" + encodeURIComponent(activeSegmentId), { method: "POST" });
    const data = await res.json();
    if (data.error) alert(step + " error: " + data.error);
    else await loadProductionView();
    return data;
  }

  document.getElementById("btn-redo-tts").addEventListener("click", () => runStep("tts"));
  document.getElementById("btn-redo-vhs").addEventListener("click", () => runStep("vhs"));
  document.getElementById("btn-redo-manim").addEventListener("click", () => runStep("manim"));
  document.getElementById("btn-redo-compose").addEventListener("click", () => runStep("compose"));
  document.getElementById("btn-run-validate").addEventListener("click", async () => {
    const data = await runStep("validate");
    if (data?.report) {
      document.getElementById("validation-results").innerHTML =
        "<pre>" + escHtml(JSON.stringify(data.report, null, 2)) + "</pre>";
    }
  });

  document.getElementById("btn-redo-all").addEventListener("click", async () => {
    if (!activeSegmentId) return;
    for (const step of ["tts", "vhs", "manim", "compose", "validate"]) {
      await runStep(step);
    }
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
