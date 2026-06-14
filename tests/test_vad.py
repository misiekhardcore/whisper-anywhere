import sys
from unittest.mock import MagicMock, patch

import pytest

from whisper_anywhere.vad import (
    VAD,
    FsmnVAD,
    _parse_vad_result,
    _merge_overlapping,
    _to_samples,
    load_vad,
)


class TestParseVadResult:
    def test_empty_input(self):
        assert _parse_vad_result([]) == []

    def test_none_input(self):
        assert _parse_vad_result(None) == []

    def test_dict_with_value_key(self):
        result = {"value": [[100, 500], [800, 1200]]}
        segments = _parse_vad_result(result)
        assert segments == [(100, 500), (800, 1200)]

    def test_list_of_lists(self):
        result = [[100, 500], [800, 1200]]
        segments = _parse_vad_result(result)
        assert segments == [(100, 500), (800, 1200)]

    def test_list_of_dicts(self):
        result = [{"start": 100, "end": 500}, {"start": 800, "end": 1200}]
        segments = _parse_vad_result(result)
        assert segments == [(100, 500), (800, 1200)]

    def test_list_with_value_dicts(self):
        result = [{"key": "k1", "value": [[100, 500], [800, 1200]]}]
        segments = _parse_vad_result(result)
        assert segments == [(100, 500), (800, 1200)]

    def test_list_with_value_dicts_ignores_key_key(self):
        result = [{"key": "k1", "value": [[100, 300]]}]
        segments = _parse_vad_result(result)
        assert segments == [(100, 300)]

    def test_list_of_dicts_with_beg(self):
        result = [{"beg": 100, "end": 500}]
        segments = _parse_vad_result(result)
        assert segments == [(100, 500)]

    def test_merges_overlapping(self):
        result = [[100, 400], [300, 600]]
        segments = _parse_vad_result(result)
        assert segments == [(100, 600)]

    def test_merges_adjacent(self):
        result = [[100, 300], [300, 600]]
        segments = _parse_vad_result(result)
        assert segments == [(100, 600)]

    def test_separate_segments_preserved(self):
        result = [[100, 300], [500, 700]]
        segments = _parse_vad_result(result)
        assert segments == [(100, 300), (500, 700)]

    def test_unsorted_segments_sorted(self):
        result = [[500, 700], [100, 300]]
        segments = _parse_vad_result(result)
        assert segments == [(100, 300), (500, 700)]

    def test_single_element_list(self):
        result = [[100, 500]]
        segments = _parse_vad_result(result)
        assert segments == [(100, 500)]


class TestMergeOverlapping:
    def test_empty(self):
        assert _merge_overlapping([]) == []

    def test_single(self):
        assert _merge_overlapping([(100, 500)]) == [(100, 500)]

    def test_no_overlap(self):
        assert _merge_overlapping([(100, 300), (500, 700)]) == [
            (100, 300),
            (500, 700),
        ]

    def test_partial_overlap(self):
        assert _merge_overlapping([(100, 400), (300, 600)]) == [(100, 600)]

    def test_full_containment(self):
        assert _merge_overlapping([(100, 600), (200, 400)]) == [(100, 600)]

    def test_adjacent(self):
        assert _merge_overlapping([(100, 300), (300, 500)]) == [(100, 500)]


class TestFsmnVAD:
    def test_protocol_conformance(self):
        assert isinstance(FsmnVAD, type)
        assert issubclass(FsmnVAD, object)
        assert hasattr(FsmnVAD, "detect")
        assert hasattr(FsmnVAD, "reset")

    @patch("funasr.AutoModel")
    def test_init_loads_model(self, mock_auto):
        vad = FsmnVAD()
        mock_auto.assert_called_once_with(model=FsmnVAD.MODEL_ID, device="cpu")

    @patch("funasr.AutoModel")
    def test_reset_reinitializes_model(self, mock_auto):
        vad = FsmnVAD()
        vad.reset()
        assert mock_auto.call_count >= 2

    @patch("funasr.AutoModel")
    def test_detect_empty_audio(self, mock_auto):
        mock_auto.return_value.generate.return_value = []
        vad = FsmnVAD()
        result = vad.detect(b"", 16000)
        assert result == []

    @patch("funasr.AutoModel")
    def test_detect_returns_segments(self, mock_auto):
        mock_auto.return_value.generate.return_value = [
            [100, 500],
            [800, 1200],
        ]
        vad = FsmnVAD()
        result = vad.detect(b"\x00\x01" * 16000, 16000)
        assert result == [(100, 500), (800, 1200)]


class TestLoadVAD:
    def test_fsmn_vad_default(self):
        with patch("whisper_anywhere.vad.FsmnVAD") as mock_cls:
            vad = load_vad()
            mock_cls.assert_called_once()
            assert vad is mock_cls.return_value

    def test_fsmn_vad_explicit(self):
        with patch("whisper_anywhere.vad.FsmnVAD") as mock_cls:
            vad = load_vad("fsmn-vad")
            mock_cls.assert_called_once()

    def test_unknown_engine(self):
        with pytest.raises(ValueError, match="Unknown VAD engine"):
            load_vad("nonexistent")


class TestVADProtocol:
    def test_good_vad_conforms(self):
        class GoodVAD:
            def detect(
                self, audio_bytes: bytes, sample_rate: int
            ) -> list[tuple[int, int]]:
                return []

            def reset(self) -> None:
                pass

        assert isinstance(GoodVAD(), VAD)

    def test_missing_detect_does_not_conform(self):
        class BadVAD:
            def reset(self) -> None:
                pass

        assert not isinstance(BadVAD(), VAD)

    def test_missing_reset_does_not_conform(self):
        class BadVAD:
            def detect(
                self, audio_bytes: bytes, sample_rate: int
            ) -> list[tuple[int, int]]:
                return []

        assert not isinstance(BadVAD(), VAD)

    def test_fsmn_vad_conforms(self):
        with patch("funasr.AutoModel"):
            assert isinstance(FsmnVAD(), VAD)
