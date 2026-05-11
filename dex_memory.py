"""
DEXprime — dex_memory.py
Historical spread patterns → feeds QuantumPrime's GeneticEngine.
Stores every signal, tracks win/loss rates per pair/dex combo,
and exports pattern summaries for strategy breeding.
"""

import json, os, time, logging
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict

log = logging.getLogger("DEXprime.Memory")

MEMORY_FILE = os.getenv("DEX_MEMORY_FILE", "/tmp/dexprime_memory.json")


@dataclass
class SpreadRecord:
    pair: str
    buy_dex: str
    sell_dex: str
    gross_pct: float
    liquidity_ok: bool
    executed: bool       # did ZeusPrime act on this?
    profitable: Optional[bool]  # None = unknown, True/False = result
    timestamp: float
    block_number: int


class DEXMemory:
    """
    Persistent pattern memory for DEXprime.
    Logs every signal and outcome. Exports heatmaps to QuantumPrime.
    """

    def __init__(self):
        self._records: List[SpreadRecord] = []
        self._load()

    def _load(self):
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE) as f:
                    data = json.load(f)
                self._records = [SpreadRecord(**r) for r in data.get("records", [])]
                log.info(f"Loaded {len(self._records)} historical records")
            except Exception as e:
                log.warning(f"Memory load failed: {e}")

    def _save(self):
        with open(MEMORY_FILE, "w") as f:
            json.dump({"records": [asdict(r) for r in self._records]}, f, indent=2)

    def log_signal(self, pair: str, buy_dex: str, sell_dex: str,
                   gross_pct: float, liquidity_ok: bool,
                   block_number: int, executed: bool = False) -> SpreadRecord:
        record = SpreadRecord(
            pair=pair, buy_dex=buy_dex, sell_dex=sell_dex,
            gross_pct=gross_pct, liquidity_ok=liquidity_ok,
            executed=executed, profitable=None,
            timestamp=time.time(), block_number=block_number
        )
        self._records.append(record)
        self._save()
        return record

    def update_outcome(self, block_number: int, pair: str, profitable: bool):
        """Called by ZeusPrime after execution to record outcome."""
        for r in reversed(self._records):
            if r.block_number == block_number and r.pair == pair:
                r.profitable = profitable
                r.executed = True
                self._save()
                return

    def get_heatmap(self) -> Dict[str, dict]:
        """
        Returns a heatmap of pair/dex combos by frequency and profitability.
        QuantumPrime's GeneticEngine uses this to score strategies.
        """
        heatmap = defaultdict(lambda: {"count": 0, "executed": 0, "wins": 0,
                                        "avg_gross_pct": 0.0, "total_gross": 0.0})
        for r in self._records:
            key = f"{r.pair}|{r.buy_dex}→{r.sell_dex}"
            heatmap[key]["count"] += 1
            heatmap[key]["total_gross"] += r.gross_pct
            if r.executed:
                heatmap[key]["executed"] += 1
            if r.profitable is True:
                heatmap[key]["wins"] += 1

        for key, data in heatmap.items():
            if data["count"] > 0:
                data["avg_gross_pct"] = round(data["total_gross"] / data["count"], 4)
            win_rate = data["wins"] / data["executed"] if data["executed"] > 0 else None
            data["win_rate"] = round(win_rate, 3) if win_rate is not None else "unknown"

        return dict(heatmap)

    def export_for_quantum(self) -> dict:
        """
        Full export for QuantumPrime's GeneticEngine.
        Returns patterns sorted by opportunity frequency.
        """
        heatmap = self.get_heatmap()
        sorted_patterns = sorted(heatmap.items(), key=lambda x: x[1]["count"], reverse=True)
        return {
            "generated_at": time.time(),
            "total_records": len(self._records),
            "patterns": [{"route": k, **v} for k, v in sorted_patterns]
        }

    def summary(self):
        total = len(self._records)
        executed = sum(1 for r in self._records if r.executed)
        wins = sum(1 for r in self._records if r.profitable is True)
        print(f"\n── DEXprime Memory Summary ──")
        print(f"  Total signals logged : {total}")
        print(f"  Executed             : {executed}")
        print(f"  Profitable           : {wins}")
        print(f"  Win rate             : {wins/executed*100:.1f}%" if executed else "  Win rate: N/A")

        print("\n  Top Routes:")
        heatmap = self.get_heatmap()
        for route, data in sorted(heatmap.items(), key=lambda x: x[1]["count"], reverse=True)[:5]:
            print(f"    {route} | {data['count']}x | avg {data['avg_gross_pct']:.3f}% | win={data['win_rate']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    mem = DEXMemory()
    mem.summary()
    print("\n── QuantumPrime Export ──")
    export = mem.export_for_quantum()
    print(json.dumps(export, indent=2))
