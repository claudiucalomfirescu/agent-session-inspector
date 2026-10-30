# Publishing the five repos

Everything lives in `repos/<name>/` on branch `split` of `agent-session-inspector` until you create
the GitHub repositories. Each folder becomes its own repository **with its own history** (only the
commits that touched that folder), using `git subtree split`. The script
[`tools/publish.sh`](tools/publish.sh) does it in one command per repo and also:

- rewrites links that point at sibling folders (`../prax-systems/…`, `../MASTER_PLAN.md`) to the
  published GitHub URLs;
- copies the ecosystem docs (MASTER_PLAN, CONTRACTS, PUBLISHING, MORNING_REPORT) into
  `prax-systems/ecosystem/`, so they stay reachable after the split;
- refuses to publish a repo that fails the Prax Systems **silver** check (override with `--force`).

## Step 1 · Create five empty repositories on GitHub (you, 3 minutes)

On <https://github.com/new>, once per name, under the account that should own them:

| Repository | Description (paste) |
|---|---|
| `prax-systems` | A method and templates for building multi-part systems that ship their goal, spec and rebuild prompts with the code. |
| `llm-proxy-log` | An OpenAI-compatible LLM proxy that logs every exchange to SQLite, with a small dashboard and a recorded demo team. |
| `llm-proxy-firewall` | llm-proxy-log plus a session firewall that flags info/warning/block and answers as the LLM when it blocks. |
| `vxc-motors-sim` | A simulated BMW dealership whose 12 employees are LLM agents and whose enterprise apps are tools backed by small real local services. |
| `llm-session-console` | A local web console that drills down from all LLM traffic to one user, day, session, message and firewall event, with a 3D galaxy view. |

Settings for each: **Public** (or Private first, if you want to review on GitHub), and leave
**"Add a README", ".gitignore" and "license" all unticked**, so the repository is completely empty.

## Step 2 · Push (pick one)

### Option A · Let Claude push (easiest)
Tell the project chat "the five repos are created under `<owner>`". Claude adds them to the
session and runs the script below from the cloud workspace. You only need to have created them.

### Option B · Push from your computer
Needs git, bash and perl (macOS, Linux, or Git Bash on Windows) and Python 3 for the check.

```bash
git clone https://github.com/claudiucalomfirescu/agent-session-inspector.git
cd agent-session-inspector
git checkout split
export OWNER=claudiucalomfirescu          # the account or organisation that owns the new repos

# Optional: see what would be pushed, without pushing
repos/tools/publish.sh prax-systems --dry-run

# Publish (methodology first, so the others' links resolve)
for r in prax-systems llm-proxy-log llm-proxy-firewall vxc-motors-sim llm-session-console; do
  repos/tools/publish.sh "$r"
done
```

Each run prints `done: https://github.com/$OWNER/<name>`.

### What the script does, by hand (for one repo)
```bash
git fetch origin split
git subtree split --prefix=repos/llm-proxy-log origin/split -b publish/llm-proxy-log
git worktree add /tmp/pub publish/llm-proxy-log
#   … edit links in /tmp/pub, commit …
python3 /tmp/pub/tools/prax_check.py /tmp/pub --level silver
git push https://github.com/$OWNER/llm-proxy-log.git publish/llm-proxy-log:main
git worktree remove /tmp/pub
```

## Step 3 · After the first push (per repo, 2 minutes)

1. **About** box (gear icon on the repo page): paste the description, add the explainer artifact
   link as the website, topics `llm`, `agents`, `proxy`, `prax-systems`.
2. Check the README renders and the quickstart works from a fresh clone:
   ```bash
   git clone https://github.com/$OWNER/llm-proxy-log && cd llm-proxy-log
   pip install -r requirements.txt && python3 -m unittest discover -s tests
   ```
3. Optional: enable GitHub Pages (Settings → Pages → branch `main`, folder `/`) so
   `explainers/index.html` is served at `https://$OWNER.github.io/<name>/explainers/`.

## Updating later

Keep working on `split` (or `main` once merged) and re-run `repos/tools/publish.sh <name>`. Subtree
split is deterministic, so the folder's history is the same each time and new commits are added on
top; the link-rewrite commit is regenerated. If you instead start working **directly** in a
published repo, stop using the script for that repo (it would overwrite with a non-fast-forward
error, which is the signal) and treat the published repo as the source from then on.

## If something goes wrong

| Symptom | Fix |
|---|---|
| `silver check failed` | Read the ✗ lines; fix the folder on `split`, or `--force` to publish anyway |
| `! [rejected] … (fetch first)` | The GitHub repo is not empty (README/licence was ticked). Delete and recreate it empty, or push with `git push --force …` once |
| `Permission denied` / 403 | The account in `OWNER` is not yours, or git is signed in as another account (`gh auth login`, or a personal access token) |
| `no repos/<name> on origin/split` | The name is misspelt or that folder has not been merged into `split` yet |
