"""Code/terms extraction from free text."""

from __future__ import annotations

from datetime import date

from tyre_finder.data.promo.extract import (
    brands_in_text,
    find_code_candidates,
    looks_like_code,
    parse_terms,
)


def test_strong_candidates_after_keywords() -> None:
    text = (
        "Gumi7: -3% с код: SUM26 за летни гуми. Използвайте промокод TIRE10 при поръчка "
        "над 100 лв. Код за отстъпка „WINTER-5“ важи до 30.11.2026"
    )
    codes = [(c.code, c.strong) for c in find_code_candidates(text)]
    assert codes == [("SUM26", True), ("TIRE10", True), ("WINTER-5", True)]


def test_no_false_codes_from_ordinary_words() -> None:
    text = "Въведи кода в полето „Промо код“ при финализиране. Размер 205/55R16 91V XL, DOT 2025"
    assert find_code_candidates(text) == []
    for token in ("БЮЛЕТИН", "XL", "2055516", "R16", "EUR", "here", "91V"):
        assert not looks_like_code(token)
    assert looks_like_code("MultiDeals1")
    assert looks_like_code("GENIUSDEALS")


def test_terms_percent_brands_period() -> None:
    t = parse_terms(
        "Вземи 6% отстъпка за гуми с Lidl Plus, (Nokian Tyres, Yokohama, Semperit, Kleber, "
        "Tigar и Radar) Период на кампанията: 01.11.2026 г. – 30.11.2026 г."
    )
    assert t.percent == 6.0
    assert t.brands == ("NOKIAN", "YOKOHAMA", "SEMPERIT", "KLEBER", "TIGAR", "RADAR")
    assert t.valid_from == date(2026, 11, 1)
    assert t.valid_until == date(2026, 11, 30)
    assert t.personal_code


def test_terms_amount_min_order_quantity() -> None:
    t = parse_terms("Ваучер 20 € при поръчка над 200 € за минимум 4 гуми")
    assert t.amount_eur == 20.0
    assert t.min_order_eur == 200.0
    assert t.min_quantity == 4
    t = parse_terms("10 лв. отстъпка при покупка над 100 лв.")
    assert t.amount_eur == round(10 / 1.95583, 2)
    assert t.min_order_eur == round(100 / 1.95583, 2)
    assert parse_terms("Купи 4 зимни гуми Michelin").min_quantity == 4


def test_scope_flags() -> None:
    assert parse_terms("до -20% на избрани продукти").selected_only
    assert not parse_terms(
        "Код за -20% на IT, смарт и електроника", general_store=True
    ).applies_to_tyres
    assert parse_terms("Код -5% на гуми", general_store=True).applies_to_tyres
    assert parse_terms("10% за абонамент за бюлетина").newsletter


def test_brands_in_text_skips_ambiguous_words() -> None:
    assert brands_in_text("Event за Michelin и Pirelli") == ("MICHELIN", "PIRELLI")
