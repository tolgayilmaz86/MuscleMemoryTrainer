"""Tests for threshold training tab functionality."""

from __future__ import annotations

import pytest

from mmt_app.config import (
    ThresholdTrainingConfig,
    load_threshold_training_config,
    save_threshold_training_config,
    DEFAULT_THRESHOLD_STEP,
    DEFAULT_THRESHOLD_SPEED,
)
from mmt_app.ui.threshold_training_tab import (
    FloatingTarget,
    StepBasedTargetGenerator,
    ThresholdTrainingState,
)


class TestFloatingTarget:
    """Tests for the FloatingTarget dataclass."""

    def test_creation(self) -> None:
        """Test that FloatingTarget can be created with valid values."""
        target = FloatingTarget(x=50.0, value=75)
        assert target.x == 50.0
        assert target.value == 75

    def test_move_left(self) -> None:
        """Test that move_left decreases x position."""
        target = FloatingTarget(x=50.0, value=75)
        target.move_left(1.5)
        assert target.x == 48.5

    def test_is_expired_when_off_screen(self) -> None:
        """Test that target is expired when x < 0."""
        target = FloatingTarget(x=-1.0, value=50)
        assert target.is_expired() is True

    def test_is_not_expired_when_on_screen(self) -> None:
        """Test that target is not expired when x >= 0."""
        target = FloatingTarget(x=0.0, value=50)
        assert target.is_expired() is False

        target2 = FloatingTarget(x=50.0, value=50)
        assert target2.is_expired() is False


class TestStepBasedTargetGenerator:
    """Tests for the StepBasedTargetGenerator class."""

    def test_default_step(self) -> None:
        """Test default step value."""
        generator = StepBasedTargetGenerator()
        assert generator.step == 10

    def test_custom_step(self) -> None:
        """Test custom step value."""
        generator = StepBasedTargetGenerator(step=15)
        assert generator.step == 15

    def test_step_clamping_below_min(self) -> None:
        """Test that step is clamped to minimum value."""
        generator = StepBasedTargetGenerator(step=1)
        assert generator.step == 5

    def test_step_clamping_above_max(self) -> None:
        """Test that step is clamped to maximum value."""
        generator = StepBasedTargetGenerator(step=100)
        assert generator.step == 25

    def test_step_setter(self) -> None:
        """Test setting step via property."""
        generator = StepBasedTargetGenerator(step=10)
        generator.step = 20
        assert generator.step == 20

    def test_step_setter_clamping(self) -> None:
        """Test that step setter clamps values."""
        generator = StepBasedTargetGenerator(step=10)
        generator.step = 1
        assert generator.step == 5
        generator.step = 100
        assert generator.step == 25

    def test_generate_returns_multiple_of_step(self) -> None:
        """Test that generated values are multiples of step."""
        generator = StepBasedTargetGenerator(step=10)
        for _ in range(50):
            value = generator.generate()
            assert value % 10 == 0
            assert 10 <= value <= 100

    def test_generate_respects_step_of_5(self) -> None:
        """Test that step=5 generates values like 5, 10, 15, ..., 100."""
        generator = StepBasedTargetGenerator(step=5)
        for _ in range(50):
            value = generator.generate()
            assert value % 5 == 0
            assert 5 <= value <= 100

    def test_generate_respects_step_of_25(self) -> None:
        """Test that step=25 generates values like 25, 50, 75, 100."""
        generator = StepBasedTargetGenerator(step=25)
        valid_values = {25, 50, 75, 100}
        for _ in range(50):
            value = generator.generate()
            assert value in valid_values


class TestThresholdTrainingState:
    """Tests for the ThresholdTrainingState dataclass."""

    def test_default_state(self) -> None:
        """Test default state values."""
        state = ThresholdTrainingState()
        assert state.running is False
        assert state.targets == []
        assert state.current_brake == 0.0
        assert state.spawn_counter == 0

    def test_targets_list_is_mutable(self) -> None:
        """Test that targets list can be modified."""
        state = ThresholdTrainingState()
        target = FloatingTarget(x=50.0, value=75)
        state.targets.append(target)
        assert len(state.targets) == 1
        assert state.targets[0] is target


class TestThresholdTrainingConfig:
    """Tests for ThresholdTrainingConfig persistence."""

    def test_config_creation(self) -> None:
        """Test that ThresholdTrainingConfig can be created."""
        config = ThresholdTrainingConfig(step=15, speed=90)
        assert config.step == 15
        assert config.speed == 90

    def test_config_immutable(self) -> None:
        """Test that config is immutable (frozen dataclass)."""
        config = ThresholdTrainingConfig(step=15, speed=90)
        with pytest.raises(AttributeError):
            config.step = 20  # type: ignore[misc]

    def test_default_values(self) -> None:
        """Test default constant values."""
        assert DEFAULT_THRESHOLD_STEP == 10
        assert DEFAULT_THRESHOLD_SPEED == 5

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch) -> None:
        """Test that config can be saved and loaded."""
        # Create a temp config path
        config_file = tmp_path / "config.ini"
        monkeypatch.setattr(
            "mmt_app.config.config_path",
            lambda: config_file,
        )

        # Save config
        original_config = ThresholdTrainingConfig(step=5, speed=2)
        save_threshold_training_config(original_config)

        # Load config
        loaded_config = load_threshold_training_config()

        assert loaded_config.step == original_config.step
        assert loaded_config.speed == original_config.speed

    def test_load_with_missing_section(self, tmp_path, monkeypatch) -> None:
        """Test loading config when section doesn't exist returns defaults."""
        config_file = tmp_path / "config.ini"
        config_file.write_text("[ui]\n")  # Config without threshold_training section
        monkeypatch.setattr(
            "mmt_app.config.config_path",
            lambda: config_file,
        )

        loaded_config = load_threshold_training_config()

        assert loaded_config.step == DEFAULT_THRESHOLD_STEP
        assert loaded_config.speed == DEFAULT_THRESHOLD_SPEED

    def test_load_clamps_invalid_values(self, tmp_path, monkeypatch) -> None:
        """Test that loading clamps invalid values to valid ranges."""
        config_file = tmp_path / "config.ini"
        config_file.write_text(
            "[threshold_training]\nstep = 1\nspeed = 200\n"
        )
        monkeypatch.setattr(
            "mmt_app.config.config_path",
            lambda: config_file,
        )

        loaded_config = load_threshold_training_config()

        assert loaded_config.step == 5  # Clamped to min
        assert loaded_config.speed == 10  # Clamped to max
