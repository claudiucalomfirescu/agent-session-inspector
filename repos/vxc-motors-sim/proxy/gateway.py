"""LLM gateway: the budget and traffic rules every agent's LLM call goes through, applied inside the proxy.

Because all agents share one OpenRouter account, the limits are account-wide, so the proxy (the one
place every call passes) is where they are enforced:

  1. Rate limit   a sliding 60 s window per tier, below OpenRouter's 20 req/min for free models.
                  Callers wait for a slot instead of getting an error.
  2. Backoff      a per-minute 429 or a busy provider (502/503) is retried on the SAME free model,
                  with exponential backoff (honouring Retry-After).
  3. Fallback     only when the free DAILY cap (1,000 req/day, resets 00:00 UTC) is used up does the
                  request move to the paid fallback model (z-ai/glm-5.3-flash).
  4. Spend cap    the fallback stops once spend reaches GATEWAY_SPEND_CAP_USD (local ledger, and the
                  key's own usage from GET /key, whichever is higher).
  5. Cache        every successful answer is stored by a hash of the request, so a recorded workday
                  can be replayed without spending requests.

Configuration (environment variables, all optional):
  GATEWAY_PRIMARY_MODEL   free model agents ask for      (default: nvidia/nemotron-3.5-super-vl:free)
  GATEWAY_FALLBACK_MODEL  paid model after the daily cap (default: z-ai/glm-5.3-flash; "" disables)
  GATEWAY_FREE_RPM        free requests per minute       (default: 16, OpenRouter allows 20)
  GATEWAY_PAID_RPM        fallback requests per minute   (default: 30)
  GATEWAY_FREE_RESERVE    free requests per day to leave unused (default: 0)
  GATEWAY_SPEND_CAP_USD   hard cap on fallback spend     (default: 3.0)
  GATEWAY_PRICE_IN/OUT    fallback $ per 1M tokens, used when a reply carries no cost (0.15 / 0.50)
  GATEWAY_MAX_WAIT_S      longest a call waits for a rate-limit slot (default: 300)
  GATEWAY_RETRIES         retries on per-minute 429 / 502 / 503      (default: 4)
  GATEWAY_FREE_TIMEOUT_S  how long the free model may take; a timeout (or a 504 from the provider)
                          goes straight to the fallback model (default: 90; the free tier sometimes hangs)
  GATEWAY_BACKOFF_S       first backoff delay, doubled each retry    (default: 5)
  GATEWAY_KEY_REFRESH_S   how often GET /key is re-read              (default: 60)
  GATEWAY_CACHE           off | record (default) | replay (cache first, miss goes upstream)
                          | strict (cache only, miss is an error)
  GATEWAY_DB              SQLite file for cache and spend ledger (default: logs/gateway.db)
"""
import hashlib
import json
import os
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# Fields that do not change the answer, so they are left out of the cache key.
CACHE_IGNORED = {"user", "stream", "stream_options"}


def _env(name, default, cast=str):
    v = os.environ.get(name)
    return default if v is None or v == "" and cast is not str else cast(v)


@dataclass
class Config:
    primary_model: str = field(default_factory=lambda: _env("GATEWAY_PRIMARY_MODEL", "nvidia/nemotron-3.5-super-vl:free"))
    fallback_model: str = field(default_factory=lambda: _env("GATEWAY_FALLBACK_MODEL", "z-ai/glm-5.3-flash"))
    free_rpm: int = field(default_factory=lambda: _env("GATEWAY_FREE_RPM", 16, int))
    paid_rpm: int = field(default_factory=lambda: _env("GATEWAY_PAID_RPM", 30, int))
    free_reserve: int = field(default_factory=lambda: _env("GATEWAY_FREE_RESERVE", 0, int))
    spend_cap_usd: float = field(default_factory=lambda: _env("GATEWAY_SPEND_CAP_USD", 3.0, float))
    price_in: float = field(default_factory=lambda: _env("GATEWAY_PRICE_IN", 0.15, float))
    price_out: float = field(default_factory=lambda: _env("GATEWAY_PRICE_OUT", 0.50, float))
    max_wait_s: float = field(default_factory=lambda: _env("GATEWAY_MAX_WAIT_S", 300.0, float))
    retries: int = field(default_factory=lambda: _env("GATEWAY_RETRIES", 4, int))
    free_timeout_s: float = field(default_factory=lambda: _env("GATEWAY_FREE_TIMEOUT_S", 90.0, float))
    backoff_s: float = field(default_factory=lambda: _env("GATEWAY_BACKOFF_S", 5.0, float))
    key_refresh_s: float = field(default_factory=lambda: _env("GATEWAY_KEY_REFRESH_S", 60.0, float))
    cache: str = field(default_factory=lambda: _env("GATEWAY_CACHE", "record").lower())
    db_path: str = field(default_factory=lambda: _env("GATEWAY_DB", "logs/gateway.db"))


