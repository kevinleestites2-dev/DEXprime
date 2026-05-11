"""
DEXprime — signal_broker.py
Publishes clean arb signals to ZeusPrime and QuantumPrime.
Replaces DexPaprika REST API calls entirely. No lag. No stale data.
"""

import json, logging, time, os
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from chain_reader import ChainReader, POOL_REGISTRY
from liquidity_map import LiquidityMap

log = logging.getLogger("DEXprime.SignalBroker")

# Signal file paths — ZeusPrime and QuantumPrime read these
SIGNAL_FILE = os.getenv("DEX_SIGNAL_FILE", "/tmp/dexprime_signals.json")
SCAN_INTERVAL = int(os.getenv("DEX_SCAN_INTERVAL", "15"))  # seconds
MIN_GROSS_PCT = float(os.getenv("DEX_MIN_GROSS_PCT", "0.15"))  # 0.15% minimum spread


@dataclass
class ArbSignal:
    pair: str           # "WPOL/USDC"
    buy_dex: str        # where to buy (lower price)
    sell_dex: str       # where to sell (higher price)
    buy_price: float
    sell_price: float
    gross_pct: float    # (sell - buy) / buy * 100
    liquidity_ok: bool  # both pools pass MIN_LIQUIDITY_USD
    timestamp: float
    block_number: int


class SignalBroker:
    """
    Core DEXprime engine.
    Scans all pairs on-chain, computes spreads, filters by liquidity,
    and writes actionable signals to disk for ZeusPrime + QuantumPrime.
    """

    PAIRS = [
        ("WPOL", "USDC"),
        ("WPOL", "WETH"),
        ("WETH", "USDC"),
        ("WBTC", "WETH"),
        ("WBTC", "USDC"),
        ("DAI",  "USDC"),
    ]

    # Rough USD prices for liquidity sizing (updated each cycle from on-chain)
    _price_usd: Dict[str, float] = {
        "WPOL": 0.103, "WETH": 2335.0, "WBTC": 65000.0,
        "USDC": 1.0,   "USDT": 1.0,    "DAI": 1.0,
    }

    def __init__(self):
        self.reader = ChainReader()
        self.lmap = LiquidityMap(self.reader)
        self.scans = 0
        self.signals_emitted = 0

    def _update_usd_prices(self, prices_by_pair: Dict[str, Dict[str, float]]):
        """Update rough USD prices from freshly read on-chain data."""
        # USDC is always ~$1. Use WPOL/USDC to get WPOL price, etc.
        if "WPOL/USDC" in prices_by_pair:
            vals = list(prices_by_pair["WPOL/USDC"].values())
            if vals:
                self._price_usd["WPOL"] = sum(vals) / len(vals)
        if "WETH/USDC" in prices_by_pair:
            vals = list(prices_by_pair["WETH/USDC"].values())
            if vals:
                self._price_usd["WETH"] = sum(vals) / len(vals)

    def _scan_pair(self, token_a: str, token_b: str) -> List[ArbSignal]:
        """Scan one pair across all DEXes and return signals if spread found."""
        prices = self.reader.get_all_prices(token_a, token_b)
        if len(prices) < 2:
            return []

        signals = []
        dex_list = list(prices.items())
        block = self.reader.w3.eth.block_number

        for i in range(len(dex_list)):
            for j in range(i + 1, len(dex_list)):
                dex_a, price_a = dex_list[i]
                dex_b, price_b = dex_list[j]

                # Always buy low, sell high
                if price_a < price_b:
                    buy_dex, buy_price = dex_a, price_a
                    sell_dex, sell_price = dex_b, price_b
                else:
                    buy_dex, buy_price = dex_b, price_b
                    sell_dex, sell_price = dex_a, price_a

                gross_pct = (sell_price - buy_price) / buy_price * 100

                if gross_pct < MIN_GROSS_PCT:
                    continue

                # Check liquidity on both sides
                price_a_usd = self._price_usd.get(token_a, 1.0)
                buy_pool = POOL_REGISTRY.get((token_a, token_b, buy_dex)) or \
                           POOL_REGISTRY.get((token_b, token_a, buy_dex))
                sell_pool = POOL_REGISTRY.get((token_a, token_b, sell_dex)) or \
                            POOL_REGISTRY.get((token_b, token_a, sell_dex))

                buy_ok = self.lmap.is_trustworthy(buy_pool, token_a, token_b, price_a_usd) if buy_pool else False
                sell_ok = self.lmap.is_trustworthy(sell_pool, token_a, token_b, price_a_usd) if sell_pool else False

                sig = ArbSignal(
                    pair=f"{token_a}/{token_b}",
                    buy_dex=buy_dex,
                    sell_dex=sell_dex,
                    buy_price=buy_price,
                    sell_price=sell_price,
                    gross_pct=round(gross_pct, 4),
                    liquidity_ok=(buy_ok and sell_ok),
                    timestamp=time.time(),
                    block_number=block
                )
                signals.append(sig)
                self.signals_emitted += 1
                log.info(f"SIGNAL {sig.pair} | {sig.buy_dex}→{sig.sell_dex} "
                         f"| {sig.gross_pct:.3f}% gross | liq={'✅' if sig.liquidity_ok else '⚠️'}")

        return signals

    def scan_once(self) -> List[ArbSignal]:
        """Run one full scan across all pairs."""
        self.scans += 1
        all_signals = []
        prices_by_pair = {}

        for ta, tb in self.PAIRS:
            prices = self.reader.get_all_prices(ta, tb)
            prices_by_pair[f"{ta}/{tb}"] = prices
            signals = self._scan_pair(ta, tb)
            all_signals.extend(signals)

        self._update_usd_prices(prices_by_pair)
        self._write_signals(all_signals)
        return all_signals

    def _write_signals(self, signals: List[ArbSignal]):
        """Write latest signals to disk. ZeusPrime + QuantumPrime read this file."""
        data = {
            "timestamp": time.time(),
            "scan": self.scans,
            "signals": [asdict(s) for s in signals],
            "stats": {
                "total_scans": self.scans,
                "total_signals": self.signals_emitted,
            }
        }
        with open(SIGNAL_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def run(self):
        """Main loop — scan forever, write signals."""
        log.info(f"DEXprime SignalBroker started | interval={SCAN_INTERVAL}s | min_gross={MIN_GROSS_PCT}%")
        while True:
            try:
                signals = self.scan_once()
                actionable = [s for s in signals if s.liquidity_ok]
                log.info(f"Scan #{self.scans} complete | {len(signals)} signals | "
                         f"{len(actionable)} actionable | next in {SCAN_INTERVAL}s")
            except Exception as e:
                log.error(f"Scan error: {e}")
            time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s"
    )
    broker = SignalBroker()
    broker.run()
