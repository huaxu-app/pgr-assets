import os
import tempfile
from typing import Union

import PyCriCodecs
from ffmpeg import FFmpeg


class PGRUSM(PyCriCodecs.USM):
    audio_language: dict[str,str] = {}

    def __init__(self, filename, key: Union[str, int, bool] = False):
        super().__init__(filename, key)
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

        filenames = self.CRIDObj.table.get('filename', [])
        i = 1
        for k, v in self.output.items():
            if k.startswith("@SFA_"):
                self.output[k] = PyCriCodecs.HCA(v, key=self.key).decode()
                self.audio_language[k] = ffmpeg_language_code(filenames[i])
            i += 1


    def extract_video(self, outfile: str, recode=False, nvenc=False):
        self.stream.seek(0)
        if not self.demuxed:
            self.demux()

        # Create dir if not exists
        os.makedirs(os.path.dirname(outfile), exist_ok=True)

        with tempfile.TemporaryDirectory() as tempdir:
            metadata = {}
            mapping = []
            audio_track_number = 0
            files = []
            for i, (k, v) in enumerate(self.output.items()):
                # I'm not sure what this is... ffmpeg doesn't either
                if k.startswith("@SBT_"):
                    continue

                path = os.path.join(tempdir, k)
                with open(path, "wb") as f:
                    f.write(v)
                files.append(path)

                if '@SFA' in k:
                    mapping.append(f"{i}:a")
                    metadata[f'metadata:s:a:{audio_track_number}'] = 'language=' + self.audio_language[k]
                    audio_track_number += 1
                elif '@SFV' in k:
                    mapping.append(f"{i}:v")

            # FFMPEG the shit out of it
            ffmpeg = FFmpeg().option("y").option("hwaccel", "auto")

            for i, f in enumerate(files):
                ffmpeg.input(f)

            encoder = "copy"
            if recode and nvenc:
                encoder = "h264_nvenc"
            elif recode:
                encoder = "h264"

            ffmpeg.output(
                outfile,
                {
                    "c:v": encoder,
                    "movflags": "+faststart",
                    "c:a": "mp3",
                    "ar": "44100",
                    "q:a": "2",
                    **metadata,
                },
                map=mapping,
            )
            ffmpeg.execute()

def ffmpeg_language_code(text: str) -> str | None:
    """
    Detect language tag inside a string and return the
    correct FFmpeg ISO-639-2 language code.
    """

    text_lower = text.lower()

    mapping = {
        "jp": "jpn",     # Japanese
        "en": "eng",     # English
        "cn": "zho",     # Chinese (Simplified/Mandarin)
        "ct": "yue",     # Cantonese (Traditional Chinese audio)
    }

    for key, code in mapping.items():
        if key in text_lower:
            return code

    return None
