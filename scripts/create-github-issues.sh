#!/usr/bin/env bash
# Create GitHub issues from docs/issues/*.md (YAML frontmatter: title, labels)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ISSUES_DIR="$REPO_ROOT/docs/issues"
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    -h|--help)
      echo "Usage: $0 [--dry-run]"
      exit 0
      ;;
  esac
done

if ! command -v gh >/dev/null 2>&1; then
  echo "error: gh CLI not found. Install https://cli.github.com/" >&2
  exit 1
fi

LABELS=(schema docs ingestion ontology llm renderer ide testing)
for label in "${LABELS[@]}"; do
  if $DRY_RUN; then
    echo "[dry-run] ensure label: $label"
  else
    gh label create "$label" --force >/dev/null 2>&1 || true
  fi
done

extract_body() {
  local file="$1"
  awk 'BEGIN { in_fm=0; done=0 }
    /^---$/ { in_fm = !in_fm; if (!in_fm && done) next; if (!in_fm) done=1; next }
    in_fm { next }
    { print }' "$file"
}

parse_frontmatter() {
  local file="$1" key="$2"
  awk -v k="$key" '
    /^---$/ { fm++; next }
    fm == 1 && $0 ~ "^" k ":" {
      sub("^" k ":[[:space:]]*", "")
      print
      exit
    }
  ' "$file"
}

shopt -s nullglob
files=("$ISSUES_DIR"/[0-9][0-9]-*.md)
IFS=$'\n' files=($(sort <<<"${files[*]}"))
unset IFS

TMPDIR="${TMPDIR:-/tmp}"
for file in "${files[@]}"; do
  base="$(basename "$file" .md)"
  num="${base%%-*}"
  title_line="$(parse_frontmatter "$file" title)"
  labels_line="$(parse_frontmatter "$file" labels)"

  label_args=()
  if [[ -n "$labels_line" ]]; then
    IFS=',' read -r -a issue_labels <<<"$labels_line"
    for l in "${issue_labels[@]}"; do
      l="$(echo "$l" | xargs)"
      [[ -n "$l" ]] && label_args+=(--label "$l")
    done
  fi

  echo "=== #$num $title_line ==="
  if $DRY_RUN; then
    echo "  file:   $file"
    echo "  labels: $labels_line"
    continue
  fi

  body_file="$(mktemp "$TMPDIR/math-ide-issue.XXXXXX")"
  trap 'rm -f "$body_file"' RETURN
  extract_body "$file" >"$body_file"

  gh issue create \
    --title "$title_line" \
    --body-file "$body_file" \
    "${label_args[@]}"
done

echo "Done."
