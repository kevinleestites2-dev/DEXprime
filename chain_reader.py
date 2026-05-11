"""
DEXprime — chain_reader.py
Direct on-chain pool reads via Web3. No REST APIs. No stale data.
Reads QuickSwap V2, SushiSwap pools directly on Polygon mainnet.
"""

import os, logging
from typing import Optional
from web3 import Web3

log = logging.getLogger("DEXprime.ChainReader")

# ── RPC endpoints (public Polygon mainnet) ────────────────────────────────
RPC_ENDPOINTS = [
    "https://polygon-rpc.com",
    "https://rpc.ankr.com/polygon",
    "https://rpc-mainnet.matic.network",
]

# ── Token addresses (Polygon mainnet) ────────────────────────────────────
TOKENS = {
    "WPOL":  "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
    "WETH":  "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
    "USDC":  "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    "USDT":  "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
    "WBTC":  "0x1BFD67037B42Cf73acF2047067bd4F2C47D9BfD6",
    "DAI":   "0x8f3Cf7ad23Cd3CaDbD9735AFf958023239c6A063",
}

# ── Uniswap V2-style Pool ABI (QuickSwap V2, SushiSwap) ───────────────────
UNIV2_POOL_ABI = [
    {"inputs": [], "name": "getReserves", "outputs": [
        {"name": "_reserve0", "type": "uint112"},
        {"name": "_reserve1", "type": "uint112"},
        {"name": "_blockTimestampLast", "type": "uint32"}
    ], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token0", "outputs": [{"name": "", "type": "address"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token1", "outputs": [{"name": "", "type": "address"}],
     "stateMutability": "view", "type": "function"},
]

# ── Token decimals ─────────────────────────────────────────────────────────
DECIMALS = {
    "WPOL": 18, "WETH": 18, "WBTC": 8,
    "USDC": 6,  "USDT": 6,  "DAI": 18,
}

# ── Known pool addresses (Polygon mainnet) ────────────────────────────────
POOL_REGISTRY = {
    ("WPOL", "USDC", "QuickSwap_V2"):  "0x6e7a5FAFcec6BB1e78bAE2A1F0B612012BF14827",
    ("WPOL", "WETH", "QuickSwap_V2"):  "0xadbF1854e5883eB8aa7BAf50705338739e558E5b",
    ("WPOL", "USDC", "SushiSwap"):     "0xCd078e3b24d9bc8a8A36b232E0B36a8E8c1b9D09",
    ("WETH", "USDC", "QuickSwap_V2"):  "0x853Ee4b2A13f8a742d64C8F088bE7bA2131f670d",
    ("WETH", "USDC", "SushiSwap"):     "0x34965ba0ac2451A34a0471F04CCa3F990b8dea27",
    ("WBTC", "WETH", "QuickSwap_V2"):  "0xdC9232E2Df177d7a12FdFf6EcBAb114E2231198D",
    ("WBTC", "USDC", "QuickSwap_V2"):  "0xF6a637525402643B0654a54bEAd2Cb9A83C8B498",
    ("DAI",  "USDC", "QuickSwap_V2"):  "0xf04adBF75cDFc5eD26eEA4bbbb991DB002036Bdd",
}


class ChainReader:
    """Reads live prices directly from on-chain DEX pools."""

    def __init__(self):
        self.w3 = self._connect()

    def _connect(self) -> Web3:
        for rpc in RPC_ENDPOINTS:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 5}))
                if w3.is_connected():
                    log.info(f"Connected to Polygon via {rpc}")
                    return w3
            except Exception as e:
                log.warning(f"RPC {rpc} failed: {e}")
        raise ConnectionError("All RPC endpoints failed")

    def read_v2_price(self, pool_address: str, token_a: str, token_b: str) -> Optional[float]:
        """Read price from a Uniswap V2-style pool (QuickSwap V2, SushiSwap)."""
        try:
            pool = self.w3.eth.contract(
                address=Web3.to_checksum_address(pool_address),
                abi=UNIV2_POOL_ABI
            )
            reserves = pool.functions.getReserves().call()
            t0_addr = pool.functions.token0().call().lower()
            token_a_addr = TOKENS.get(token_a, "").lower()

            r0, r1 = reserves[0], reserves[1]
            dec_a = DECIMALS.get(token_a, 18)
            dec_b = DECIMALS.get(token_b, 18)

            if t0_addr == token_a_addr:
                price = (r1 / 10**dec_b) / (r0 / 10**dec_a)
            else:
                price = (r0 / 10**dec_a) / (r1 / 10**dec_b)

            return price
        except Exception as e:
            log.debug(f"V2 read failed {pool_address}: {e}")
            return None

    def get_price(self, token_a: str, token_b: str, dex: str) -> Optional[float]:
        """Get live on-chain price for a pair on a given DEX."""
        key = (token_a, token_b, dex)
        pool_addr = POOL_REGISTRY.get(key)
        if not pool_addr:
            key_r = (token_b, token_a, dex)
            pool_addr = POOL_REGISTRY.get(key_r)
            if pool_addr:
                price = self.read_v2_price(pool_addr, token_b, token_a)
                return 1.0 / price if price else None
        if not pool_addr:
            return None
        return self.read_v2_price(pool_addr, token_a, token_b)

    def get_all_prices(self, token_a: str, token_b: str) -> dict:
        """Fetch live prices for a pair across ALL registered DEXes."""
        results = {}
        for (ta, tb, dex) in POOL_REGISTRY:
            if (ta == token_a and tb == token_b) or (ta == token_b and tb == token_a):
                price = self.get_price(token_a, token_b, dex)
                if price:
                    results[dex] = price
        return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    reader = ChainReader()
    pairs = [("WPOL", "USDC"), ("WETH", "USDC"), ("WBTC", "WETH")]
    for ta, tb in pairs:
        print(f"\n── {ta}/{tb} ──")
        prices = reader.get_all_prices(ta, tb)
        for dex, price in prices.items():
            print(f"  {dex}: ${price:.6f}")
