# CMS Current A — locked production selection rule
#
# This module documents and centralizes ONLY the eligibility/tiering rule.
# It deliberately contains no Streamlit, Supabase, legacy Early Engine,
# Catalyst, Structure/Trend, Pivot/Room, or historical-replay code.
#
# IMPORTANT: thresholds below are copied exactly from the current production
# analyze_daily_candidate() logic. Keep behavior unchanged.

import math


def _finite_number(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def classify_current_a(kd20_now, ret5, atr_pct):
    """Return the exact current-A eligibility/tier fields.

    Formal A:
      strict KD20 golden cross
      AND prior/current 5D return <= -3%
      AND ATR% >= 4%

    Strong rebound tier:
      same rule, with 5D return <= -5%.

    RSI, volume, OBV, accumulation, panic-release, Early V2 and room/pivot
    are not eligibility filters here.
    """
    ret5 = _finite_number(ret5)
    atr_pct = _finite_number(atr_pct)
    kd20_now = bool(kd20_now)

    preferred = (
        kd20_now
        and ret5 is not None and ret5 <= -0.03
        and atr_pct is not None and atr_pct >= 0.04
    )
    strong = (
        kd20_now
        and ret5 is not None and ret5 <= -0.05
        and atr_pct is not None and atr_pct >= 0.04
    )

    if strong:
        return {
            "A候选等级": "🔥 强反弹候选",
            "A正式候选": "是",
            "A动作": "重点买入候选",
            "A核心原因": "KD20金叉 + 前5日跌≥5% + ATR≥4%",
            "A优先级": 1,
        }
    if preferred:
        return {
            "A候选等级": "✅ 优选候选",
            "A正式候选": "是",
            "A动作": "买入候选",
            "A核心原因": "KD20金叉 + 前5日跌≥3% + ATR≥4%",
            "A优先级": 2,
        }
    if kd20_now:
        return {
            "A候选等级": "🟡 普通KD20",
            "A正式候选": "否",
            "A动作": "观察",
            "A核心原因": "KD20金叉，但未同时满足跌≥3%与ATR≥4%",
            "A优先级": 3,
        }
    return {
        "A候选等级": "无",
        "A正式候选": "否",
        "A动作": "无",
        "A核心原因": "",
        "A优先级": 9,
    }


def rank_current_a(df, max_candidates=20):
    """Apply the existing production A ordering without changing eligibility.

    Existing order:
      1) A优先级 ascending
      2) 资金积累总分 descending
      3) 恐慌释放分 descending
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    out["_a_priority"] = out["A优先级"].apply(_finite_number).fillna(9)
    out["_accum"] = out["资金积累总分"].apply(_finite_number).fillna(0)
    out["_panic"] = out["恐慌释放分"].apply(_finite_number).fillna(0)
    out = out.sort_values(
        ["_a_priority", "_accum", "_panic"],
        ascending=[True, False, False],
    ).drop(columns=["_a_priority", "_accum", "_panic"])
    out = out.head(max_candidates).reset_index(drop=True)
    out["Rank"] = out.index + 1
    return out
