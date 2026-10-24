"""callstore + call_report helpers on synthetic payloads."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import call_report  # noqa: E402
from hiyo.callstore import recording_targets  # noqa: E402


def synth_messages():
    base = 1_800_000_000_000  # epoch ms
    return [
        {"role": "system", "time": base, "secondsFromStart": 0, "message": "sys"},
        {"role": "bot", "time": base + 1000, "endTime": base + 3000, "duration": 2000,
         "secondsFromStart": 1.0, "message": "hi"},
        {"role": "user", "time": base + 5000, "endTime": base + 6000, "duration": 1000,
         "secondsFromStart": 5.0, "message": "hey"},
        {"role": "bot", "time": base + 7200, "endTime": base + 9000, "duration": 1800,
         "secondsFromStart": 7.2, "message": "how can I help"},
        {"role": "user", "time": base + 16000, "endTime": base + 17000, "duration": 1000,
         "secondsFromStart": 16.0, "message": "what's next"},
        {"role": "bot", "toolCalls": [{"function": {"name": "get_next_events", "arguments": "{}"}}],
         "time": base + 17200, "secondsFromStart": 17.2, "message": ""},
        {"role": "tool_call_result", "toolCallId": "x", "name": "get_next_events",
         "result": '{"events": []}', "time": base + 17400, "secondsFromStart": 17.4},
        {"role": "bot", "time": base + 18000, "endTime": base + 19500, "duration": 1500,
         "secondsFromStart": 18.0, "message": "you have a thing"},
    ]


def test_msg_end_prefers_endtime_minus_time_ms():
    m = {"secondsFromStart": 5.0, "time": 1000, "endTime": 2500, "duration": 1500}
    assert call_report.msg_end(m) == 6.5
    # duration alone is ms too
    m2 = {"secondsFromStart": 5.0, "duration": 1500}
    assert call_report.msg_end(m2) == 6.5


def test_response_latencies():
    gaps = call_report.response_latencies(synth_messages())
    # user@5.0 ends 6.0 -> bot@7.2 = 1.2s
    # user@16.0 ends 17.0 -> bot tool-call turn@17.2 = 0.2s
    import pytest as _pt
    assert gaps == _pt.approx([1.2, 0.2])


def test_silence_gaps():
    sil = call_report.silence_gaps(synth_messages())
    # bot ends 9.0 -> user at 16.0 = 7s gap
    assert (9.0, 7.0) in [(round(o, 1), round(g, 1)) for o, g in sil]


def test_overlaps_and_tools():
    assert call_report.overlaps(synth_messages()) == 0
    inter = [{"role": "bot", "secondsFromStart": 1.0, "duration": 5000, "time": 0, "endTime": 5000},
             {"role": "user", "secondsFromStart": 2.0, "time": 0, "endTime": 100}]
    assert call_report.overlaps(inter) == 1
    assert call_report.tool_calls_used(synth_messages()) == ["get_next_events"]


def test_redact_phone():
    assert "+1234567890123" not in call_report.redact("call +1234567890123 now")
    assert call_report.redact("call +1234567890123 now").endswith("23 now")


def test_recording_targets_prefers_presigned():
    call = {"artifact": {
        "presignedMonoUrl": "https://p/mono.wav",
        "presignedStereoUrl": "https://p/stereo.wav",
        "recording": {"mono": {"combinedUrl": "https://r/mono.wav"},
                      "stereoUrl": "https://r/stereo.wav"},
    }}
    t = recording_targets(call)
    assert t == [("recording_mono.wav", "https://p/mono.wav"),
                 ("recording_stereo.wav", "https://p/stereo.wav")]
    # fallback when no presigned
    call2 = {"artifact": {"recording": {"mono": {"combinedUrl": "https://r/m.wav"}}}}
    assert recording_targets(call2) == [("recording_mono.wav", "https://r/m.wav")]
