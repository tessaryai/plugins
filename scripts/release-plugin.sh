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

set -euo pipefail

PLUGIN="${1:?plugin name required (e.g. evals)}"
VERSION="${2:?new version required (e.g. 0.2.0)}"
TAG="${PLUGIN}-v${VERSION}"

REPO_ROOT="$(git rev-parse --show-toplevel)"
PLUGIN_JSON="${REPO_ROOT}/plugins/${PLUGIN}/.claude-plugin/plugin.json"
MARKETPLACE_JSON="${REPO_ROOT}/.claude-plugin/marketplace.json"

[[ -f "$PLUGIN_JSON" ]]      || { echo "missing $PLUGIN_JSON" >&2; exit 1; }
[[ -f "$MARKETPLACE_JSON" ]] || { echo "missing $MARKETPLACE_JSON" >&2; exit 1; }

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "working tree not clean — commit or stash first" >&2
  exit 1
fi

if git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
  echo "tag ${TAG} already exists" >&2
  exit 1
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
git commit -m "Release ${TAG}"
git tag "$TAG" HEAD

echo
echo "Released ${TAG} at $(git rev-parse --short HEAD)."
echo "Push with: git push && git push origin ${TAG}"
