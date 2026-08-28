from agents.universe_screener import UniverseScreener
from models.stock import Stock


def make_stock() -> Stock:
    return Stock(
        ticker="RKLB",
        company="Rocket Lab",
        sector="Industrials",
        industry="Aerospace",
        exchange="NASDAQ",
    )


def test_strong_fundamentals_can_pass_below_ema_200() -> None:
    screener = UniverseScreener()

    result = screener.screen(
        make_stock(),
        market_cap_billion=39.0,
        revenue_growth_percent=52.0,
        debt_to_equity=0.1,
        above_200_ema=False,
    )

    assert result.passed is True
    assert result.score == 80.0
    assert (
        "Price is above the 200-day EMA."
        not in result.reasons
    )


def test_ema_200_adds_twenty_points() -> None:
    screener = UniverseScreener()

    below_ema = screener.screen(
        make_stock(),
        market_cap_billion=39.0,
        revenue_growth_percent=52.0,
        debt_to_equity=0.1,
        above_200_ema=False,
    )

    above_ema = screener.screen(
        make_stock(),
        market_cap_billion=39.0,
        revenue_growth_percent=52.0,
        debt_to_equity=0.1,
        above_200_ema=True,
    )

    assert below_ema.score == 80.0
    assert above_ema.score == 100.0


def test_weak_company_does_not_pass_on_ema_alone() -> None:
    screener = UniverseScreener()

    result = screener.screen(
        make_stock(),
        market_cap_billion=0.5,
        revenue_growth_percent=5.0,
        debt_to_equity=2.0,
        above_200_ema=True,
    )

    assert result.passed is False
    assert result.score == 20.0