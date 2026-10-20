"""Kalendarze: trwajace wydarzenie ma byc biezacym wydarzeniem (stan "on")."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

from homeassistant.components.calendar import CalendarEvent

from custom_components.librus_apix import calendar as kal

STREFA = kal._STREFA_PL


def _lekcja(od: str, do: str, nazwa: str = "Matematyka") -> CalendarEvent:
    dzien = "2026-10-21"
    return CalendarEvent(
        start=datetime.strptime(f"{dzien} {od}", "%Y-%m-%d %H:%M").replace(tzinfo=STREFA),
        end=datetime.strptime(f"{dzien} {do}", "%Y-%m-%d %H:%M").replace(tzinfo=STREFA),
        summary=nazwa,
    )


def _o(godzina: str) -> datetime:
    return datetime.strptime(f"2026-10-21 {godzina}", "%Y-%m-%d %H:%M").replace(tzinfo=STREFA)


def test_trwajaca_lekcja_jest_biezacym_wydarzeniem():
    lekcje = [_lekcja("08:00", "08:45", "Polski"), _lekcja("08:55", "09:40", "Matematyka")]
    assert kal._biezace_lub_nastepne(lekcje, _o("08:20")).summary == "Polski"


def test_miedzy_lekcjami_zwraca_nastepna():
    lekcje = [_lekcja("08:00", "08:45", "Polski"), _lekcja("08:55", "09:40", "Matematyka")]
    assert kal._biezace_lub_nastepne(lekcje, _o("08:50")).summary == "Matematyka"


def test_po_ostatniej_lekcji_brak_wydarzenia():
    assert kal._biezace_lub_nastepne([_lekcja("08:00", "08:45")], _o("08:45")) is None
    assert kal._biezace_lub_nastepne([], _o("08:00")) is None


def test_wydarzenie_calodniowe_trwa_caly_dzien():
    sprawdzian = CalendarEvent(start=date(2026, 10, 21), end=date(2026, 10, 22), summary="Sprawdzian")
    assert kal._biezace_lub_nastepne([sprawdzian], _o("14:00")).summary == "Sprawdzian"
    assert kal._biezace_lub_nastepne([sprawdzian], _o("14:00") + timedelta(days=1)) is None


def test_zakres_obejmuje_wydarzenia_rozpoczete_przed_zakresem():
    lekcja = _lekcja("08:00", "08:45")
    # widok zaczynajacy sie w trakcie lekcji nadal ja pokazuje
    assert kal._w_zakresie([lekcja], _o("08:30"), _o("12:00")) == [lekcja]
    # a lekcja po zakresie albo przed nim - nie
    assert kal._w_zakresie([lekcja], _o("09:00"), _o("12:00")) == []
    assert kal._w_zakresie([lekcja], _o("06:00"), _o("08:00")) == []


def test_encja_planu_lekcji_uzywa_biezacego_wydarzenia(monkeypatch):
    encja = kal.LibrusTimetableCalendar(MagicMock(), MagicMock(entry_id="x"))
    lekcja = _lekcja("08:00", "08:45")
    monkeypatch.setattr(encja, "_get_events", lambda: [lekcja])

    class _Teraz(datetime):
        @classmethod
        def now(cls, tz=None):
            return _o("08:10")

    monkeypatch.setattr(kal, "datetime", _Teraz)
    assert encja.event is lekcja
