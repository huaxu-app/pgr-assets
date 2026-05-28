import logging
import os
import tempfile
from typing import Union, cast, Any
import PyCriCodecs

from pgr_assets.extractors.video_encoders import BaseVideoEncoder, Track

logger = logging.getLogger(__name__)


class PGRUSM(PyCriCodecs.USM):
    audio_language: dict[str, str] = {}

    def __init__(self, filename, key: Union[str, int, bool] = False):
        super().__init__(filename, cast(str, key)) # bad cast, but PyCriCodecs is bad at typing
        self.key = key

    def reader(self, chuncksize, offset, padding, header) -> bytearray:
        """Chunks reader function, reads all data in a chunk and returns a bytearray."""
        # CURSED OVERRIDE OF READER FN
        # WHATEVER THIS LIB DOES, IT'S DOING SFA WRONG. PGR IS USING HCA
        # Hotpatch function to not decrypt audio data, and hook into demux to do full decrypt afterwards
        data = bytearray(self.stream.read(chuncksize)[offset:])
        if (
            header == PyCriCodecs.USMChunckHeaderType.SFV.value
            or header == PyCriCodecs.USMChunckHeaderType.ALP.value
        ):
            data = self.VideoMask(data) if self.decrypt else data
        elif header == PyCriCodecs.USMChunckHeaderType.SFA.value:
            data = data  # don't decrypt data
        if padding:
            data = data[:-padding]
        return data

    # Hotpatch to decrypt SFA chunks as HCA
    def demux(self) -> None:
        super().demux()

        filenames = self.CRIDObj.table.get("filename", [])
        i = 1
        for k, v in self.output.items():
            if k.startswith("@SFA_"):
                self.output[k] = PyCriCodecs.HCA(
                    cast(Any, v), # cast: it gets passed to bytearray, which accepts bytes too
                    key=cast(Any, self.key) # cast: this is fine, but again... PyCriCodecs
                ).decode()
                self.audio_language[k] = ffmpeg_language_code(filenames[i])
            i += 1

    def extract_video(self, base_outfile: str, encoders: list[BaseVideoEncoder]):
        self.stream.seek(0)
        if not self.demuxed:
            self.demux()

        with tempfile.TemporaryDirectory() as tempdir:
            videos: list[Track] = []
            audios: list[Track] = []

            for i, (k, v) in enumerate(self.output.items()):
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
