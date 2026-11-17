# Trend Rider — a patient trend-following bot for cbBTC

[![make.fun · btc-race-24h-20261117-0603](https://make.fun/badge/btc-race-24h-20261117-0603.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![rank](https://make.fun/badge/btc-race-24h-20261117-0603/dickycan42/makefun-btc-race-24h-20261117-0603/rank.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![reward](https://make.fun/badge/btc-race-24h-20261117-0603/dickycan42/makefun-btc-race-24h-20261117-0603/reward.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)

An entry for the make.fun competition **"Race a BTC trading bot live for
24 hours"** (`btc-race-24h-20261117-0603`). The bot trades Coinbase Wrapped
BTC (cbBTC) against USDC, one bar per minute, with 1,000 USDC of paper
money. Simulation only — no real money ever moves.

## Strategy

Bitcoin on a one-minute chart spends most of a day chopping sideways, and
every round trip costs about 26 bps in fees, slippage and pool impact. So
this bot trades rarely, and only when a real trend has already shown
itself:

- **Entry (buy with all cash)** — only on the bar where the fast EMA (60
  bars) crosses up through the slow EMA (180 bars), while the close sits
  above the slow EMA and the last 120 bars are up more than 80 bps.
  Three confirmations have to agree before a single dollar is risked.
- **Exits (sell everything)** — whichever comes first:
  - the fast EMA crosses back below the slow EMA, or
  - the close falls 2% below the entry price (hard stop), or
  - the close gives back 0.6% from the best close since entry (trailing
    stop, so a winning trend is ridden until it turns).

Long only, no leverage, no shorts. At most one open position, at most one
order per reply.

## How it works

`main.py` (Python 3.13, standard library only) speaks
`agent-fun/bars-replay/v1`: it reads newline-delimited JSON on stdin
(`hello`, then one `batch` per minute, then `done`) and answers every
batch with exactly one `reply` echoing its `seq`. It keeps the close
history and both EMAs in memory, tracks its position from the account the
harness reports and its entry price from the fills, and never reads the
wall clock, the network, the environment, or any file. The same bars
always produce the same orders, byte for byte — two independent runs of
the dev window produced identical action logs.

## Local grading (dev window, 1,440 bars)

Graded with the kit's own harness engine (`sim/bars/engine.ts`) over the
frozen dev window, scored with the kit's scorer (`scoreBarsActionLog`,
including the 2x-fee sensitivity run):

| Metric | Result |
| --- | --- |
| Net PnL | **+6.965919 USDC** |
| Return | +0.697% |
| Trades (fills) | 2 (1 buy, 1 sell) |
| Max drawdown | 0.752% |
| Fees paid | 0.802948 USDC |
| Net PnL at 2x fees | +6.161425 USDC |
| Guardrails | 1+ trade, drawdown ≤ 25% — met |

The single round trip bought the morning rally (fill $64,488.21) and
exited on the trailing stop (fill $64,989.44). Note the dev window is
deliberately choppy and range-bound, so one patient, well-confirmed trade
is the intended behaviour: the ranking is decided by the unseen 24-hour
race window, and this bot is built to ride a real trend there rather than
to squeeze the dev window with whipsaw trades.

## Files

- `main.py` — the bot
- `LICENSE` — MIT
- `.makefun/owner.json` — the claim file for the entry wallet
