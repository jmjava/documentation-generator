#!/usr/bin/env bash
set -euo pipefail

# Render PlantUML sources for the suite handbook to PNG.
# Uses the vendored JAR under third_party/plantuml/.
#
# Usage:
#   ./scripts/render-suite-diagrams.sh              # all *.puml in docs/suite/diagrams/
#   ./scripts/render-suite-diagrams.sh path/to/x.puml ...

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIAGRAM_DIR="${DIAGRAM_DIR:-$REPO_ROOT/docs/suite/diagrams}"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/docs/suite/generated}"

resolve_jar() {
  if [[ -n "${PLANTUML_JAR:-}" ]]; then
    printf '%s' "$PLANTUML_JAR"
    return
  fi
  local jar
  jar="$(ls -1 "$REPO_ROOT"/third_party/plantuml/plantuml-*.jar 2>/dev/null | sort -V | tail -1 || true)"
  if [[ -z "${jar}" || ! -f "${jar}" ]]; then
    echo "render-suite-diagrams: no JAR under $REPO_ROOT/third_party/plantuml/ (set PLANTUML_JAR)" >&2
    exit 1
  fi
  printf '%s' "${jar}"
}

PLANTUML_JAR_RESOLVED="$(resolve_jar)"
mkdir -p "${OUT_DIR}"

if ! command -v java >/dev/null 2>&1; then
  echo "render-suite-diagrams: java is required on PATH" >&2
  exit 1
fi

if ! command -v dot >/dev/null 2>&1; then
  echo "render-suite-diagrams: Graphviz 'dot' is required on PATH (PlantUML uses it for component diagrams)." >&2
  echo "  Ubuntu/Debian: sudo apt-get install -y graphviz" >&2
  echo "  macOS: brew install graphviz" >&2
  exit 1
fi

args=()
if [[ "$#" -eq 0 ]]; then
  mapfile -t args < <(find "${DIAGRAM_DIR}" -maxdepth 1 -name '*.puml' -type f | sort)
  if [[ "${#args[@]}" -eq 0 ]]; then
    echo "render-suite-diagrams: no .puml files in ${DIAGRAM_DIR}" >&2
    exit 1
  fi
else
  args=("$@")
fi

echo "Using: ${PLANTUML_JAR_RESOLVED}"
echo "Output: ${OUT_DIR}"

exec java ${JAVA_OPTS:-} -jar "${PLANTUML_JAR_RESOLVED}" -tpng -o "${OUT_DIR}" "${args[@]}"
