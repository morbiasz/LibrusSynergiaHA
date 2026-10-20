"""Platforma kalendarza dla integracji Librus."""
import logging
from datetime import datetime, timedelta, date
from typing import Any, Dict, List

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import zoneinfo

from .const import DOMAIN
from .sensor import _device_info

_LOGGER = logging.getLogger(__name__)

# Strefa ladowana raz przy imporcie modulu (w executorze HA) - ZoneInfo przy
# pierwszym uzyciu czyta plik, co w petli zdarzen HA zglasza jako blokujace.
_STREFA_PL = zoneinfo.ZoneInfo("Europe/Warsaw")


def _biezace_lub_nastepne(events: List[CalendarEvent], now: datetime) -> CalendarEvent | None:
    """Trwajace wydarzenie albo, gdy zadne nie trwa, najblizsze nadchodzace.

    Wydarzenie trwa do swojego konca, wiec liczy sie czas zakonczenia, a nie
    rozpoczecia - inaczej encja nigdy nie bylaby w stanie "on".
    """
    aktualne = [e for e in events if e.end_datetime_local > now]
    if not aktualne:
        return None
    return min(aktualne, key=lambda e: e.start_datetime_local)


def _w_zakresie(
    events: List[CalendarEvent], start_date: datetime, end_date: datetime
) -> List[CalendarEvent]:
    """Wydarzenia, ktore zachodza na zadany zakres (rowniez rozpoczete wczesniej)."""
    return [
        e for e in events
        if e.start_datetime_local < end_date and e.end_datetime_local > start_date
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Konfiguracja platformy kalendarza."""
    client = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = client.coordinator
    
    async_add_entities([
        LibrusTimetableCalendar(coordinator, config_entry),
        LibrusScheduleCalendar(coordinator, config_entry)
    ])


class LibrusTimetableCalendar(CoordinatorEntity, CalendarEntity):
    """Kalendarz planu lekcji."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Plan lekcji (Kalendarz)"
        self._attr_unique_id = f"{config_entry.entry_id}_plan_lekcji_kalendarz"
        
        # Wymagane przez Home Assistant
        self._event: CalendarEvent | None = None

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def event(self) -> CalendarEvent | None:
        """Zwraca trwajace lub najblizsze nadchodzace wydarzenie."""
        events = self._get_events()
        if not events:
            return None
            
        return _biezace_lub_nastepne(events, datetime.now(_STREFA_PL))

    def _get_events(self) -> List[CalendarEvent]:
        """Pobiera i formatuje wydarzenia z koordynatora."""
        events = []
        data = self.coordinator.data or {}
        plan = data.get("plan_lekcji", [])
        
        tz = _STREFA_PL
        
        for day in plan:
            lekcje = day.get("lekcje", [])
            for lekcja in lekcje:
                try:
                    # Format: YYYY-MM-DD
                    lekcja_data = lekcja.get("data")
                    if not lekcja_data:
                        continue
                        
                    # Format: HH:MM
                    godzina_od = lekcja.get("godzina_od")
                    godzina_do = lekcja.get("godzina_do")
                    if not godzina_od or not godzina_do:
                        continue
                        
                    if "??:??" in godzina_od or "??:??" in godzina_do:
                        dt_od = datetime.strptime(lekcja_data, "%Y-%m-%d").date()
                        dt_do = dt_od + timedelta(days=1)
                    else:
                        dt_od = datetime.strptime(f"{lekcja_data} {godzina_od}", "%Y-%m-%d %H:%M")
                        dt_do = datetime.strptime(f"{lekcja_data} {godzina_do}", "%Y-%m-%d %H:%M")
                        dt_od = dt_od.replace(tzinfo=tz)
                        dt_do = dt_do.replace(tzinfo=tz)
                    
                    przedmiot = lekcja.get("przedmiot", "Lekcja")
                    odwolana = lekcja.get("odwolana", False)
                    zastepstwo = lekcja.get("zastepstwo", False)
                    zdarzenie = lekcja.get("zdarzenie")
                    
                    if odwolana:
                        summary = f"❌ [Odwołane] {przedmiot}"
                    elif zastepstwo:
                        summary = f"🔄 [Zastępstwo] {przedmiot}"
                    elif zdarzenie == "Sprawdzian":
                        summary = f"🔴 [{zdarzenie}] {przedmiot}"
                    elif zdarzenie:
                        summary = f"🟠 [{zdarzenie}] {przedmiot}"
                    else:
                        summary = przedmiot

                    sala = lekcja.get("nauczyciel_i_sala", "")
                    description = f"Nauczyciel i sala: {sala}" if sala else ""
                    
                    events.append(
                        CalendarEvent(
                            start=dt_od,
                            end=dt_do,
                            summary=summary,
                            description=description,
                            location=sala
                        )
                    )
                except ValueError as ex:
                    _LOGGER.error("Błąd parsowania daty w planie lekcji: %s", ex)
                    
        return events

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> List[CalendarEvent]:
        """Zwraca wydarzenia dla danego zakresu dat."""
        return _w_zakresie(self._get_events(), start_date, end_date)


class LibrusScheduleCalendar(CoordinatorEntity, CalendarEntity):
    """Kalendarz sprawdzianow i kartkowek (Terminarz)."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Terminarz (Kalendarz)"
        self._attr_unique_id = f"{config_entry.entry_id}_terminarz_kalendarz"
        
        self._event: CalendarEvent | None = None

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def event(self) -> CalendarEvent | None:
        events = self._get_events()
        if not events:
            return None
            
        return _biezace_lub_nastepne(events, datetime.now(_STREFA_PL))

    def _get_events(self) -> List[CalendarEvent]:
        events = []
        data = self.coordinator.data or {}
        terminarz = data.get("terminarz", [])
        
        plan = data.get("plan_lekcji", [])
        tz = _STREFA_PL
        
        for ev in terminarz:
            try:
                ev_data = ev.get("data")
                if not ev_data:
                    continue
                    
                dt_start = datetime.strptime(ev_data, "%Y-%m-%d").date()
                dt_end = dt_start + timedelta(days=1)
                is_all_day = True
                
                numer_lekcji = ev.get("numer_lekcji")
                if numer_lekcji and numer_lekcji != "unknown":
                    # Szukamy godziny lekcji w planie
                    for day in plan:
                        if day.get("data") == ev_data:
                            for lekcja in day.get("lekcje", []):
                                if str(lekcja.get("numer")) == str(numer_lekcji):
                                    godzina_od = lekcja.get("godzina_od")
                                    godzina_do = lekcja.get("godzina_do")
                                    if godzina_od and godzina_do and "??" not in godzina_od and "??" not in godzina_do:
                                        dt_start = datetime.strptime(f"{ev_data} {godzina_od}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
                                        dt_end = datetime.strptime(f"{ev_data} {godzina_do}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
                                        is_all_day = False
                                    break
                            break
                
                przedmiot = ev.get("przedmiot", "")
                tytul = ev.get("tytul", "")
                szczegoly = ev.get("szczegoly", "")
                
                summary = f"[{przedmiot}] {tytul}" if przedmiot else tytul
                
                if isinstance(szczegoly, dict):
                    description = "\n".join(f"{k}: {v}" for k, v in szczegoly.items() if v.lower() != "unknown")
                else:
                    description = f"{szczegoly}"
                
                events.append(
                    CalendarEvent(
                        start=dt_start,
                        end=dt_end,
                        summary=summary,
                        description=description
                    )
                )
            except ValueError as ex:
                _LOGGER.error("Błąd parsowania daty w terminarzu: %s", ex)
                
        return events

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> List[CalendarEvent]:
        return _w_zakresie(self._get_events(), start_date, end_date)
