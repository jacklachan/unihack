#!/usr/bin/env bash
# Push the current commit to the Hugging Face Space.
#
# Hugging Face reads its configuration from the frontmatter of README.md at the
# repository root, and the GitHub README is a different document. So this builds
# a throwaway `space` branch whose README.md is the Space one, pushes that, and
# puts you back on the branch you started from.
#
# Auth: username is your HF username; the password is an access token with WRITE
# permission from https://huggingface.co/settings/tokens -- not your password.
set -euo pipefail

SPACE_URL="${SPACE_URL:-https://huggingface.co/spaces/jacklachan/unihack}"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"

if [ -n "$(git status --porcelain)" ]; then
  echo "Working tree is dirty. Commit or stash first, so the Space matches a"
  echo "commit you can point at." >&2
  exit 1
fi

git remote get-url space >/dev/null 2>&1 || git remote add space "$SPACE_URL"
git remote set-url space "$SPACE_URL"

cleanup() { git checkout -q "$BRANCH"; }
trap cleanup EXIT

git checkout -q -B space
cp deploy/README_SPACE.md README.md
git add README.md
git commit -q -m "Space: Gradio front end over the CALIPER pipeline" || true

echo "Pushing to $SPACE_URL"
echo "  username: your HF username    password: an HF access token (write)"
git push --force space space:main

echo
echo "Pushed. Watch the build at $SPACE_URL  ->  Logs"
echo "Back on branch $BRANCH; the GitHub README is unchanged."