class RateLimiter:
    """At most `rpm` acquisitions in any 60 s window. acquire() blocks until a slot is free."""

    def __init__(self, rpm, window=60.0):
        self.rpm, self.window = rpm, window
        self.stamps = deque()
        self.lock = threading.Lock()

    def acquire(self, max_wait):
        deadline = time.monotonic() + max_wait
        while True:
            with self.lock:
                now = time.monotonic()
                while self.stamps and now - self.stamps[0] >= self.window:
                    self.stamps.popleft()
                if len(self.stamps) < self.rpm:
                    self.stamps.append(now)
                    return True
                wait = self.window - (now - self.stamps[0])
            if time.monotonic() + wait > deadline:
                return False
            time.sleep(min(wait, 1.0))

    def in_window(self):
        with self.lock:
            now = time.monotonic()
            return sum(1 for t in self.stamps if now - t < self.window)


def _for_fallback(req, model):
    """The request as sent to the fallback model. GLM cannot switch reasoning off (400 "Reasoning is
    mandatory"), so a caller's {"enabled": false} becomes the lowest effort instead."""
    out = {**req, "model": model}
    if isinstance(req.get("reasoning"), dict) and req["reasoning"].get("enabled") is False:
        out["reasoning"] = {"effort": "low"}
    return out


def _next_utc_midnight():
    now = datetime.now(timezone.utc)
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _error(status, message, kind):
    """An error body shaped like OpenRouter's, so OpenAI SDKs raise their usual exceptions."""
    return status, [("Content-Type", "application/json")], json.dumps(
        {"error": {"code": status, "message": message, "metadata": {"gateway": kind}}}).encode()


