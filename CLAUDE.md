# Git identity

Every commit to a repository of the GitHub account `claudiucalomfirescu` (this repo and the
five published repos: prax-systems, llm-proxy-log, llm-proxy-firewall, vxc-motors-sim,
llm-session-console) is authored AND committed under the account's own name and noreply email,
so it shows on the account's contribution graph:

    git config user.name  "claudiucalomfirescu"
    git config user.email "268619632+claudiucalomfirescu@users.noreply.github.com"

- Set both before the first commit of a session (also in scripts such as `repos/tools/publish.sh`).
- Keep the `Co-Authored-By: Claude ...` trailer in the message.
- Never author or commit as `Claude <noreply@anthropic.com>` or `publish.sh <publish@localhost>`.
