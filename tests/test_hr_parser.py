"""hr_parser tests: 8-bit, 16-bit, RR intervals in 1/1024 s units (T18)."""

from hiyo.hr_parser import parse_heart_rate


def test_8bit_bpm():
    m = parse_heart_rate(bytes([0x00, 72]))
    assert m.bpm == 72
    assert not m.hr_is_16bit
    assert m.rr_intervals_ms == []


def test_16bit_bpm():
    m = parse_heart_rate(bytes([0x01, 0x40, 0x01]))  # 0x0140 = 320
    assert m.bpm == 320
    assert m.hr_is_16bit


def test_rr_intervals_converted_to_ms():
    # flags: RR present (0x10); rr values 1024 units (=1000ms) and 512 (=500ms)
    m = parse_heart_rate(bytes([0x10, 80, 0x00, 0x04, 0x00, 0x02]))
    assert m.bpm == 80
    assert m.rr_intervals_ms == [1000.0, 500.0]


def test_missing_rr_is_fine():
    m = parse_heart_rate(bytes([0x00, 65]))
    assert m.bpm == 65
    assert not m.has_rr  # missing RR must not fabricate HRV (T18)


def test_empty_payload():
    m = parse_heart_rate(b"")
    assert m.bpm is None


def test_contact_bits():
    m = parse_heart_rate(bytes([0x06, 70]))  # contact supported + detected
    assert m.sensor_contact_supported
    assert m.sensor_contact_detected is True
    m2 = parse_heart_rate(bytes([0x00, 70]))  # unsupported -> None not False
    assert m2.sensor_contact_detected is None
