import logging
import os
import re
import tempfile
from typing import Any, cast

from pgr_assets.cri import HCA, USM
from pgr_assets.extractors.video_encoders import BaseVideoEncoder, Track

logger = logging.getLogger(__name__)


class PGRUSM(USM):
    # Maps stream key (e.g. "@SFA_0") -> RFC 5646 language code.
    audio_language: dict[str, str]

    def __init__(self, filename: str | bytes, key: str | int | bool = False):
        self.key = key
        self.audio_language = {}
        super().__init__(
            filename, cast(str, key)
        )  # bad cast, but the lib is bad at typing
        # SFA chunks are HCA the reader passes through still encrypted. Decode after demux.
        self.demux()
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
                if (language := ffmpeg_language_code(filenames[i])) is not None:
                    self.audio_language[k] = language
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


_LANGUAGES = {
    "jp": "ja",
    "cn": "zh",
    "ct": "yue",  # Cantonese
    "en": "en",
}


def ffmpeg_language_code(filename: str) -> str | None:
    """
    RFC 5646 code from a CRID audio filename like 10003_Audio_02_CT.wav.
    Single-track movies carry no token, so they get None.
    """
    m = re.search(r"_([a-z]{2})\.\w+$", filename.lower())
    return _LANGUAGES.get(m[1]) if m else None
