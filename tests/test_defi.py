from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import Mock

from entrotter_engine.defi import approve, exact_input_single, read_uint, uint_word, wrap_native
from entrotter_engine.evm import ExecutionError
from entrotter_engine.models import ValidationError, validate
from entrotter_engine.rpc import RPCError
from entrotter_engine.runner import run_native as run

DATA = Path(__file__).parent / "data"
TOKEN = "0x" + "a" * 40
OTHER = "0x" + "b" * 40


def local_token():
    scenario = json.loads((DATA / "local.json").read_text())
    scenario["allowed_targets"] = [TOKEN]
    scenario["local_contracts"] = {TOKEN: (DATA / "wrapped-runtime.hex").read_text().strip()}
    scenario["tracked_tokens"] = [{"address": TOKEN, "symbol": "TEST", "decimals": 18}]
    scenario["steps"] = [{"baseline": None, "candidate": wrap_native(TOKEN, 10**18)}]
    return scenario


class DefiBoundaryTests(unittest.TestCase):
    def test_abi_unsigned_bounds(self):
        for value in [-1, True, 2**256, "1", 1.1]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                uint_word(value)

    def test_approve_is_exact_amount_and_spender(self):
        tx = approve(TOKEN, OTHER, 123)
        self.assertEqual(tx["data"], "0x095ea7b3" + OTHER[2:].zfill(64) + f"{123:064x}")

    def test_nonstandard_token_does_not_silently_report_zero(self):
        for data in ["0x", "0x1234", "0x" + "g" * 64, None]:
            with self.subTest(data=data), self.assertRaises(RPCError):
                read_uint(Mock(call=Mock(return_value=data)), TOKEN, "0x313ce567")

    def test_token_metadata_bounds_and_uniqueness(self):
        base = local_token()
        for mutation in [lambda s: s["tracked_tokens"].append(deepcopy(s["tracked_tokens"][0])),
                         lambda s: s["tracked_tokens"][0].update(decimals=True),
                         lambda s: s["tracked_tokens"][0].update(decimals=37),
                         lambda s: s["tracked_tokens"][0].update(address=OTHER),
                         lambda s: s["tracked_tokens"][0].update(symbol="<script>")]:
            s = deepcopy(base)
            mutation(s)
            with self.assertRaises(ValidationError):
                validate(s)

    def test_fixture_cannot_request_token_rpc_reads(self):
        s = json.loads((DATA / "fixture.json").read_text())
        s["tracked_tokens"] = []
        with self.assertRaises(ValidationError):
            validate(s)

    @unittest.skipUnless(shutil.which("cast"), "Foundry cast required for independent ABI comparison")
    def test_swap_encoding_matches_solidity_abi_tool(self):
        action = exact_input_single(router=TOKEN, token_in=TOKEN, token_out=OTHER,
                                   fee=3000, recipient=OTHER, deadline=1700000000,
                                   amount_in=10**18, minimum_out=2000000000)
        expected = subprocess.check_output([
            "cast", "calldata", "exactInputSingle((address,address,uint24,address,uint256,uint256,uint256,uint160))",
            f"({TOKEN},{OTHER},3000,{OTHER},1700000000,1000000000000000000,2000000000,0)"], text=True).strip()
        self.assertEqual(action["data"], expected)


@unittest.skipUnless(shutil.which("anvil"), "Real Anvil required")
class RealTokenTests(unittest.TestCase):
    def test_real_storage_and_token_deltas_are_branch_isolated(self):
        r = run(local_token())
        b, c = r["baseline"]["tokens"][0], r["candidate"]["tokens"][0]
        self.assertEqual(b["initial_balance_raw"], c["initial_balance_raw"])
        self.assertEqual(b["balance_delta_raw"], "0")
        self.assertEqual(c["balance_delta_raw"], str(10**18))
        self.assertEqual(r["candidate"]["trace"][0]["token_deltas_raw"][TOKEN], str(10**18))
        self.assertEqual(r["candidate"]["trace"][0]["receipt"]["status"], "0x1")

    def test_wrong_decimal_pin_fails_execution(self):
        s = local_token()
        s["tracked_tokens"][0]["decimals"] = 6
        with self.assertRaisesRegex(ExecutionError, "decimals"):
            run(s)
