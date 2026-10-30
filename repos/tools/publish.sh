#!/usr/bin/env bash
# Publish one folder under repos/ as its own GitHub repository.
#
#   repos/tools/publish.sh <name> [--dry-run] [--force]
#
# Takes repos/<name> from branch `split` (with the folder's own history, via
# git subtree split), rewrites links that point outside the folder to the
# published sibling repos, runs the Prax Systems silver check, and pushes the
# result to the `main` branch of https://github.com/$OWNER/<name>.
#
# Env: OWNER (default claudiucalomfirescu), REMOTE_BASE (default
# https://github.com/$OWNER), SOURCE (default origin/split).
set -euo pipefail

name=${1:?usage: publish.sh <name> [--dry-run] [--force]}
shift
dry=0; force=0
for a in "$@"; do
  case $a in --dry-run) dry=1 ;; --force) force=1 ;; *) echo "unknown flag $a" >&2; exit 2 ;; esac
done
OWNER=${OWNER:-claudiucalomfirescu}
REMOTE_BASE=${REMOTE_BASE:-https://github.com/$OWNER}
SOURCE=${SOURCE:-origin/split}
GH="https://github.com/$OWNER"

root=$(git rev-parse --show-toplevel)
cd "$root"
[ "$SOURCE" = origin/split ] && git fetch -q origin split
git cat-file -e "$SOURCE:repos/$name" 2>/dev/null || { echo "no repos/$name on $SOURCE" >&2; exit 1; }

branch="publish/$name"
git branch -D "$branch" >/dev/null 2>&1 || true
echo "→ extracting history of repos/$name"
git subtree split --prefix="repos/$name" "$SOURCE" -b "$branch" >/dev/null

work=$(mktemp -d)
trap 'git worktree remove --force "$work" >/dev/null 2>&1 || true' EXIT
git worktree add -q "$work" "$branch"

echo "→ rewriting cross-repo links for $GH"
(
  cd "$work"
  # The ecosystem docs travel with prax-systems.
  if [ "$name" = prax-systems ]; then
    mkdir -p ecosystem
    for f in MASTER_PLAN.md CONTRACTS.md PUBLISHING.md MORNING_REPORT.md; do
      git -C "$root" show "$SOURCE:repos/$f" > "ecosystem/$f" 2>/dev/null || rm -f "ecosystem/$f"
    done
  fi
  files=$(grep -rlE '\.\./(prax-systems|llm-proxy-log|llm-proxy-firewall|vxc-motors-sim|llm-session-console|MASTER_PLAN\.md|CONTRACTS\.md|PUBLISHING\.md|MORNING_REPORT\.md)' \
          --include='*.md' --include='*.yaml' --include='*.html' . || true)
  for f in $files; do
    # Only link targets (markdown ](…) and href="…"); commands in code blocks are left alone.
    GH="$GH" perl -pi -e '
      s#(\]\(|href=")(?:\.\./)+(prax-systems|llm-proxy-log|llm-proxy-firewall|vxc-motors-sim|llm-session-console)/#$1$ENV{GH}/$2/blob/main/#g;
      s#(\]\(|href=")(?:\.\./)+(MASTER_PLAN|CONTRACTS|PUBLISHING|MORNING_REPORT)\.md#$1$ENV{GH}/prax-systems/blob/main/ecosystem/$2.md#g;
    ' "$f"
  done
  # Inside prax-systems/ecosystem the docs point at siblings relative to repos/.
  if [ -d ecosystem ]; then
    GH="$GH" perl -pi -e 's#\]\((prax-systems|llm-proxy-log|llm-proxy-firewall|vxc-motors-sim|llm-session-console)/#]($ENV{GH}/$1/blob/main/#g' ecosystem/*.md
  fi
  git add -A
  git -c user.name="${GIT_AUTHOR_NAME:-publish.sh}" -c user.email="${GIT_AUTHOR_EMAIL:-publish@localhost}" \
    commit -qm "Prepare $name for standalone publication (links to sibling repos)" || true
)

echo "→ Prax Systems silver check"
checker="$work/tools/prax_check.py"
[ -f "$checker" ] || checker="$root/repos/prax-systems/tools/prax_check.py"
if ! python3 "$checker" "$work" --level silver; then
  [ $force = 1 ] || { echo "silver check failed; fix it or pass --force" >&2; exit 1; }
fi

if [ $dry = 1 ]; then
  echo "dry run: would push $branch → $REMOTE_BASE/$name (main)"
  git -C "$work" log --oneline | head -5
  exit 0
fi
echo "→ pushing to $REMOTE_BASE/$name main"
git push "$REMOTE_BASE/$name.git" "$branch:main"
echo "done: $GH/$name"
