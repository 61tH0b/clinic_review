import importlib.util
import random
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_no_phi", Path(__file__).resolve().parents[1] / "scripts" / "check_no_phi.py"
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def _valid_phn(rng: random.Random) -> str:
    while True:
        body = "9" + "".join(rng.choice("0123456789") for _ in range(8))
        check = 11 - sum(int(d) * w for d, w in zip(body[1:], guard.PHN_WEIGHTS)) % 11
        if check < 10:
            return body + str(check)


def test_valid_numbers_are_caught_and_near_misses_are_not():
    rng = random.Random(7)
    for _ in range(200):
        phn = _valid_phn(rng)
        assert guard.is_bc_phn(phn)
        assert not guard.is_bc_phn(phn[:9] + str((int(phn[9]) + 1) % 10))
        assert not guard.is_bc_phn("8" + phn[1:])
        assert guard.PHN_LIKE.search(f"x {phn[:4]} {phn[4:7]} {phn[7:]} y")
