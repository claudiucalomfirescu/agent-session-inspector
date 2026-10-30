# people/ · who each VXC Motors employee is

Every employee agent carries an **intrinsic context**: four short Markdown files that are loaded into its
system prompt before any task. They sit on top of the facts in [`company/personas/<id>.md`](../company/personas/)
(name, role, department, reporting line, systems, risk profile), which stay the source of truth for facts.

| File | What it is | Visible to colleagues? |
|---|---|---|
| `resume.md` | Prior history: profile, experience with achievements, education, skills, what a former boss would say | yes, it can come up naturally |
| `job.md` | The job at VXC Motors: purpose, responsibilities, decision rights, KPIs, who they work with, systems | yes |
| `persona.md` | How they behave in public at work: tone, habits, how they write, how they act in a group | yes, it *is* their public face |
| `soul.md` | Values, what they are looking for, when they are happy, what worries them, a private truth (and, for the three monitored risk personas, the inner tension behind the risk) | no: it shapes reactions, the agent does not recite it |

```python
from people.load import load_identity, list_people
system = load_identity("elena-popescu") + "\n\n" + task_prompt
```

`load_identity()` returns one block: a short preamble ("You are Elena Popescu, Aftersales (Service)
Manager…; follow your persona, keep your soul private, stay in character"), then PERSONA, SOUL, JOB and
RESUME, in that order (most behaviour-shaping first). About 1,000 tokens per person. Stdlib only.

`python3 -m people.load` prints the size of each identity block.

## The twelve

| id | Name | Role | One line from the soul |
|---|---|---|---|
| victor-hale | Victor Hale | General Manager | Reputation is the asset; quietly anxious about the bank covenant |
| maria-santos | Maria Santos | Receptionist & Office Coordinator | Dignity of the welcome; wants to run customer experience |
| priya-nair | Priya Nair | Finance & Admin Officer | Truth you can trace; enjoys the detective work |
| daniel-reed | Daniel Reed | Sales Manager | Winning the right way; wants to be a GM by 50 |
| sofia-marin | Sofia Marin | Sales Consultant (BMW i & fleet) | Honesty over the sale; has been approached by another group |
| tom-becker | Tom Becker | Sales Consultant (M & used) | Being the best; behind on rent ⚠ discount-fraud temptation |
| elena-popescu | Elena Popescu | Aftersales Manager | Craft and truth; unsure she wants to leave the cars for the GM job |
| james-okafor | James Okafor | Senior Service Advisor | Being needed, loyalty to mates ⚠ customer-data temptation |
| nina-kovac | Nina Kovač | Service Advisor (warranty) | Getting it right; has automation ideas she hasn't shared |
| lucas-meyer | Lucas Meyer | Master Technician | Do it properly or don't; prouder of Aisha than he says |
| aisha-rahman | Aisha Rahman | EV & Electrical Technician | Safety and understanding why; dreams of her own diagnostic tool |
| mark-doyle | Mark Doyle | Parts & Supply Chain | Dependable, people over systems ⚠ password-sharing temptation |

The off-site meeting ([`../offsite/`](../offsite/)) is the first thing that runs on these identities.