class Gateway:
    def __init__(self, upstream, key, cfg=None):
        self.upstream, self.key, self.cfg = upstream.rstrip("/"), key, cfg or Config()
        self.limiters = {"free": RateLimiter(self.cfg.free_rpm), "paid": RateLimiter(self.cfg.paid_rpm)}
        self.lock = threading.Lock()
        self.key_info, self.key_read_at, self.free_since_read = None, 0.0, 0
        self.free_exhausted_until = 0.0
        self._db = None

    # ---- storage: response cache and spend ledger -------------------------------------------
    def db(self):
        if self._db is None:
            os.makedirs(os.path.dirname(self.cfg.db_path) or ".", exist_ok=True)
            self._db = sqlite3.connect(self.cfg.db_path, check_same_thread=False)
            self._db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, ts TEXT, model TEXT, response BLOB)")
            self._db.execute("CREATE TABLE IF NOT EXISTS spend (id INTEGER PRIMARY KEY, ts TEXT, model TEXT, "
                             "prompt_tokens INTEGER, completion_tokens INTEGER, cost_usd REAL, estimated INTEGER)")
            self._db.commit()
        return self._db

    def _sql(self, query, args=(), fetch=False):
        with self.lock:
            cur = self.db().execute(query, args)
            if fetch:
                return cur.fetchall()
            self.db().commit()

    @staticmethod
    def cache_key(req):
        return hashlib.sha256(json.dumps({k: v for k, v in req.items() if k not in CACHE_IGNORED},
                                         sort_keys=True).encode()).hexdigest()

    def spent_local(self):
        return self._sql("SELECT COALESCE(SUM(cost_usd), 0) FROM spend", fetch=True)[0][0]

    # ---- account state from GET /key ---------------------------------------------------------
    def refresh_key_info(self, force=False):
        if not force and time.time() - self.key_read_at < self.cfg.key_refresh_s:
            return self.key_info
        try:
            req = urllib.request.Request(self.upstream + "/key", headers={"Authorization": f"Bearer {self.key}"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read()).get("data") or {}
            with self.lock:
                self.key_info, self.key_read_at, self.free_since_read = data, time.time(), 0
        except (OSError, ValueError):
            with self.lock:
                self.key_read_at = time.time()  # keep the last good reading; try again later
        return self.key_info

    def free_remaining(self):
        info = (self.refresh_key_info() or {}).get("free_model_daily_requests") or {}
        if "remaining" not in info:
            return None
        return info["remaining"] - self.free_since_read

    def free_exhausted(self):
        if time.time() < self.free_exhausted_until:
            return True
        remaining = self.free_remaining()
        return remaining is not None and remaining <= self.cfg.free_reserve

    def spent(self):
        key_usage = (self.key_info or {}).get("usage") or 0
        return max(self.spent_local(), key_usage)

    def status(self):
        info = self.refresh_key_info() or {}
        return {
            "primary_model": self.cfg.primary_model, "fallback_model": self.cfg.fallback_model,
            "free": {"daily": info.get("free_model_daily_requests"), "since_last_read": self.free_since_read,
                     "exhausted": self.free_exhausted(), "rpm_limit": self.cfg.free_rpm,
                     "in_last_minute": self.limiters["free"].in_window()},
            "paid": {"rpm_limit": self.cfg.paid_rpm, "in_last_minute": self.limiters["paid"].in_window(),
                     "spent_usd": round(self.spent(), 6), "spent_local_usd": round(self.spent_local(), 6),
                     "cap_usd": self.cfg.spend_cap_usd},
            "cache": {"mode": self.cfg.cache,
                      "entries": self._sql("SELECT COUNT(*) FROM cache", fetch=True)[0][0]},
        }

    # ---- one chat completion -------------------------------------------------------------------
    def _send(self, path, body, headers, timeout=300):
        req = urllib.request.Request(self.upstream + path, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.getheaders(), r.read()
        except urllib.error.HTTPError as e:
            return e.code, list(e.headers.items()), e.read()
        except (TimeoutError, socket.timeout):
            return _error(504, f"provider did not answer within {timeout:.0f}s", "timeout")
        except urllib.error.URLError as e:
            if isinstance(e.reason, (TimeoutError, socket.timeout)):
                return _error(504, f"provider did not answer within {timeout:.0f}s", "timeout")
            return _error(502, f"proxy could not reach provider: {type(e).__name__}", "unreachable")
        except OSError as e:
            return _error(502, f"proxy could not reach provider: {type(e).__name__}", "unreachable")

    @staticmethod
    def _classify(status, data):
        """'ok', 'daily_cap', 'retry' (per-minute 429 / busy provider) or 'fail'."""
        try:
            body = json.loads(data)
        except ValueError:
            body = None
        err = body.get("error") if isinstance(body, dict) else None
        if status == 200 and not err:
            return "ok"
        code = status if status != 200 else (err or {}).get("code")
        text = json.dumps(err).lower() if err else data[:2000].decode("utf-8", "replace").lower()
        if code == 429 and ("per-day" in text or "per day" in text or "daily" in text):
            return "daily_cap"
        if code in (429, 502, 503):
            return "retry"
        if code == 504:
            return "unavailable"   # timed out (ours or the provider's): a hanging model, not a busy one
        return "fail"

    def _record_cost(self, model, data):
        try:
            usage = json.loads(data).get("usage") or {}
        except ValueError:
            usage = {}
        p, c = usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0
        cost, estimated = usage.get("cost"), 0
        if cost is None:
            cost, estimated = (p * self.cfg.price_in + c * self.cfg.price_out) / 1e6, 1
        self._sql("INSERT INTO spend VALUES (NULL,?,?,?,?,?,?)",
                  (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), model, p, c, float(cost), estimated))
        return float(cost)

    def chat(self, path, body, headers):
        """Returns (status, headers, data, meta). meta = route, upstream_model, attempts, cost_usd."""
        meta = {"route": None, "upstream_model": None, "attempts": 0, "cost_usd": None}
        try:
            req = json.loads(body)
        except ValueError:
            req = None
        if not isinstance(req, dict) or "model" not in req:
            meta["route"] = "passthrough"
            return (*self._send(path, body, headers), meta)

        key = self.cache_key(req)
        if self.cfg.cache in ("replay", "strict"):
            hit = self._sql("SELECT response FROM cache WHERE key=?", (key,), fetch=True)
            if hit:
                meta.update(route="cache", upstream_model=req["model"])
                return 200, [("Content-Type", "application/json"), ("X-Gateway-Route", "cache")], hit[0][0], meta
            if self.cfg.cache == "strict":
                meta["route"] = "refused"
                return (*_error(504, "replay cache miss (GATEWAY_CACHE=strict)", "cache_miss"), meta)

        model = req["model"]
        is_free = model.endswith(":free")
        if is_free and self.free_exhausted():
            model, is_free = self.cfg.fallback_model, False
        delay = self.cfg.backoff_s
        while True:
            if not model:
                meta["route"] = "refused"
                return (*_error(429, "free daily cap reached and no fallback model configured", "daily_cap"), meta)
            if not is_free and self.spent() >= self.cfg.spend_cap_usd:
                meta["route"] = "refused"
                return (*_error(429, f"fallback spend cap ${self.cfg.spend_cap_usd:.2f} reached", "spend_cap"), meta)
            if not self.limiters["free" if is_free else "paid"].acquire(self.cfg.max_wait_s):
                meta["route"] = "refused"
                return (*_error(429, "gateway rate limit: no slot within GATEWAY_MAX_WAIT_S", "rate_limit"), meta)
            send = body if model == req["model"] else json.dumps(_for_fallback(req, model)).encode()
            status, resp_headers, data = self._send(path, send, headers,
                                                    self.cfg.free_timeout_s if is_free else 300)
            meta["attempts"] += 1
            meta["upstream_model"] = model
            verdict = self._classify(status, data)
            if verdict == "daily_cap" and is_free:
                with self.lock:
                    self.free_exhausted_until = _next_utc_midnight()
                model, is_free, delay = self.cfg.fallback_model, False, self.cfg.backoff_s
                continue
            if verdict == "unavailable" and is_free and self.cfg.fallback_model:
                model, is_free, delay = self.cfg.fallback_model, False, self.cfg.backoff_s   # hung or down: don't wait
                continue
            if verdict in ("retry", "unavailable") and meta["attempts"] <= self.cfg.retries:
                retry_after = dict((k.lower(), v) for k, v in resp_headers).get("retry-after")
                try:
                    wait = max(float(retry_after), delay) if retry_after else delay
                except ValueError:
                    wait = delay
                time.sleep(min(wait, 60))
                delay *= 2
                continue
            break

        if verdict == "ok":
            if is_free:
                with self.lock:
                    self.free_since_read += 1
            else:
                meta["cost_usd"] = self._record_cost(model, data)
            if self.cfg.cache != "off":
                self._sql("INSERT OR REPLACE INTO cache VALUES (?,?,?,?)",
                          (key, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), model, data))
        meta["route"] = "fallback" if model != req["model"] else ("primary" if is_free else "direct")
        resp_headers = [(k, v) for k, v in resp_headers if k.lower() != "x-gateway-route"]
        resp_headers.append(("X-Gateway-Route", meta["route"]))
        return status, resp_headers, data, meta
