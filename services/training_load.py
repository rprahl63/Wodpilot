"""
ATL / CTL / TSB calculation (like TrainingPeaks).

ATL  = Acute Training Load   – 7-day exponential moving average  (fatigue)
CTL  = Chronic Training Load – 42-day exponential moving average (fitness)
TSB  = TSB = CTL – ATL                                           (form)

HR-based TSS (no power meter):
    TSS = duration_hours × hr_ratio² × 100
    where hr_ratio = hr_avg / hr_threshold
    hr_threshold ≈ 0.85 × hr_max  (lactate threshold approximation)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional


@dataclass
class DailyLoad:
    date: date
    tss: float


@dataclass
class TrainingLoad:
    atl: float          # Acute Training Load (7d EMA)
    ctl: float          # Chronic Training Load (42d EMA)
    tsb: float          # Training Stress Balance = CTL - ATL
    weekly_tss: float   # Rolling 7-day TSS
    recommendation: str # human-readable recommendation
    run_km_14d: float   # total running km in last 14 days


# EMA constants
_ATL_DAYS = 7
_CTL_DAYS = 42
_ATL_ALPHA = 2 / (_ATL_DAYS + 1)
_CTL_ALPHA = 2 / (_CTL_DAYS + 1)


def calculate_hr_tss(
    duration_s: int,
    hr_avg: int,
    hr_max: int,
    hr_threshold: Optional[int] = None,
) -> float:
    """Compute HR-based Training Stress Score."""
    if not duration_s or not hr_avg or not hr_max:
        return 0.0
    if hr_threshold is None:
        hr_threshold = int(0.85 * hr_max)
    duration_h = duration_s / 3600
    hr_ratio = hr_avg / hr_threshold
    return duration_h * (hr_ratio ** 2) * 100


def calculate_load(daily_loads: List[DailyLoad], run_km_14d: float = 0.0) -> TrainingLoad:
    """
    Compute ATL, CTL, TSB from a list of daily TSS values.
    The list should be sorted oldest → newest.
    """
    if not daily_loads:
        return TrainingLoad(
            atl=0, ctl=0, tsb=0, weekly_tss=0,
            recommendation=_recommend(0, 0, 0, run_km_14d),
            run_km_14d=run_km_14d,
        )

    # Fill missing days with 0 TSS
    date_map = {d.date: d.tss for d in daily_loads}
    first_day = daily_loads[0].date
    last_day = daily_loads[-1].date
    all_days: List[float] = []
    cur = first_day
    while cur <= last_day:
        all_days.append(date_map.get(cur, 0.0))
        cur += timedelta(days=1)

    atl = ctl = 0.0
    for tss in all_days:
        atl = _ATL_ALPHA * tss + (1 - _ATL_ALPHA) * atl
        ctl = _CTL_ALPHA * tss + (1 - _CTL_ALPHA) * ctl

    tsb = ctl - atl
    weekly_tss = sum(all_days[-7:])

    return TrainingLoad(
        atl=round(atl, 1),
        ctl=round(ctl, 1),
        tsb=round(tsb, 1),
        weekly_tss=round(weekly_tss, 1),
        recommendation=_recommend(atl, ctl, tsb, run_km_14d),
        run_km_14d=round(run_km_14d, 1),
    )


def _recommend(atl: float, ctl: float, tsb: float, run_km_14d: float) -> str:
    high_run = run_km_14d > 50

    if tsb < -30:
        return (
            "Sehr müde (TSB {tsb:.0f}). Heute Regeneration oder leichte Technikarbeit. "
            "Kein High-Intensity Training.".format(tsb=tsb)
        )
    if tsb < -10:
        base = "Etwas müde (TSB {tsb:.0f}). Moderate Intensität empfohlen.".format(tsb=tsb)
        if high_run:
            base += " Hohe Laufbelastung ({km:.0f} km/14d) → Unterkörper schonen.".format(km=run_km_14d)
        return base
    if tsb < 5:
        base = "Gute Form (TSB {tsb:.0f}). Normal trainieren.".format(tsb=tsb)
        if high_run:
            base += " Laufvolumen beachten ({km:.0f} km/14d).".format(km=run_km_14d)
        return base
    if tsb < 20:
        return "Ausgeruht (TSB {tsb:.0f}). Heute Potenzial für intensives Training oder PR-Versuche.".format(tsb=tsb)
    return "Sehr ausgeruht (TSB {tsb:.0f}). Bereit für maximale Anstrengung.".format(tsb=tsb)
