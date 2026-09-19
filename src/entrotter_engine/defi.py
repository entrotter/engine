"""Bounded ABI builders and exact ERC-20 observations; never sends a transaction."""

import re
from .models import ValidationError, address, integer
from .rpc import RPCError


def uint_word(value: int, bits: int = 256) -> str:
    integer(value, "ABI unsigned integer", 0, 2**bits - 1)
    return f"{value:064x}"


def address_word(value: str) -> str:
    return address(value, "ABI address")[2:].zfill(64)


def approve(token: str, spender: str, amount: int) -> dict:
    return {
        "to": address(token, "token"),
        "data": "0x095ea7b3" + address_word(spender) + uint_word(amount),
        "gas": 100000,
    }


def wrap_native(weth: str, amount: int) -> dict:
    uint_word(amount)
    return {
        "to": address(weth, "wrapped native token"),
        "data": "0xd0e30db0",
        "value_wei": str(amount),
        "gas": 100000,
    }


def exact_input_single(
    *,
    router: str,
    token_in: str,
    token_out: str,
    fee: int,
    recipient: str,
    deadline: int,
    amount_in: int,
    minimum_out: int,
    sqrt_price_limit_x96: int = 0,
) -> dict:
    """Uniswap v3 ISwapRouter, NOT SwapRouter02 (which has a different ABI).

    Amounts are raw token units. A zero minimum explicitly provides no minimum-
    output protection. The caller chooses the source, allowlist and action slots.
    """
    if address(token_in, "input token") == address(token_out, "output token"):
        raise ValidationError("Swap tokens must differ")
    fields = [
        address_word(token_in),
        address_word(token_out),
        uint_word(fee, 24),
        address_word(recipient),
        uint_word(deadline),
        uint_word(amount_in),
        uint_word(minimum_out),
        uint_word(sqrt_price_limit_x96, 160),
    ]
    return {
        "to": address(router, "router"),
        "data": "0x414bf389" + "".join(fields),
        "gas": 500000,
    }


def read_uint(rpc, token: str, calldata: str) -> int:
    result = rpc.call("eth_call", [{"to": token, "data": calldata}, "latest"])
    if not isinstance(result, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", result):
        raise RPCError("ERC-20 observation did not return one ABI word")
    try:
        if not result.startswith("0x"):
            raise ValueError
        return int(result[2:], 16)
    except ValueError:
        raise RPCError("ERC-20 observation returned invalid hex") from None


def token_balances(rpc, tokens: list[dict], actor: str) -> dict[str, str]:
    return {
        token["address"].lower(): str(
            read_uint(rpc, token["address"], "0x70a08231" + address_word(actor))
        )
        for token in tokens
    }
