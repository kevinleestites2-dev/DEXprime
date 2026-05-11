# DEXprime — The Pantheon's On-Chain Eyes

> Not a scanner. Not a REST API wrapper. A sovereign DEX intelligence layer.

## What It Does

DEXprime reads prices **directly from on-chain pools** via Web3 — no DexPaprika, no REST lag, no stale data. It maps liquidity depth to filter thin/manipulable pools, computes real spreads, and publishes clean signals to ZeusPrime and QuantumPrime.

## Architecture

```
chain_reader.py    — Web3 direct pool reads (V2 + V3) on Polygon mainnet
liquidity_map.py   — Pool reserve tracking + thin pool detection ($50K min)
signal_broker.py   — Core engine: scans all pairs, emits actionable signals
dex_memory.py      — Historical pattern storage → QuantumPrime GeneticEngine feed
```

## Signal Flow

```
DEXprime (signal_broker.py)
    ↓  writes /tmp/dexprime_signals.json
ZeusPrime (reads signals → executes flash loan arb)
    ↓  reports outcome
DEXprime (dex_memory.py stores win/loss)
    ↓  exports heatmap
QuantumPrime (GeneticEngine breeds better strategies)
```

## Pairs Monitored

- WPOL/USDC
- WPOL/WETH
- WETH/USDC
- WBTC/WETH
- WBTC/USDC
- DAI/USDC

## Run (Termux)

```bash
# Clone
git clone https://github.com/kevinleestites2-dev/DEXprime
cd DEXprime

# Install
pip install web3

# Run signal broker (continuous scan, 15s interval)
python3 signal_broker.py

# One-time price check
python3 chain_reader.py

# Liquidity map
python3 liquidity_map.py

# Memory / pattern report
python3 dex_memory.py
```

## Environment Variables

```bash
DEX_SIGNAL_FILE=/tmp/dexprime_signals.json   # where signals are written
DEX_MEMORY_FILE=/tmp/dexprime_memory.json    # historical pattern storage
DEX_SCAN_INTERVAL=15                          # seconds between scans
DEX_MIN_GROSS_PCT=0.15                        # minimum spread % to emit signal
```

## Pantheon Role

**DEXprime** sits between raw on-chain data and ZeusPrime's execution layer. It is the intelligence that prevents Zeus from walking into thin-liquidity traps and stale spread mirages. QuantumPrime's GeneticEngine ingests DEXprime's historical heatmap to breed winning arb strategies over time.

```
Raw Chain Data → DEXprime → Clean Signals → ZeusPrime (execute)
                                          → QuantumPrime (evolve)
```
