from unittest.mock import MagicMock, patch

import pytest

from whisper_anywhere.vad import (
    VAD,
    FsmnVAD,
    _merge_overlapping,
    _parse_vad_result,
    load_vad,
)


class TestParseVadResult:
    def test_empty_input(self) -> None:
        assert _parse_vad_result([]) == []

    def test_none_input(self) -> None:
        assert _parse_vad_result(None) == []

    def test_dict_with_value_key(self) -> None:
        result: dict[str, list[list[int]]] = {"value": [[100, 500], [800, 1200]]}
        segments: list[tuple[int, int]] = _parse_vad_result(result)
        assert segments == [(100, 500), (800, 1200)]

    def test_list_of_lists(self) -> None:
        result: list[list[int]] = [[100, 500], [800, 1200]]
        segments: list[tuple[int, int]] = _parse_vad_result(result)
        assert segments == [(100, 500), (800, 1200)]

    def test_list_of_dicts(self) -> None:
        result: list[dict[str, int]] = [
            {"start": 100, "end": 500},
            {"start": 800, "end": 1200},
        ]
        segments = _parse_vad_result(result)
        assert segments == [(100, 500), (800, 1200)]

    def test_list_with_value_dicts(self) -> None:
        result: list[dict[str, list[list[int]]]] = [
            {"key": "k1", "value": [[100, 500], [800, 1200]]}
        ]
        segments: list[tuple[int, int]] = _parse_vad_result(result)
        assert segments == [(100, 500), (800, 1200)]

    def test_list_with_value_dicts_ignores_key_key(self) -> None:
        result: list[dict[str, list[list[int]]]] = [
            {"key": "k1", "value": [[100, 300]]}
        ]
        segments: list[tuple[int, int]] = _parse_vad_result(result)
        assert segments == [(100, 300)]

    def test_list_of_dicts_with_beg(self) -> None:
        result: list[dict[str, int]] = [{"beg": 100, "end": 500}]
        segments: list[tuple[int, int]] = _parse_vad_result(result)
        assert segments == [(100, 500)]

    def test_merges_overlapping(self) -> None:
        result: list[list[int]] = [[100, 400], [300, 600]]
        segments: list[tuple[int, int]] = _parse_vad_result(result)
        assert segments == [(100, 600)]

    def test_merges_adjacent(self) -> None:
        result: list[list[int]] = [[100, 300], [300, 600]]
        segments: list[tuple[int, int]] = _parse_vad_result(result)
        assert segments == [(100, 600)]

    def test_separate_segments_preserved(self) -> None:
        result: list[list[int]] = [[100, 300], [500, 700]]
        segments: list[tuple[int, int]] = _parse_vad_result(result)
        assert segments == [(100, 300), (500, 700)]

    def test_unsorted_segments_sorted(self) -> None:
        result: list[list[int]] = [[500, 700], [100, 300]]
        segments: list[tuple[int, int]] = _parse_vad_result(result)
        assert segments == [(100, 300), (500, 700)]

    def test_single_element_list(self) -> None:
        result: list[list[int]] = [[100, 500]]
        segments: list[tuple[int, int]] = _parse_vad_result(result)
        assert segments == [(100, 500)]


class TestMergeOverlapping:
    def test_empty(self) -> None:
        assert _merge_overlapping([]) == []

    def test_single(self) -> None:
        assert _merge_overlapping([(100, 500)]) == [(100, 500)]

    def test_no_overlap(self) -> None:
        assert _merge_overlapping([(100, 300), (500, 700)]) == [
            (100, 300),
            (500, 700),
        ]

    def test_partial_overlap(self) -> None:
        assert _merge_overlapping([(100, 400), (300, 600)]) == [(100, 600)]

    def test_full_containment(self) -> None:
        assert _merge_overlapping([(100, 600), (200, 400)]) == [(100, 600)]

    def test_adjacent(self) -> None:
        assert _merge_overlapping([(100, 300), (300, 500)]) == [(100, 500)]


class TestFsmnVAD:
    def test_protocol_conformance(self) -> None:
        assert isinstance(FsmnVAD, type)
        assert issubclass(FsmnVAD, object)
        assert hasattr(FsmnVAD, "detect")
        assert hasattr(FsmnVAD, "reset")

    @patch("funasr.AutoModel")
    def test_init_loads_model(self, mock_auto: MagicMock) -> None:
        FsmnVAD()
        mock_auto.assert_called_once_with(model=FsmnVAD.ENGINE_ID, device="cpu")

    @patch("funasr.AutoModel")
    def test_reset_is_noop(self, mock_auto: MagicMock) -> None:
        vad: FsmnVAD = FsmnVAD()
        vad.reset()
        assert mock_auto.call_count == 1

    @patch("funasr.AutoModel")
    def test_detect_empty_audio(self, mock_auto: MagicMock) -> None:
        mock_auto.return_value.generate.return_value = []
        vad: FsmnVAD = FsmnVAD()
        result: list[tuple[int, int]] = vad.detect(b"", 16000)
        assert result == []

    @patch("funasr.AutoModel")
    def test_detect_returns_segments(self, mock_auto: MagicMock) -> None:
        mock_auto.return_value.generate.return_value = [
            [100, 500],
            [800, 1200],
        ]
        vad: FsmnVAD = FsmnVAD()
        result: list[tuple[int, int]] = vad.detect(b"\x00\x01" * 16000, 16000)
        assert result == [(100, 500), (800, 1200)]


class TestLoadVAD:
    def test_fsmn_vad_default(self) -> None:
        with patch("whisper_anywhere.vad.FsmnVAD"):
            vad: FsmnVAD = load_vad()
            assert isinstance(vad, FsmnVAD)

    def test_fsmn_vad_explicit(self) -> None:
        with patch("whisper_anywhere.vad.FsmnVAD"):
            vad: FsmnVAD = load_vad("fsmn-vad")
            assert isinstance(vad, FsmnVAD)

    def test_unknown_engine(self) -> None:
        with pytest.raises(ValueError, match="Unknown VAD engine"):
            load_vad("nonexistent")


class TestVADProtocol:
    def test_good_vad_conforms(self) -> None:
        class GoodVAD:
            def detect(
                self, audio_bytes: bytes, sample_rate: int
            ) -> list[tuple[int, int]]:
                return []

            def reset(self) -> None:
                pass

        assert isinstance(GoodVAD(), VAD)

    def test_missing_detect_does_not_conform(self) -> None:
        class BadVAD:
            def reset(self) -> None:
                pass

        assert not isinstance(BadVAD(), VAD)

    def test_missing_reset_does_not_conform(self) -> None:
        class BadVAD:
            def detect(
                self, audio_bytes: bytes, sample_rate: int
            ) -> list[tuple[int, int]]:
                return []

        assert not isinstance(BadVAD(), VAD)

    def test_fsmn_vad_conforms(self) -> None:
        with patch("funasr.AutoModel"):
            assert isinstance(FsmnVAD(), VAD)
