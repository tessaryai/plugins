#!/usr/bin/env bash
# Release a plugin: bump version, update marketplace ref, commit, tag.
#
# Usage:   scripts/release-plugin.sh <plugin-name> <new-version>
# Example: scripts/release-plugin.sh evals 0.2.0
#
# Produces ONE commit containing:
#   - plugins/<name>/.claude-plugin/plugin.json   version -> <new-version>
#   - .claude-plugin/marketplace.json source.ref -> <name>-v<new-version>
# Then tags that commit as <name>-v<new-version>.
#
# The tagged commit is fully self-consistent: marketplace.json points to a tag
# that names this very commit. No "marketplace ahead of tag" drift.
#
# gtm editions: plugins/gtm is generated from plugins/gtm-pro by
# scripts/build-gtm-edition.py and inherits its version. Release gtm-pro; the
# same commit regenerates plugins/gtm, sets the gtm ref to gtm-v<new-version>,
# and tags both. Releasing gtm on its own is refused.

set -euo pipefail

PLUGIN="${1:?plugin name required (e.g. evals)}"
VERSION="${2:?new version required (e.g. 0.2.0)}"
TAG="${PLUGIN}-v${VERSION}"

if [[ "$PLUGIN" == "gtm" ]]; then
  echo "plugins/gtm is generated from plugins/gtm-pro; run: scripts/release-plugin.sh gtm-pro ${VERSION}" >&2
  exit 1
fi
EDITION_TAG=""
if [[ "$PLUGIN" == "gtm-pro" ]]; then
  EDITION_TAG="gtm-v${VERSION}"
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
PLUGIN_JSON="${REPO_ROOT}/plugins/${PLUGIN}/.claude-plugin/plugin.json"
MARKETPLACE_JSON="${REPO_ROOT}/.claude-plugin/marketplace.json"

[[ -f "$PLUGIN_JSON" ]]      || { echo "missing $PLUGIN_JSON" >&2; exit 1; }
[[ -f "$MARKETPLACE_JSON" ]] || { echo "missing $MARKETPLACE_JSON" >&2; exit 1; }

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "working tree not clean — commit or stash first" >&2
  exit 1
fi

for t in "$TAG" $EDITION_TAG; do
  if git rev-parse -q --verify "refs/tags/${t}" >/dev/null; then
    echo "tag ${t} already exists" >&2
    exit 1
  fi
done

if [[ -n "$EDITION_TAG" ]]; then
  EDITION_CHANGELOG="${REPO_ROOT}/scripts/gtm-edition-overlay/files/CHANGELOG.md"
  if ! grep -q "TL;DR (v${VERSION}" "$EDITION_CHANGELOG"; then
    echo "add a 'TL;DR (v${VERSION}' block to ${EDITION_CHANGELOG} (the gtm edition changelog) first" >&2
    exit 1
  fi
fi

tmp_plugin="$(mktemp)"
jq --arg v "$VERSION" '.version = $v' "$PLUGIN_JSON" > "$tmp_plugin"
mv "$tmp_plugin" "$PLUGIN_JSON"

tmp_market="$(mktemp)"
jq --arg name "$PLUGIN" --arg tag "$TAG" '
  .plugins |= map(if .name == $name then .source.ref = $tag else . end)
' "$MARKETPLACE_JSON" > "$tmp_market"
mv "$tmp_market" "$MARKETPLACE_JSON"

git add "$PLUGIN_JSON" "$MARKETPLACE_JSON"

if [[ -n "$EDITION_TAG" ]]; then
  python3 "${REPO_ROOT}/scripts/build-gtm-edition.py"
  python3 "${REPO_ROOT}/scripts/check-plugin-files.py" "${REPO_ROOT}/plugins/gtm"
  tmp_market="$(mktemp)"
  jq --arg tag "$EDITION_TAG" '
    .plugins |= map(if .name == "gtm" then .source.ref = $tag else . end)
  ' "$MARKETPLACE_JSON" > "$tmp_market"
  mv "$tmp_market" "$MARKETPLACE_JSON"
  git add -A "${REPO_ROOT}/plugins/gtm" "$MARKETPLACE_JSON"
fi

git commit -m "Release ${TAG}${EDITION_TAG:+ and ${EDITION_TAG}}"
git tag "$TAG" HEAD
if [[ -n "$EDITION_TAG" ]]; then
  git tag "$EDITION_TAG" HEAD
fi

echo
echo "Released ${TAG}${EDITION_TAG:+ and ${EDITION_TAG}} at $(git rev-parse --short HEAD)."
echo "Push with: git push && git push origin ${TAG}${EDITION_TAG:+ ${EDITION_TAG}}"
