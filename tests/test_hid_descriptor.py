"""Tests for HID report descriptor parsing (axis discovery like games do)."""

from __future__ import annotations

from mmt_app.input.hid_descriptor import AxisField, guess_axes, parse_input_axes

# Descriptors below were read from real devices with hid.device().get_report_descriptor().

# VNM Direct Drive (captured from real hardware)
VNM_DIRECT_DRIVE = bytes.fromhex(
    "05010904a10185010509190129801500250175019580810205010900a1000930093116008026ff7f75109502"
    "81020932093309340935150027ffff0000751095048102c005020900a10009c409c509c609bb150027ffff00"
    "00751095048102c0050f0992a1028502099f09a009a409a509a6150025017501950581027503950181030994"
    "150025013500450175089501810209221501252835014528750895018102c00921a102850609221501252875"
    "08950191020925a1020926092709300931093209330934094009410942094309281501250c75089501350045"
    "009100c0095009540951150027ffff0000350047ffff000057fdffffff660310751095039102095215002610"
    "27350046102755006500751095019102095315012508350145087508950191020955a1020501093015002501"
    "75019501350045009102c0050f0956150025017501950191027506950191030957a102050a09010902150027"
    "9f8c00003500479f8c000057feffffff6514751095029102c0c0050f095aa102850709221501252835014528"
    "55006500750895019102095b095d15002610273500461027751095029102095c095e150027ffff0000350047"
    "ffff000057fdffffff660310751095029102c0095fa102850809221501252835014528550065007508950191"
    "02092315002503350045037504950191020958a102050a0901090215002503750295029102c0050f096016f0"
    "d826102736f0d84610277510950191020961096209630964096515002610273500461027751095059102c009"
    "6ea102850909221501252835014528750895019102097015002610273500461027751095019102096f16f0d8"
    "26102736f0d846102775109501910209711500279f8c00003500479f8c000057feffffff6514751095019102"
    "0972150027ffff0000350047ffff000057fdffffff660310751095019102c00973a102850a09221501252835"
    "01452855006500750895019102097016f0d826102736f0d8461027751095019102c00974a102850b09221501"
    "2528350145287508950191020975097616f0d826102736f0d8461027751095029102c0096ba102850c092215"
    "01252835014528750895019102096d150026ff00350046ff007508950191020951150027ffff0000350047ff"
    "ff000057fdffffff660310751095019102c00968a102850d0922150125283501452855006500750895019102"
    "096c15002610273500461027751095019102096916f0d826102736f0d84610277510950c920201c00966a102"
    "850e05010930093116f0d8261027751095029102c0050f0977a102850f092215012528350145287508950191"
    "020978a1020979097a097b1501250375089501350045009100c0097c150026ff00350046ff00750895019102"
    "c00990a102851009221501252835014528750895019102c00996a1028511099709980999099a099b099c1501"
    "250675089501350045009100c0097da1028512097e15002610273500461027751095019102c009aba1020925"
    "a10285050926092709300931093209330934094009410942094309281501250c750895014500b100c0050109"
    "3b150026ff01350046ff01750a9501b10275069501b103c0050f0989a1028503092215012528350145287508"
    "9501b102098ba102098c098d098e150125037508950135004500b100c009ac150027ffff0000350047ffff00"
    "0075109501b102c0097fa10285040980150027ffff000075109501b1020983150026ff00350046ff00750895"
    "01b10209a909aa15002501750195024500b10275069501b103c00600ff0901a1ff85410901150026ff003500"
    "45017508953f810285140901150026ff007508953f910285150901150026ff007508953f9102851a09011500"
    "26ff007508953f9102c0c0"
)

# mBooster Pedals (captured from real hardware)
MOZA_MBOOSTER_PEDALS = bytes.fromhex(
    "05010904a1018510093309340935150027ffff0000350047ffff0000751095038102c0"
)

# Forte Formula Pro wheel (captured from real hardware)
ASETEK_FORTE_RIM = bytes.fromhex(
    "05010904a1010900a100850105091901298015002501750195808102050109300931150027ffff0000751095"
    "028102c0093915012508750895018102c0"
)


def _axes_by_name(descriptor: bytes) -> dict[str, AxisField]:
    return {axis.name: axis for axis in parse_input_axes(descriptor)}


class TestRealDescriptors:
    """Axis layouts of real sim racing hardware."""

    def test_mbooster_pedals_have_three_16bit_axes(self) -> None:
        axes = _axes_by_name(MOZA_MBOOSTER_PEDALS)
        assert list(axes) == ["Rx", "Ry", "Rz"]
        for i, name in enumerate(("Rx", "Ry", "Rz")):
            axis = axes[name]
            assert (axis.report_id, axis.bit_offset, axis.bit_size) == (0x10, 16 * i, 16)
            assert (axis.logical_min, axis.logical_max) == (0, 0xFFFF)

    def test_vnm_steering_is_signed_16bit(self) -> None:
        axes = _axes_by_name(VNM_DIRECT_DRIVE)
        x = axes["X"]
        assert (x.report_id, x.bit_offset, x.bit_size) == (1, 128, 16)  # after 128 buttons
        assert (x.logical_min, x.logical_max) == (-32768, 32767)
        # Simulation-page pedal axes on the base are found too.
        assert {"Accelerator", "Brake", "Clutch"} <= set(axes)

    def test_vnm_skips_outputs_features_and_vendor_reports(self) -> None:
        axes = parse_input_axes(VNM_DIRECT_DRIVE)
        assert {a.report_id for a in axes} == {1}
        assert len(axes) == 10

    def test_forte_rim_axes(self) -> None:
        axes = _axes_by_name(ASETEK_FORTE_RIM)
        assert list(axes) == ["X", "Y"]
        assert axes["X"].bit_offset == 128 and axes["Y"].bit_offset == 144


