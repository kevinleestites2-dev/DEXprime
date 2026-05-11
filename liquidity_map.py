"""
DEXprime — liquidity_map.py
Tracks pool depths and flags thin/manipulable liquidity.
A spread on a dry pool is a trap. DEXprime doesn't walk into traps.
"""

import logging, time
from typing import Dict, Optional
from web3 import Web3
from chain_reader import ChainReader, POOL_REGISTRY, DECIMALS, TOKENS, UNIV2_POOL_ABI

log = logging.getLogger("DEXprime.LiquidityMap")

# Minimum USD liquidity to consider a pool trustworthy
MIN_LIQUIDITY_USD = 50_000


class LiquidityMap:
    """Monitors pool reserves and flags thin liquidity."""

    def __init__(self, reader: ChainReader):
        self.reader = reader
        self._cache: Dict[str, dict] = {}  # pool_addr → {reserve_usd, timestamp}

    def get_pool_liquidity(self, pool_address: str, token_a: str, token_b: str,
                            price_a_usd: float) -> Optional[float]:
        """
        Returns total pool liquidity in USD.
        Uses token_a reserve × price_a_usd × 2 (both sides equal in balanced pool).
        """
        try:
            pool = self.reader.w3.eth.contract(
                address=Web3.to_checksum_address(pool_address),
                abi=UNIV2_POOL_ABI
            )
            reserves = pool.functions.getReserves().call()
            t0_addr = pool.functions.token0().call().lower()
            token_a_addr = TOKENS.get(token_a, "").lower()

            dec_a = DECIMALS.get(token_a, 18)
            r0, r1 = reserves[0], reserves[1]

            if t0_addr == token_a_addr:
                reserve_a = r0 / 10**dec_a
            else:
                reserve_a = r1 / 10**dec_a

            liquidity_usd = reserve_a * price_a_usd * 2
            self._cache[pool_address] = {
                "liquidity_usd": liquidity_usd,
                "timestamp": time.time()
            }
            return liquidity_usd
        except Exception as e:
            log.debug(f"Liquidity read failed {pool_address}: {e}")
            return None

    def is_trustworthy(self, pool_address: str, token_a: str, token_b: str,
                        price_a_usd: float) -> bool:
        """Returns True only if pool has enough liquidity to execute safely."""
        liq = self.get_pool_liquidity(pool_address, token_a, token_b, price_a_usd)
        if liq is None:
            return False
        if liq < MIN_LIQUIDITY_USD:
            log.warning(f"THIN POOL {pool_address}: ${liq:,.0f} USD — SKIP")
            return False
        return True

    def scan_all(self, token_prices_usd: Dict[str, float]) -> Dict[str, dict]:
        """
        Scan all registered pools and return liquidity report.
        token_prices_usd: {"WPOL": 0.103, "WETH": 2335.0, ...}
        """
        report = {}
        for (ta, tb, dex), addr in POOL_REGISTRY.items():
            price_a = token_prices_usd.get(ta)
            if not price_a:
                continue
            liq = self.get_pool_liquidity(addr, ta, tb, price_a)
            report[f"{ta}/{tb} {dex}"] = {
                "pool": addr,
                "liquidity_usd": liq,
                "trustworthy": (liq or 0) >= MIN_LIQUIDITY_USD
            }
        return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    reader = ChainReader()
    lmap = LiquidityMap(reader)

    # Rough prices for scanning
    prices = {"WPOL": 0.103, "WETH": 2335.0, "WBTC": 65000.0,
              "USDC": 1.0, "USDT": 1.0, "DAI": 1.0}

    report = lmap.scan_all(prices)
    print("\n── Liquidity Map ──")
    for pair, data in report.items():
        status = "✅" if data["trustworthy"] else "⚠️  THIN"
        liq = data["liquidity_usd"]
        liq_str = f"${liq:,.0f}" if liq else "N/A"
        print(f"  {status} {pair}: {liq_str}")
