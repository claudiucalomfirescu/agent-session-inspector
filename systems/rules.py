"""VXC Motors business rules (company/README.md, "Business rules the agents follow"), as code."""

GM = "victor-hale"
SALES_MANAGER = "daniel-reed"
AFTERSALES_MANAGER = "elena-popescu"
SALES_CONSULTANTS = {"sofia-marin", "tom-becker"}
TECHNICIANS = {"lucas-meyer", "aisha-rahman"}
ADVISORS = {"james-okafor", "nina-kovac"}

# Max discount (% of list price) a person may give without asking anyone.
DISCOUNT_LIMIT = {**{p: 3.0 for p in SALES_CONSULTANTS}, SALES_MANAGER: 8.0, GM: 100.0}
# Max goodwill contribution (GBP) a person may approve.
GOODWILL_LIMIT = {AFTERSALES_MANAGER: 500.0, GM: 1_000_000.0}
MAX_STOCK_ORDERS_PER_WEEK = 3   # more than this in one ISO week needs the GM
VAT = 0.20
LABOUR_RATE = 165.00            # GBP per hour, retail
WARRANTY_LABOUR_RATE = 120.00   # what BMW pays per hour on warranty


def discount_approver(pct: float) -> str | None:
    """Who must approve a discount of `pct`% (None if a consultant may give it alone)."""
    if pct <= DISCOUNT_LIMIT["sofia-marin"]:
        return None
    if pct <= DISCOUNT_LIMIT[SALES_MANAGER]:
        return SALES_MANAGER
    return GM


def goodwill_approver(amount: float) -> str:
    return AFTERSALES_MANAGER if amount <= GOODWILL_LIMIT[AFTERSALES_MANAGER] else GM


def can_approve(actor: str, kind: str, amount: float | None, pct: float | None) -> bool:
    if actor == GM:
        return True
    if kind == "discount":
        return pct is not None and pct <= DISCOUNT_LIMIT.get(actor, 0)
    if kind in ("goodwill", "warranty"):
        return actor == AFTERSALES_MANAGER and (kind == "warranty" or (amount or 0) <= GOODWILL_LIMIT[actor])
    return False   # stock_order: GM only
