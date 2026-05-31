import io
import logging
import os
import tempfile
from typing import Any, BinaryIO, Union, cast

from PyCriCodecsEx.hca import HCA
from PyCriCodecsEx.usm import USM
from pgr_assets.extractors.video_encoders import BaseVideoEncoder, Track

logger = logging.getLogger(__name__)


class PGRUSM(USM):
    # Maps stream key (e.g. "@SFA_0") -> RFC 5646 language code.
    audio_language: dict[str, str]

    def __init__(
        self, filename: str | bytes | BinaryIO, key: Union[str, int, bool] = False
    ):
        self.key = key
        self.audio_language = {}
        # Ex's USM only accepts a path or a file-like, not raw bytes.
        if isinstance(filename, (bytes, bytearray)):
            filename = io.BytesIO(filename)
        # Ex demuxes during construction. PGR's SFA chunks are HCA (left
        # unmasked by Ex's reader); decode them once demux has populated output.
        super().__init__(
            filename, cast(str, key)
        )  # bad cast, but the lib is bad at typing
        self._decode_sfa_audio()

    def _decode_sfa_audio(self) -> None:
        filenames = self.CRIDObj.table.get("filename", [])
        i = 1
        for k, v in self.output.items():
            if k.startswith("@SFA_"):
                self.output[k] = HCA(
                    cast(Any, v),  # cast: passed to bytearray, which accepts bytes too
                    key=cast(Any, self.key),
                ).decode()
                self.audio_language[k] = ffmpeg_language_code(filenames[i])
            i += 1

    def extract_video(self, base_outfile: str, encoders: list[BaseVideoEncoder]):
        with tempfile.TemporaryDirectory() as tempdir:
            videos: list[Track] = []
            audios: list[Track] = []

            for k, v in self.output.items():
                # Subtitles not supported (yet)
                if k.startswith("@SBT_"):
                    continue

                path = os.path.join(tempdir, k)
                with open(path, "wb") as f:
                    f.write(v)

                t = Track(k, path)
                if k.startswith("@SFA_"):
                    if (language := self.audio_language.get(k, None)) is not None:
                        t.language = language
                    audios.append(t)
                elif k.startswith("@SFV_"):
                    videos.append(t)
                else:
                    logger.warning("Unknown stream: %s", k)

            for encoder in encoders:
                encoder.encode(base_outfile, videos, audios)


def ffmpeg_language_code(text: str) -> str:
    """
    Detect language tag inside a string and return the
    correct RFC 5646 language code.
    """

    text_lower = text.lower()

    mapping = {
        "jp": "ja",  # Japanese
        "en": "en",  # English
        "cn": "zh",  # Chinese (Simplified/Mandarin)
        "ct": "yue",  # Cantonese (Traditional Chinese audio)
    }

    for key, code in mapping.items():
        if key in text_lower:
            return code

    # close enough usually?
    return text_lower
