"""Wheel & pedal setup: bind axes by moving them, with live feedback.

- `InputBindingsGroup` is the Settings section listing throttle / brake /
  steering with a live bar for each and Detect / Clear buttons.
- `AxisDetectDialog` walks through "press the throttle", "press the brake",
  "turn the wheel" and binds whatever moved, like a game's controls menu.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mmt_app.input.bindings import (
    ROLE_LABELS,
    ROLES,
    AxisBinding,
    AxisDetector,
    InputMapper,
    save_binding,
)

ROLE_COLORS = {"throttle": "#22c55e", "brake": "#ef4444", "steering": "#f97316"}

_PROMPTS = {
    "throttle": "Press the throttle pedal all the way down, then let it go.",
    "brake": "Press the brake pedal as hard as you would under full braking, then let it go.",
    "steering": "Turn the wheel left and right (about half a turn), then back to center.",
}
_LIVE_UPDATE_MS = 33
_DETECT_TICK_MS = 16
_STEP_DONE_PAUSE_MS = 800
_RECONNECT_CHECK_MS = 2000
_RESCAN_WHILE_EMPTY_TICKS = 60  # ~1 s at the detection tick rate


def _is_pedal(role: str) -> bool:
    return role != "steering"


class AxisLevelBar(QWidget):
    """Compact horizontal level bar: 0..1 from the left, or -1..1 from the center."""

    def __init__(self, color: str, *, centered: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._centered = centered
        self._value: float | None = None
        self.setMinimumSize(120, 14)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def configure(self, color: str, *, centered: bool) -> None:
        """Change the fill color and whether the bar fills from the center."""
        self._color = QColor(color)
        self._centered = centered
        self._value = None
        self.update()

    def set_value(self, value: float | None) -> None:
        """Set the level (None draws an empty bar, e.g. when nothing is bound)."""
        if value != self._value:
            self._value = value
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        rect = QRectF(self.rect()).adjusted(0.5, 1.5, -0.5, -1.5)
        painter.setBrush(QColor("#1f2937"))
        painter.drawRoundedRect(rect, 4, 4)
        if self._value is not None:
            painter.setBrush(self._color)
            if self._centered:
                value = max(-1.0, min(1.0, self._value))
                width = abs(value) * rect.width() / 2
                left = rect.center().x() - (width if value < 0 else 0)
                painter.drawRect(QRectF(left, rect.top(), width, rect.height()))
            else:
                value = max(0.0, min(1.0, self._value))
                painter.drawRoundedRect(
                    QRectF(rect.left(), rect.top(), value * rect.width(), rect.height()), 4, 4
                )
        if self._centered:
            painter.setBrush(QColor("#94a3b8"))
            painter.drawRect(QRectF(rect.center().x() - 0.5, rect.top(), 1, rect.height()))
        painter.end()


class AxisDetectDialog(QDialog):
    """Bind one or more roles by asking the user to move each control in turn."""

    def __init__(
        self, mapper: InputMapper, roles: Sequence[str], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._mapper = mapper
        self._roles = list(roles)
        self._index = -1
        self._results: dict[str, AxisBinding] = {}
        self._detector: AxisDetector | None = None
        self._empty_ticks = 0

        self.setWindowTitle("Set up wheel & pedals")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._build_ui()

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(_DETECT_TICK_MS)
        self._tick_timer.timeout.connect(self._tick)
        self._next_timer = QTimer(self)
        self._next_timer.setSingleShot(True)
        self._next_timer.setInterval(_STEP_DONE_PAUSE_MS)
        self._next_timer.timeout.connect(self._next_role)

        self._mapper.hub.refresh()  # Pick up anything plugged in since startup.
        self._next_role()

    @property
    def results(self) -> dict[str, AxisBinding]:
        """Bindings detected in this session (skipped roles are absent)."""
        return dict(self._results)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(10)

        self._step_label = QLabel()
        self._step_label.setObjectName("hintLabel")
        self._step_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._step_label)

        self._title_label = QLabel()
        self._title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._title_label)

        self._prompt_label = QLabel()
        self._prompt_label.setAlignment(Qt.AlignCenter)
        self._prompt_label.setWordWrap(True)
        self._prompt_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(self._prompt_label)

        layout.addSpacing(8)
        self._detected_label = QLabel()
        self._detected_label.setAlignment(Qt.AlignCenter)
        self._detected_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        layout.addWidget(self._detected_label)

        self._bar = AxisLevelBar(ROLE_COLORS["brake"])
        self._bar.setMinimumHeight(18)
        layout.addWidget(self._bar)

        self._hint_label = QLabel()
        self._hint_label.setObjectName("hintLabel")
        self._hint_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._hint_label)

        layout.addSpacing(8)
        buttons = QHBoxLayout()
        self._skip_btn = QPushButton("Skip")
        self._skip_btn.setToolTip("Keep the current setting for this control and continue")
        self._skip_btn.clicked.connect(self._next_role)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self._skip_btn)
        buttons.addStretch()
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

    def _excluded_for(self, role: str) -> list[AxisBinding]:
        """Axes the detector must ignore for `role`."""
        excluded = list(self._results.values())  # Already assigned in this session.
        for other, binding in self._mapper.bindings.items():
            # Never let a pedal take the steering axis or vice versa.
            if other not in self._results and _is_pedal(other) != _is_pedal(role):
                excluded.append(binding)
        return excluded

    def _next_role(self) -> None:
        self._next_timer.stop()
        self._index += 1
        if self._index >= len(self._roles):
            self._tick_timer.stop()
            if self._results:
                self.accept()
            else:
                self.reject()
            return
        role = self._roles[self._index]
        self._detector = AxisDetector(role, exclude=self._excluded_for(role))
        color = ROLE_COLORS[role]

        total = len(self._roles)
        self._step_label.setText(f"Step {self._index + 1} of {total}" if total > 1 else "")
        self._step_label.setVisible(total > 1)
        self._title_label.setText(
            f"<span style='font-size:22px; font-weight:700; color:{color}'>{ROLE_LABELS[role]}</span>"
        )
        self._prompt_label.setText(_PROMPTS[role])
        self._bar.configure(color, centered=not _is_pedal(role))
        self._skip_btn.setEnabled(True)
        self._tick_timer.start()
        self._tick()

    def _tick(self) -> None:
        detector = self._detector
        if detector is None:
            return
        self._mapper.poll()
        hub = self._mapper.hub
        hub.finish_background_refresh()
        controllers = hub.controllers
        if not controllers:
            self._empty_ticks += 1
            if self._empty_ticks >= _RESCAN_WHILE_EMPTY_TICKS:
                self._empty_ticks = 0
                hub.start_background_refresh()
            self._detected_label.setText("No wheel or pedals found")
            self._hint_label.setText("Plug them in; they will be picked up automatically.")
            self._bar.set_value(None)
            return

        detector.update(controllers)
        result = detector.result()
        if result is not None:
            self._complete_step(result)
            return

        leader = detector.leader()
        pedal = _is_pedal(detector.role)
        if leader is None:
            self._detected_label.setText("Waiting for movement…")
            self._hint_label.setText("")
            self._bar.set_value(None)
            return
        self._detected_label.setText(f"{leader.controller.info.product_string} · {leader.field.name}")
        scale = max(leader.travel, detector.min_travel)
        if pedal:
            self._bar.set_value(leader.deflection / scale)
        else:
            self._bar.set_value((leader.last - leader.start) / scale)
        if not detector.reached_travel():
            self._hint_label.setText("Keep pressing…" if pedal else "Keep turning…")
        else:
            self._hint_label.setText("Now let it go." if pedal else "Now bring it back to center.")

    def _complete_step(self, binding: AxisBinding) -> None:
        self._tick_timer.stop()
        role = self._roles[self._index]
        self._results[role] = binding
        self._detected_label.setText(f"✓ {ROLE_LABELS[role]}: {binding.label}")
        self._hint_label.setText("")
        self._bar.set_value(None)
        self._skip_btn.setEnabled(False)
        self._next_timer.start()

    def done(self, result: int) -> None:  # noqa: D102 (Qt override)
        self._tick_timer.stop()
        self._next_timer.stop()
        super().done(result)


class InputBindingsGroup(QGroupBox):
    """Settings section: which controller axis drives throttle, brake and steering."""

    def __init__(
        self,
        mapper: InputMapper,
        parent: QWidget | None = None,
        *,
        on_status_update: Callable[[str], None] | None = None,
        on_bindings_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__("Wheel && Pedals", parent)
        self._mapper = mapper
        self._on_status_update = on_status_update or (lambda _: None)
        self._on_bindings_changed = on_bindings_changed or (lambda: None)
        self._rows: dict[str, tuple[QLabel, AxisLevelBar, QLabel, QPushButton]] = {}
        self._build_ui()

        self._live_timer = QTimer(self)
        self._live_timer.setInterval(_LIVE_UPDATE_MS)
        self._live_timer.timeout.connect(self._update_live)

        # Reopen bound controllers automatically when they are plugged back in.
        self._last_missing: list[str] = []
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setInterval(_RECONNECT_CHECK_MS)
        self._reconnect_timer.timeout.connect(self._reconnect_missing)
        self._reconnect_timer.start()

        self.update_rows()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        setup_btn = QPushButton("\U0001F3AF Set up wheel && pedals…")
        setup_btn.setToolTip(
            "Press each pedal and turn the wheel when asked; the app binds whatever moves."
        )
        setup_btn.setStyleSheet("font-weight: bold;")
        setup_btn.setMinimumHeight(36)
        setup_btn.clicked.connect(lambda: self.open_setup())
        rescan_btn = QPushButton("Rescan")
        rescan_btn.setToolTip("Look for newly connected wheels and pedals")
        rescan_btn.clicked.connect(self.rescan)
        self._devices_label = QLabel()
        self._devices_label.setObjectName("hintLabel")
        self._devices_label.setWordWrap(True)
        top.addWidget(setup_btn)
        top.addWidget(rescan_btn)
        top.addWidget(self._devices_label, stretch=1)
        layout.addLayout(top)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 3)
        for row, role in enumerate(ROLES):
            name = QLabel(ROLE_LABELS[role])
            name.setStyleSheet(f"font-weight: 700; color: {ROLE_COLORS[role]};")
            binding_label = QLabel()
            bar = AxisLevelBar(ROLE_COLORS[role], centered=not _is_pedal(role))
            value_label = QLabel()
            value_label.setMinimumWidth(48)
            value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            detect_btn = QPushButton("Detect")
            detect_btn.setToolTip(f"Bind {ROLE_LABELS[role].lower()} by moving it")
            detect_btn.clicked.connect(lambda _=False, r=role: self.open_setup([r]))
            clear_btn = QPushButton("Clear")
            clear_btn.setToolTip(f"Unassign {ROLE_LABELS[role].lower()}")
            clear_btn.clicked.connect(lambda _=False, r=role: self._clear(r))
            grid.addWidget(name, row, 0)
            grid.addWidget(binding_label, row, 1)
            grid.addWidget(bar, row, 2)
            grid.addWidget(value_label, row, 3)
            grid.addWidget(detect_btn, row, 4)
            grid.addWidget(clear_btn, row, 5)
            self._rows[role] = (binding_label, bar, value_label, clear_btn)
        layout.addLayout(grid)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def open_setup(self, roles: Sequence[str] = ROLES) -> None:
        """Run the guided detection for `roles`; detected bindings are applied on success."""
        dialog = AxisDetectDialog(self._mapper, roles, parent=self.window())
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.accepted.connect(lambda: self._apply_results(dialog.results))
        dialog.rejected.connect(self.update_rows)
        dialog.open()

    def _apply_results(self, results: dict[str, AxisBinding]) -> None:
        for role, binding in results.items():
            self._assign(role, binding)
        names = ", ".join(f"{ROLE_LABELS[r].lower()} → {b.label}" for r, b in results.items())
        self._on_status_update(f"Inputs set: {names}.")
        self.update_rows()
        self._on_bindings_changed()

    def rescan(self) -> None:
        """Re-enumerate controllers (opens newly connected ones)."""
        self._mapper.hub.refresh()
        self.update_rows()
        self._on_bindings_changed()

    def update_rows(self) -> None:
        """Refresh device list and binding labels."""
        names = [c.info.product_string for c in self._mapper.hub.controllers]
        if names:
            self._devices_label.setText("Found: " + ", ".join(names))
        else:
            self._devices_label.setText("No wheels or pedals found. Plug them in and press Rescan.")
        for role, (binding_label, bar, value_label, clear_btn) in self._rows.items():
            binding = self._mapper.binding(role)
            clear_btn.setEnabled(binding is not None)
            if binding is None:
                binding_label.setText("Not set")
                binding_label.setStyleSheet("color: #94a3b8;")
            elif self._mapper.controller_for(role) is None:
                binding_label.setText(f"{binding.label} (not connected)")
                binding_label.setStyleSheet("color: #f59e0b;")
            else:
                binding_label.setText(binding.label)
                binding_label.setStyleSheet("")
            bar.set_value(None)
            value_label.setText("")

    # -------------------------------------------------------------------------
    # Internals
    # -------------------------------------------------------------------------

    def _assign(self, role: str, binding: AxisBinding) -> None:
        # One axis drives one role: unassign anything else that used this axis.
        for other, existing in self._mapper.bindings.items():
            if other != role and existing.same_axis(binding):
                self._mapper.set_binding(other, None)
                save_binding(other, None)
        self._mapper.set_binding(role, binding)
        save_binding(role, binding)

    def _clear(self, role: str) -> None:
        self._mapper.set_binding(role, None)
        save_binding(role, None)
        self._on_status_update(f"{ROLE_LABELS[role]} unassigned.")
        self.update_rows()
        self._on_bindings_changed()

    def _update_live(self) -> None:
        if self._mapper.poll():
            self.update_rows()
            self._on_bindings_changed()
        for role, (_, bar, value_label, _) in self._rows.items():
            value = self._mapper.value(role)
            if value is None:
                bar.set_value(None)
                value_label.setText("")
            elif _is_pedal(role):
                bar.set_value(value / 100.0)
                value_label.setText(f"{value:.0f}%")
            else:
                bar.set_value(value / 100.0)
                value_label.setText(f"{value:+.0f}%")

    def _reconnect_missing(self) -> None:
        """Reopen bound controllers that were unplugged, without blocking the UI."""
        hub = self._mapper.hub
        self._mapper.poll()  # Notices unplugged devices even when nothing else is reading.
        hub.finish_background_refresh()
        missing = self._mapper.missing_devices()
        if missing:
            hub.start_background_refresh()  # Applied on the next check.
        if missing != self._last_missing:
            if self._last_missing and not missing:
                self._on_status_update("Wheel/pedals reconnected.")
            self._last_missing = missing
            self.update_rows()
            self._on_bindings_changed()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().showEvent(event)
        self.update_rows()
        self._live_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._live_timer.stop()
        super().hideEvent(event)
