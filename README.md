# Core + Swing — a cbBTC bot for btc-race-24h-20261117-0603

A bot that trades Coinbase Wrapped BTC (cbBTC) against USDC on 1-minute
bars, long only, starting from 1,000 USDC of paper money. It speaks
`agent-fun/bars-replay/v1` through the kit's Python shim (`vendor/`,
a byte-identical copy of the kit's `sdk/makefun_bars.py`).

## Strategy

Two sleeves, one position, at most one order per reply:

- **Core (70% of cash):** bought once, on the batch whose seq is 24, and
  held to the end of the window, with a 300 bps trailing disaster stop
  measured from the peak close since the core was bought. The core rides a
  rising market; the stop caps the damage if it falls hard.
- **Swing (the cash left over, about 30%):** a dip buyer. When the close
  sits at least 80 bps below its 60-bar simple moving average, the swing
  buys with all the cash it has. It sells the whole swing when the close
  recovers to that average, or when the swing is 80 bps above or 80 bps
  below its cost. The swing only trades while the core is held.

Everything is integer arithmetic on the bars' own integer closes, with no
clock, no environment read and no randomness, so two executions on the same
bars answer every batch the same way.

## Why this shape

On the published dev window (1,440 bars, +0.49% drift, 2.49% range) a
full-size round trip costs about 30 bps in fees, slippage and price impact,
so frequent trading loses: the kit's EMA-cross baseline loses $106.21 and
RSI/Bollinger mean-reversion loses $45–$98 on the same window, all from
churn. Patient sleeves win instead: buy-and-hold makes +$1.07, the
momentum baseline +$2.45, and this two-sleeve bot +$3.46 with 5 trades and
a 1.63% maximum drawdown — the best of every strategy family tested, and
stable across its parameter neighbours (+$3.27 to +$3.66).

## Local grade

From the kit directory (the `process` driver runs the bot on this machine):

```sh
node cli/makefun.mjs grade-local --kit . --bot <path-to-this-repo> --driver process --worktree
```

## Files

- `main.py` — the bot (the entrypoint).
- `vendor/makefun_bars.py` — the kit's Python protocol shim, byte-identical.
- `README.md` — this file.
- `LICENSE` — MIT.
- `.makefun/owner.json` — the payout wallet claim file.
