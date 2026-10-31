# repos/ — the split

Five future standalone repositories, built here on branch `split` until they get their own GitHub
homes. Start with [MASTER_PLAN.md](MASTER_PLAN.md); the method all of them follow is
[prax-systems/](prax-systems/); the contracts between them are in [CONTRACTS.md](CONTRACTS.md);
how to publish them is [PUBLISHING.md](PUBLISHING.md).

Check them all:
```bash
for r in llm-proxy-log llm-proxy-firewall vxc-motors-sim llm-session-console prax-systems; do
  python3 prax-systems/tools/prax_check.py $r --level silver; done
```
