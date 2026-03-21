"""Unit tests for the ATL/CTL/TSB training load calculation."""
import pytest
from datetime import date, timedelta
from services.training_load import (
    DailyLoad,
    TrainingLoad,
    calculate_hr_tss,
    calculate_load,
)


def test_hr_tss_basic():
    # 1h at HR=160, max=190 → threshold≈161.5 → ratio≈0.99 → TSS≈98
    tss = calculate_hr_tss(duration_s=3600, hr_avg=160, hr_max=190)
    assert 80 < tss < 120, f"Expected TSS around 100, got {tss}"


def test_hr_tss_zero_inputs():
    assert calculate_hr_tss(0, 160, 190) == 0.0
    assert calculate_hr_tss(3600, 0, 190) == 0.0
    assert calculate_hr_tss(3600, 160, 0) == 0.0


def test_calculate_load_empty():
    load = calculate_load([])
    assert load.atl == 0
    assert load.ctl == 0
    assert load.tsb == 0


def test_calculate_load_single_day():
    loads = [DailyLoad(date=date.today(), tss=100)]
    load = calculate_load(loads)
    assert load.atl > 0
    assert load.ctl > 0
    # TSB = CTL - ATL; with single day both are similar
    assert abs(load.tsb) < 50


def test_calculate_load_tsb_rested():
    """After many rest days TSB should be positive (CTL > ATL)."""
    today = date.today()
    # 6 weeks of daily 80 TSS, then 2 weeks rest
    loads = []
    for i in range(42):
        loads.append(DailyLoad(date=today - timedelta(days=42 - i), tss=80))
    for i in range(14):
        loads.append(DailyLoad(date=today - timedelta(days=14 - i), tss=0))

    load = calculate_load(loads)
    assert load.tsb > 0, f"Expected positive TSB after taper, got {load.tsb}"


def test_recommendation_high_run():
    loads = [DailyLoad(date=date.today(), tss=50)]
    load = calculate_load(loads, run_km_14d=60)
    assert "Lauf" in load.recommendation or "km" in load.recommendation


def test_recommendation_tired():
    """Simulate a very tired athlete (large negative TSB)."""
    today = date.today()
    loads = [
        DailyLoad(date=today - timedelta(days=7 - i), tss=200)
        for i in range(7)
    ]
    load = calculate_load(loads)
    assert load.tsb < -10
    assert "müde" in load.recommendation.lower() or "regeneration" in load.recommendation.lower()
