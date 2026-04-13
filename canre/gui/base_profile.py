"""Base classes for vehicle GUI profiles.

A VehicleProfile declares:
  - which DBC files to load per logical bus name
  - anchor IDs for bus identification (same data as vehicle_configs)
  - modes and mode-detection rules (ModeRule lists)
  - Qt widget construction and update logic per mode

Mode detection
--------------
A mode is active if ANY of its ModeRules evaluates True.
Rules are evaluated in the order modes are listed; the first matching mode wins.

ModeRule forms:
  1. ID presence only:  bus + msg_id, no signal/predicate.
     True if a frame with that ID was received within max_age_s seconds.
  2. Signal value:      bus + msg_id + signal + predicate.
     True if ID is present AND the decoded signal value satisfies predicate.

Predicates compare raw integer/float values (decode_choices=False is used
by BusDecoder so signals with VAL_ tables return integers, not strings).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, List, Optional


@dataclass
class ModeRule:
    """One condition for mode activation.

    A mode is active if ANY of its rules evaluates True.
    """
    bus: str                                          # logical bus name, e.g. "b_can"
    msg_id: int                                       # CAN arbitration ID (int)
    signal: Optional[str] = None                      # DBC signal name; None = ID-presence check only
    predicate: Optional[Callable[[Any], bool]] = None # None = just check ID presence
    max_age_s: float = 10.0                           # max seconds since last frame

    def evaluate(self, decoder: "BusDecoder") -> bool:  # type: ignore[name-defined]
        if not decoder.id_present(self.bus, self.msg_id, self.max_age_s):
            return False
        if self.signal is None or self.predicate is None:
            return True  # ID presence is sufficient
        val = decoder.get(self.bus, self.msg_id, self.signal)
        if val is None:
            return False
        return bool(self.predicate(val))


class VehicleProfile(ABC):
    """Base class for vehicle-specific GUI profiles.

    Subclasses must define these class-level attributes:

        vehicle_name : str
            Human-readable vehicle name shown in the window title.

        dbc_paths : Dict[str, str]
            {bus_name: path_relative_to_project_root}
            e.g. {"b_can": "projects/coda/CODA-B-CAN.dbc"}

        anchor_ids : Dict[str, FrozenSet[int]]
            {bus_name: frozenset of anchor IDs}
            Used for bus assignment during startup sniffing.
            Must match vehicle_configs.VEHICLES[vehicle_name].buses.

        modes : List[str]
            Ordered list of mode names. Modes are evaluated in order;
            the first matching mode wins. Last entry is the fallback/default.

    Subclasses must implement:

        get_mode_rules() -> Dict[str, List[ModeRule]]
        build_layout(mode: str) -> QWidget
        update(mode: str, decoder: BusDecoder) -> None

    Subclasses may optionally implement:

        build_persistent_panel() -> Optional[QWidget]
            A compact widget shown above all mode layouts at all times.
            Return None (default) to omit the persistent panel.

        update_always(decoder: BusDecoder) -> None
            Called every timer tick regardless of active mode.
            Use this to refresh the persistent panel widgets.
    """

    vehicle_name: str
    dbc_paths: Dict[str, str]
    anchor_ids: Dict[str, FrozenSet[int]]
    modes: List[str]

    def default_mode(self) -> str:
        """Mode shown before any signal data arrives."""
        return self.modes[-1] if self.modes else "idle"

    @abstractmethod
    def get_mode_rules(self) -> Dict[str, List[ModeRule]]:
        """Return {mode_name: [ModeRule, ...]}.

        A mode is active if ANY rule in its list evaluates True.
        The last mode typically has no rules (fallback/default).
        """
        ...

    @abstractmethod
    def build_layout(self, mode: str) -> "QWidget":  # type: ignore[name-defined]
        """Build and return the Qt widget for this mode.

        Called once per mode at startup. Store all widget references as
        instance variables so update() can push values to them later.
        """
        ...

    @abstractmethod
    def update(self, mode: str, decoder: "BusDecoder") -> None:  # type: ignore[name-defined]
        """Pull current values from decoder and refresh all mode widgets."""
        ...

    def build_persistent_panel(self) -> "Optional[QWidget]":  # type: ignore[name-defined]
        """Build and return a compact widget always shown above mode layouts.

        Return None to omit the persistent panel (default).
        Store widget references as instance variables for use in update_always().
        """
        return None

    def update_always(self, decoder: "BusDecoder") -> None:  # type: ignore[name-defined]
        """Refresh persistent panel widgets. Called every timer tick regardless of mode."""
        pass
