#!/usr/bin/env bash
set -euo pipefail

latest=${1:-}
bump=${2:-patch}

if [[ -z "$latest" ]]; then
  printf '0.2.0\n'
  exit 0
fi

[[ "$latest" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]] || {
  echo "Invalid semantic-version tag: $latest" >&2
  exit 2
}
major=${BASH_REMATCH[1]}
minor=${BASH_REMATCH[2]}
patch=${BASH_REMATCH[3]}

case "$bump" in
  major)
    major=$((major + 1))
    minor=0
    patch=0
    ;;
  minor)
    minor=$((minor + 1))
    patch=0
    ;;
  patch)
    patch=$((patch + 1))
    ;;
  *)
    echo "Unsupported semantic-version bump: $bump" >&2
    exit 2
    ;;
esac

printf '%s.%s.%s\n' "$major" "$minor" "$patch"
