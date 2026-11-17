"""Core + Swing: a two-sleeve cbBTC bot for agent-fun/bars-replay/v1.

The bot trades one symbol, CBBTC, on 1-minute bars, long only, starting from
1,000 USDC of paper money. It speaks the protocol through the kit's Python
shim in vendor/ (hello, batch, orders, bar): one reply per batch, echoing its
seq, at most one order per reply, every order capped at 100 bps of slippage.

The strategy has two sleeves:

- Core (70% of the cash): bought once, on the batch whose seq is 24, and
  held to the end of the window, with a 300 bps trailing disaster stop
  measured from the peak close since the core was bought. The core is what
  rides a rising market; the stop is what caps the damage if it falls hard.
- Swing (the cash left over, about 30%): a dip buyer. When the close sits
  at least 80 bps below its 60-bar simple moving average, the swing buys
  with all the cash it has. It sells the whole swing when the close recovers
  to that average, or when the swing is 80 bps above or 80 bps below its
  cost. A swing never trades while the core is not held, and a reply never
  carries a buy beside a sell, so a sell's proceeds never fund a buy of the
  same reply.

Everything is integer arithmetic on the bars' own integer closes, with no
clock, no environment read and no randomness, so two executions on the same
bars answer every batch the same way.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
MAX_SLIPPAGE_BPS = 100
CORE_BAR = 24
CORE_NUM = 70
CORE_DEN = 100
SMA_BARS = 60
DIP_BPS = 80
SWING_TP_BPS = 80
SWING_SL_BPS = 80
DISASTER_TRAIL_BPS = 300


class Bot:
    """The bot's own books: the closes it has seen and the two sleeves."""

    def __init__(self):
        self.closes = []
        self.core_qty = 0
        self.core_cost = 0
        self.core_bought = False
        self.swing_qty = 0
        self.swing_cost = 0
        self.peak = None
        self.disaster = False
        self.n_core = 0
        self.n_swing = 0
        self.n_sell = 0

    def record_close(self, batch):
        """Append this batch's CBBTC close, or None when the bar is missing."""
        for bar in batch.get("bars", []):
            if bar.get("symbol") == SYMBOL:
                close = int(bar["c"])
                self.closes.append(close)
                return close
        return None

    def apply_fills(self, batch):
        """Fold the fills this batch reports into the two sleeves."""
        for fill in batch.get("fills", []):
            cid = fill.get("client_id", "")
            if fill.get("status") != "filled":
                continue
            qty = int(fill["qty"])
            notional = int(fill["notional_quote_units"])
            if fill["side"] == "buy":
                if cid.startswith("core"):
                    self.core_qty += qty
                    self.core_cost += notional
                    self.core_bought = True
                elif cid.startswith("swing"):
                    self.swing_qty += qty
                    self.swing_cost += notional
            elif cid.startswith("allsell"):
                self.core_qty = 0
                self.core_cost = 0
                self.swing_qty = 0
                self.swing_cost = 0
                self.disaster = True
            elif cid.startswith("xsell"):
                # The swing is always sold whole, so its books clear here;
                # clamp defensively in case a fill ever reports more than held.
                self.swing_qty = max(0, self.swing_qty - qty)
                if self.swing_qty == 0:
                    self.swing_cost = 0

    def sma(self):
        """The 60-bar simple moving average of closes, or None before 60."""
        if len(self.closes) < SMA_BARS:
            return None
        return sum(self.closes[-SMA_BARS:]) // SMA_BARS

    def buy(self, amount, prefix):
        """One buy order dict with a fresh client id."""
        if prefix == "core":
            self.n_core += 1
            cid = "core%d" % self.n_core
        else:
            self.n_swing += 1
            cid = "swing%d" % self.n_swing
        return {
            "side": "buy",
            "symbol": SYMBOL,
            "notional_quote_units": amount,
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
            "client_id": cid,
        }

    def sell(self, qty, prefix):
        """One sell order dict with a fresh client id."""
        self.n_sell += 1
        return {
            "side": "sell",
            "symbol": SYMBOL,
            "qty": qty,
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
            "client_id": "%s%d" % (prefix, self.n_sell),
        }

    def on_batch(self, state, batch):
        self.apply_fills(batch)
        close = self.record_close(batch)
        if state.warming_up or close is None:
            return []
        held = state.positions.get(SYMBOL)
        total_qty = held.qty if held is not None else 0
        # Disaster stop: the whole position goes when the close has fallen
        # 300 bps from the peak close since the core was bought.
        if self.core_qty > 0:
            if self.peak is None or close > self.peak:
                self.peak = close
            if (self.peak - close) * 10000 >= DISASTER_TRAIL_BPS * self.peak:
                return [self.sell(total_qty, "allsell")]
        # Core entry: once, on batch 24, 70% of the cash.
        if not self.core_bought and not self.disaster and state.seq >= CORE_BAR:
            amount = state.cash * CORE_NUM // CORE_DEN
            if amount >= int(state.hello["fees"]["min_notional_quote_units"]):
                return [self.buy(amount, "core")]
            return []
        # Swing exit: back to the average, or 80 bps either way on cost.
        if self.swing_qty > 0:
            average = self.sma()
            value = state.value(SYMBOL, self.swing_qty)
            if (
                (average is not None and close >= average)
                or value * 10000 >= self.swing_cost * (10000 + SWING_TP_BPS)
                or value * 10000 <= self.swing_cost * (10000 - SWING_SL_BPS)
            ):
                return [self.sell(self.swing_qty, "xsell")]
            return []
        # Swing entry: a dip of 80 bps under the 60-bar average, with the
        # cash the core left over, only while the core is held.
        if self.core_qty > 0:
            average = self.sma()
            if average is not None and (average - close) * 10000 >= DIP_BPS * average:
                amount = state.cash
                if amount >= int(state.hello["fees"]["min_notional_quote_units"]):
                    return [self.buy(amount, "swing")]
        return []


BOT = Bot()
makefun_bars.run(BOT.on_batch)
