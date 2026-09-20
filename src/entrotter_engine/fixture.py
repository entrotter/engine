"""Causal synthetic stress tests, not real-world price forecasts or EVM replay."""

from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Protocol, TypedDict
from .artifact import VERSION, seal

D = Decimal


def text(value: Decimal) -> str:
    return format(value, "f")


@dataclass(frozen=True)
class Observation:
    step: int
    price: Decimal
    peak_price: Decimal
    cash: Decimal
    units: Decimal


class TraceRow(TypedDict):
    step: int
    observed_price: str
    action: str
    cash: str
    units: str
    equity: str
    execution_price: str | None
    fee: str


class Policy(Protocol):
    def observe(self, observation: Observation) -> str: ...


class Hold:
    def observe(self, observation: Observation) -> str:
        return "hold"


class CircuitBreaker:
    def __init__(self, trigger: str):
        self.trigger = D(trigger)

    def observe(self, o: Observation) -> str:
        # Only the current observation and past peak are available. No future array.
        if o.units > 0 and (o.peak_price - o.price) / o.peak_price >= self.trigger:
            return "sell_all"
        return "hold"


def build_policy(spec: dict) -> Policy:
    return (
        Hold() if spec["type"] == "hold" else CircuitBreaker(spec["drawdown_trigger"])
    )


def trial(market: dict, spec: dict) -> dict:
    policy = build_policy(spec)
    cash, units = D(market["initial_cash"]), D(market["initial_units"])
    fee_rate = D(market["fee_bps"]) / 10000
    slip = D(market["slippage_bps"]) / 10000
    peak_price, peak_equity, max_drawdown = D(0), D(0), D(0)
    rows: list[TraceRow] = []
    fees, trades = D(0), 0
    for step, raw_price in enumerate(market["prices"]):
        price = D(raw_price)
        peak_price = max(peak_price, price)
        action = policy.observe(Observation(step, price, peak_price, cash, units))
        execution_price, fee = None, D(0)
        if action == "sell_all" and units:
            execution_price = price * (1 - slip)
            gross = units * execution_price
            fee = gross * fee_rate
            cash += gross - fee
            units = D(0)
            fees += fee
            trades += 1
        equity = cash + units * price
        peak_equity = max(peak_equity, equity)
        drawdown = (peak_equity - equity) / peak_equity if peak_equity else D(0)
        max_drawdown = max(max_drawdown, drawdown)
        rows.append(
            {
                "step": step,
                "observed_price": text(price),
                "action": action,
                "cash": text(cash),
                "units": text(units),
                "equity": text(equity),
                "execution_price": text(execution_price)
                if execution_price is not None
                else None,
                "fee": text(fee),
            }
        )
    initial = D(market["initial_cash"]) + D(market["initial_units"]) * D(
        market["prices"][0]
    )
    final = D(rows[-1]["equity"])
    return {
        "policy": spec,
        "trace": rows,
        "metrics": {
            "initial_equity": text(initial),
            "final_equity": text(final),
            "return_pct": text((final - initial) / initial * 100),
            "max_drawdown_pct": text(max_drawdown * 100),
            "fees": text(fees),
            "trades": trades,
        },
    }


def run_fixture(scenario: dict) -> dict:
    with localcontext() as ctx:
        ctx.prec = 60
        baseline = trial(scenario["market"], scenario["baseline"])
        candidate = trial(scenario["market"], scenario["candidate"])
        delta = D(candidate["metrics"]["final_equity"]) - D(
            baseline["metrics"]["final_equity"]
        )
        return seal(
            {
                "schema_version": VERSION,
                "engine_version": VERSION,
                "mode": "fixture",
                "scenario": scenario,
                "baseline": baseline,
                "candidate": candidate,
                "comparison": {"final_equity_delta": text(delta)},
                "assumptions": [
                    "Synthetic exogenous price path; not a historical replay.",
                    "Both policies observe identical prices with no future lookahead.",
                    "Immediate fills with fixed fees/slippage; no gas, MEV, market impact or liquidity model.",
                    "No real money, chain transaction or LLM is used.",
                ],
            }
        )
