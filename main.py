#!/usr/bin/env python3
"""Trend Rider for cbBTC: a patient, long-only trend-following bot.

Protocol: agent-fun/bars-replay/v1 (newline-delimited JSON on stdin/stdout).
Python 3.13, standard library only. Deterministic: the same bars always
produce the same orders, byte for byte. No network, no wall clock, no
files, no randomness.

Strategy in one paragraph
-------------------------
Bitcoin on a one-minute chart spends most of a day chopping sideways, and
every round trip costs about 26 bps in fees, slippage and pool impact, so
this bot trades rarely and only when a real trend has already shown itself.
It watches two exponential moving averages of the close (fast 60 bars,
slow 180 bars) plus the 120-bar return. It buys, with all of its cash,
only on the bar where the fast average crosses up through the slow one
while the price sits above the slow average and the last two hours are up
more than 80 bps. It sells everything when the fast average crosses back
down, when the price falls 2% below its entry, or when it gives back 0.6%
from the best close since entry (a trailing stop). That is the whole
strategy: one entry rule, three exit rules, no leverage, no shorts.
"""

import json
import sys

SYMBOL = "CBBTC"

# Strategy parameters (bars are one minute).
FAST_N = 60            # fast EMA length
SLOW_N = 180           # slow EMA length
MOM_LOOKBACK = 120     # momentum window, bars
MOM_MIN_BPS = 80       # momentum must exceed +80 bps over the window
HARD_STOP_BPS = 200    # sell if close falls 2% below entry
TRAIL_BPS = 60         # sell if close falls 0.6% below the peak since entry
MAX_SLIPPAGE_BPS = 300  # per-order slippage guard (fills move ~15 bps)

# The warm-up needed before any signal is meaningful: the slow EMA plus
# the momentum window.
MIN_BARS = SLOW_N + 2


class Bot:
    def __init__(self, hello):
        self.hello = hello
        self.caps = hello["caps"]
        self.fees = hello["fees"]
        self.warmup_bars = hello.get("warmup_bars", 0)
        self.min_notional = int(self.fees["min_notional_quote_units"])
        self.cash = int(hello["capital"]["quote_units"])
        self.qty = 0
        self.seq = -1
        self.closes = []          # closes, scaled ints, oldest first
        self.ema_fast = None
        self.ema_slow = None
        self.prev_fast = None
        self.prev_slow = None
        self.entry_price = None  # fill price of the open position (scaled int)
        self.peak = None         # best close since entry (scaled int)
        self.next_id = 1

    # -- indicator bookkeeping ------------------------------------------------

    def _update_indicators(self, close):
        if self.ema_fast is None:
            self.ema_fast = float(close)
            self.ema_slow = float(close)
        else:
            self.prev_fast = self.ema_fast
            self.prev_slow = self.ema_slow
            kf = 2.0 / (FAST_N + 1)
            ks = 2.0 / (SLOW_N + 1)
            self.ema_fast = close * kf + self.ema_fast * (1.0 - kf)
            self.ema_slow = close * ks + self.ema_slow * (1.0 - ks)
        self.closes.append(close)

    def _momentum_bps(self):
        """Return over the last MOM_LOOKBACK bars, in basis points (float)."""
        if len(self.closes) <= MOM_LOOKBACK:
            return None
        old = self.closes[-1 - MOM_LOOKBACK]
        new = self.closes[-1]
        if old <= 0:
            return None
        return (new - old) * 10000.0 / old

    # -- account / fills ------------------------------------------------------

    def _apply_account(self, account):
        self.cash = int(account["cash_quote_units"])
        held = 0
        for pos in account["positions"]:
            if pos["symbol"] == SYMBOL:
                held = int(pos["qty"])
        self.qty = held
        if held == 0:
            self.entry_price = None
            self.peak = None

    def _apply_fills(self, fills):
        for fill in fills:
            if fill["symbol"] != SYMBOL or fill["status"] != "filled":
                continue
            if fill["side"] == "buy":
                self.entry_price = int(fill["price"])
                self.peak = int(fill["price"])
            # Sells empty the whole position here, so nothing to track.

    # -- decisions ------------------------------------------------------------

    def _client_id(self, prefix):
        cid = "%s%d" % (prefix, self.next_id)
        self.next_id += 1
        return cid

    def decide(self):
        """Orders for this batch (possibly none)."""
        if self.seq < self.warmup_bars:
            return []
        if len(self.closes) < MIN_BARS:
            return []
        if self.prev_fast is None or self.prev_slow is None:
            return []
        close = self.closes[-1]
        mom = self._momentum_bps()
        if mom is None:
            return []

        if self.qty == 0:
            crossed_up = self.ema_fast > self.ema_slow and self.prev_fast <= self.prev_slow
            if (
                crossed_up
                and close > self.ema_slow
                and mom > MOM_MIN_BPS
                and self.cash >= self.min_notional
            ):
                return [{
                    "side": "buy",
                    "client_id": self._client_id("b"),
                    "symbol": SYMBOL,
                    "notional_quote_units": str(self.cash),
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }]
            return []

        # Holding: exit rules.
        crossed_down = self.ema_fast < self.ema_slow and self.prev_fast >= self.prev_slow
        stop_hit = self.entry_price is not None and close * 10000 < self.entry_price * (10000 - HARD_STOP_BPS)
        trail_hit = self.peak is not None and close * 10000 < self.peak * (10000 - TRAIL_BPS)
        if crossed_down or stop_hit or trail_hit:
            return [{
                "side": "sell",
                "client_id": self._client_id("s"),
                "symbol": SYMBOL,
                "qty": str(self.qty),
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
            }]
        return []

    # -- wire -----------------------------------------------------------------

    def on_batch(self, batch):
        self.seq = batch["seq"]
        got_bar = False
        for bar in batch["bars"]:
            if bar["symbol"] == SYMBOL:
                self._update_indicators(int(bar["c"]))
                got_bar = True
        self._apply_fills(batch["fills"])
        self._apply_account(batch["account"])
        # Track the running peak with this bar's close while holding.
        if self.qty > 0 and self.closes:
            close = self.closes[-1]
            if self.peak is None or close > self.peak:
                self.peak = close
        # A minute with no bar for our symbol carries no new price: never
        # decide on stale closes (the fill would land on a bar we never saw).
        orders = self.decide() if got_bar else []
        return {"type": "reply", "seq": batch["seq"], "orders": orders}


def main():
    bot = None
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        kind = msg.get("type")
        if kind == "hello":
            if msg.get("protocol") != "agent-fun/bars-replay/v1":
                raise SystemExit("unsupported protocol: %r" % (msg.get("protocol"),))
            bot = Bot(msg)
        elif kind == "batch":
            if bot is None:
                raise SystemExit("batch before hello")
            reply = bot.on_batch(msg)
            out.write(json.dumps(reply, separators=(",", ":")) + "\n")
            out.flush()
        elif kind == "done":
            return 0
        else:
            raise SystemExit("unknown message type: %r" % (kind,))
    raise SystemExit("input ended before done")


if __name__ == "__main__":
    main()