class TestAxisFieldRead:
    """Decoding values from reports as hidapi returns them."""

    def test_reads_numbered_report(self) -> None:
        rz = _axes_by_name(MOZA_MBOOSTER_PEDALS)["Rz"]
        report = [0x10, 0x00, 0x00, 0x38, 0x01, 0x34, 0x12]
        assert rz.read(report) == 0x1234

    def test_wrong_report_id_gives_none(self) -> None:
        rz = _axes_by_name(MOZA_MBOOSTER_PEDALS)["Rz"]
        assert rz.read([0x11, 0, 0, 0, 0, 0x34, 0x12]) is None

    def test_short_report_gives_none(self) -> None:
        rz = _axes_by_name(MOZA_MBOOSTER_PEDALS)["Rz"]
        assert rz.read([0x10, 0, 0]) is None
        assert rz.read(None) is None

    def test_signed_values_are_sign_extended(self) -> None:
        x = _axes_by_name(VNM_DIRECT_DRIVE)["X"]
        report = [1] + [0] * 16 + [0x20, 0xFF] + [0] * 40  # -224 little-endian
        assert x.read(report) == -224
        report[17:19] = [0xFF, 0x7F]
        assert x.read(report) == 32767

    def test_unnumbered_report_starts_at_byte_zero(self) -> None:
        axis = AxisField(report_id=0, bit_offset=8, bit_size=8, logical_min=0, logical_max=255)
        assert axis.read([0x01, 0x80, 0x02]) == 0x80

    def test_sub_byte_offsets(self) -> None:
        axis = AxisField(report_id=0, bit_offset=4, bit_size=10, logical_min=0, logical_max=1023)
        # value 0x2AB placed at bit 4: 0x2AB << 4 = 0x2AB0
        assert axis.read([0xB0, 0x2A]) == 0x2AB

    def test_normalized(self) -> None:
        x = _axes_by_name(VNM_DIRECT_DRIVE)["X"]
        assert x.normalized(-32768) == 0.0
        assert x.normalized(32767) == 1.0


class TestDescriptorEdgeCases:
    """Descriptor features beyond the captured devices."""

    def test_padding_and_buttons_shift_offsets(self) -> None:
        descriptor = bytes([
            0x05, 0x01, 0x09, 0x04, 0xA1, 0x01,  # Joystick application collection
            0x05, 0x09, 0x19, 0x01, 0x29, 0x05,  # Buttons 1..5
            0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x05, 0x81, 0x02,
            0x75, 0x03, 0x95, 0x01, 0x81, 0x03,  # 3 bits constant padding
            0x05, 0x01, 0x09, 0x30,              # X
            0x15, 0x00, 0x26, 0xFF, 0x03, 0x75, 0x0A, 0x95, 0x01, 0x81, 0x02,
            0xC0,
        ])
        axes = parse_input_axes(descriptor)
        assert len(axes) == 1
        assert (axes[0].name, axes[0].bit_offset, axes[0].bit_size, axes[0].logical_max) == (
            "X", 8, 10, 1023
        )

    def test_one_byte_logical_max_quirk(self) -> None:
        descriptor = bytes([
            0x05, 0x01, 0x09, 0x32, 0x15, 0x00, 0x25, 0xFF,  # Logical max encoded as 0xFF
            0x75, 0x08, 0x95, 0x01, 0x81, 0x02,
        ])
        (axis,) = parse_input_axes(descriptor)
        assert (axis.logical_min, axis.logical_max) == (0, 255)

    def test_usage_range_and_extended_usage(self) -> None:
        descriptor = bytes([
            0x05, 0x01, 0x19, 0x30, 0x29, 0x32,           # Usage min X .. max Z
            0x15, 0x00, 0x26, 0xFF, 0x00, 0x75, 0x08, 0x95, 0x03, 0x81, 0x02,
            0x0B, 0xC5, 0x00, 0x02, 0x00,                 # 4-byte usage: Simulation/Brake
            0x75, 0x08, 0x95, 0x01, 0x81, 0x02,
        ])
        axes = parse_input_axes(descriptor)
        assert [a.name for a in axes] == ["X", "Y", "Z", "Brake"]
        assert axes[3].bit_offset == 24

    def test_push_pop_restores_globals(self) -> None:
        descriptor = bytes([
            0x05, 0x01, 0x15, 0x00, 0x26, 0xFF, 0x00, 0x75, 0x08, 0x95, 0x01,
            0xA4,                                   # Push
            0x26, 0xFF, 0x03, 0x75, 0x10,           # 10-bit range in 16 bits
            0x09, 0x30, 0x81, 0x02,
            0xB4,                                   # Pop -> back to 8-bit
            0x09, 0x31, 0x81, 0x02,
        ])
        x, y = parse_input_axes(descriptor)
        assert (x.bit_size, x.logical_max) == (16, 1023)
        assert (y.bit_offset, y.bit_size, y.logical_max) == (16, 8, 255)

    def test_garbage_does_not_crash(self) -> None:
        assert parse_input_axes(b"") == []
        assert parse_input_axes(bytes(range(256))) is not None


def test_guess_axes_offers_bytes_and_pairs() -> None:
    fields = guess_axes(4)
    names = [f.name for f in fields]
    assert names == ["Byte 0", "Bytes 0-1", "Byte 1", "Bytes 1-2", "Byte 2", "Bytes 2-3", "Byte 3"]
