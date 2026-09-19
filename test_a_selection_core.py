"""Lightweight parity checks for the locked current-A selection rule.

No network, Supabase, Google Sheets, or market-data calls.
Run: python test_a_selection_core.py
"""
from a_selection_core import classify_current_a, current_a_trigger_from_history


def old_rule(kd20_now, ret5, atr_pct):
    preferred = bool(kd20_now and ret5 is not None and ret5 <= -0.03 and atr_pct is not None and atr_pct >= 0.04)
    strong = bool(kd20_now and ret5 is not None and ret5 <= -0.05 and atr_pct is not None and atr_pct >= 0.04)
    if strong:
        return ("🔥 强反弹候选", "是", "重点买入候选", 1)
    if preferred:
        return ("✅ 优选候选", "是", "买入候选", 2)
    if kd20_now:
        return ("🟡 普通KD20", "否", "观察", 3)
    return ("无", "否", "无", 9)


def new_tuple(kd20_now, ret5, atr_pct):
    r = classify_current_a(kd20_now, ret5, atr_pct)
    return (r["A候选等级"], r["A正式候选"], r["A动作"], r["A优先级"])


CASES = [
    (False, -0.10, 0.10),   # no KD20
    (True, -0.0299, 0.04),  # just misses 3% drawdown
    (True, -0.03, 0.04),    # exact preferred boundary
    (True, -0.0499, 0.04),  # preferred, just misses strong
    (True, -0.05, 0.04),    # exact strong boundary
    (True, -0.10, 0.0399),  # just misses ATR boundary
    (True, -0.10, 0.04),    # exact ATR boundary
    (True, 0.02, 0.08),     # KD20 only
    (True, None, 0.08),
    (True, -0.10, None),
]


if __name__ == "__main__":
    for case in CASES:
        old = old_rule(*case)
        new = new_tuple(*case)
        assert old == new, f"Mismatch {case}: old={old}, new={new}"
    print(f"PASS: {len(CASES)} current-A parity cases matched.")


KD_CASES = [
    ([10, 12], [11, 11], True),   # strict cross, both <=20
    ([10, 12], [9, 11], False),   # yesterday K already above D
    ([10, 21], [11, 19], False),  # K above low zone
    ([10, 19], [11, 21], False),  # D above low zone
    ([10, 10], [11, 10], False),  # no strict K>D today
]

for k, d, expected in KD_CASES:
    got = current_a_trigger_from_history(k, d)
    assert got == expected, f"KD20 mismatch K={k}, D={d}: expected={expected}, got={got}"
