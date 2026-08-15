/* Vue 3 scene-timing benchmark view (wizard + PyInstaller desktop shell). */
(function () {
  "use strict";

  function createBenchmarkApp() {
    return Vue.createApp({
      data() {
        return {
          loading: false,
          error: "",
          report: null,
          selected: null,
          caseFilter: "",
          caseIds: [],
          frozen: false,
        };
      },
      computed: {
        rows() {
          return (this.report && this.report.cases) || [];
        },
        controlSkips() {
          const row = this.rows.find((r) => r.role === "control");
          return row ? row.wait_skips : "—";
        },
      },
      methods: {
        deltaScore(row) {
          const prev = row.baseline && row.baseline.score;
          if (prev == null) return "—";
          const d = row.score - Number(prev);
          if (d === 0) return "0";
          return d > 0 ? "+" + d : String(d);
        },
        rowClass(row) {
          const classes = [];
          if (this.selected && this.selected.case_id === row.case_id) classes.push("selected");
          if (row.role === "control") classes.push("control");
          if (row.role === "quality" && row.defect_points > 0) classes.push("bad");
          if (row.role === "quality" && row.defect_points === 0) classes.push("ok");
          return classes.join(" ");
        },
        async run() {
          this.loading = true;
          this.error = "";
          const q = this.caseFilter ? "?case=" + encodeURIComponent(this.caseFilter) : "";
          try {
            const res = await fetch("/api/benchmark" + q);
            const data = await res.json();
            if (!res.ok || data.ok === false) {
              this.error = data.error || "Benchmark failed";
              this.report = null;
              return;
            }
            this.report = data;
            this.caseIds = data.case_ids || [];
            this.frozen = !!data.frozen;
            this.selected = (data.cases || [])[0] || null;
          } catch (err) {
            this.error = String(err.message || err);
          } finally {
            this.loading = false;
          }
        },
        async updateBaseline() {
          if (this.frozen) {
            this.error = "Baseline updates are disabled in a packaged desktop build.";
            return;
          }
          if (!confirm("Rewrite the committed baseline from this run? Review the Git diff.")) {
            return;
          }
          this.loading = true;
          this.error = "";
          try {
            const res = await fetch("/api/benchmark/update-baseline", { method: "POST" });
            const data = await res.json();
            if (!res.ok || data.ok === false) {
              this.error = data.error || "Update failed";
              return;
            }
            this.report = data;
            this.selected = (data.cases || [])[0] || null;
          } catch (err) {
            this.error = String(err.message || err);
          } finally {
            this.loading = false;
          }
        },
      },
      mounted() {
        const q = new URLSearchParams(window.location.search).get("case");
        if (q) this.caseFilter = q;
        this.run();
      },
    });
  }

  function mountBenchmark() {
    const el = document.getElementById("benchmark-app");
    if (!el || el.__vue_app__) return;
    if (typeof Vue === "undefined") return;
    const app = createBenchmarkApp();
    app.mount(el);
    el.__vue_app__ = app;
  }

  window.docgenMountBenchmark = mountBenchmark;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountBenchmark);
  } else {
    mountBenchmark();
  }
})();
