import os
import tempfile
from typing import Union

import PyCriCodecs
from ffmpeg import FFmpeg


class PGRUSM(PyCriCodecs.USM):
    def __init__(self, filename, key: Union[str, int, bool] = False):
        super().__init__(filename, key)
        self.key = key

    def reader(self, chuncksize, offset, padding, header) -> bytearray:
        """ Chunks reader function, reads all data in a chunk and returns a bytearray. """
        # CURSED OVERRIDE OF READER FN
        # WHATEVER THIS LIB DOES, IT'S DOING SFA WRONG. PGR IS USING HCA
        # Hotpatch function to not decrypt audio data, and hook into demux to do full decrypt afterwards
        data = bytearray(self.stream.read(chuncksize)[offset:])
        if header == PyCriCodecs.USMChunckHeaderType.SFV.value or header == PyCriCodecs.USMChunckHeaderType.ALP.value:
            data = self.VideoMask(data) if self.decrypt else data
        elif header == PyCriCodecs.USMChunckHeaderType.SFA.value:
            data = data  # don't decrypt data
        if padding:
            data = data[:-padding]
        return data

    def demux(self) -> None:
        super().demux()
        # Hotpatch to decrypt SFA chunks as HCA
        for k, v in self.output.items():
            if k.startswith('@SFA_'):
                self.output[k] = PyCriCodecs.HCA(v, key=self.key).decode()

    def extract_video(self, outfile: str, recode=False):
        self.stream.seek(0)
        if not self.demuxed:
            self.demux()

        # Create dir if not exists
        os.makedirs(os.path.dirname(outfile), exist_ok=True)

        with tempfile.TemporaryDirectory() as tempdir:
            files = []
            for k, v in self.output.items():
                # I'm not sure what this is... ffmpeg doesn't either
                if k.startswith('@SBT_'):
                    continue

                path = os.path.join(tempdir, k)
                with open(path, "wb") as f:
                    f.write(v)
                files.append(path)

            # FFMPEG the shit out of it
            ffmpeg = FFmpeg().option('y').option('hwaccel', 'auto')
            for f in files:
                ffmpeg.input(f)
            ffmpeg.output(outfile, {
                "c:v": "h264" if recode else "copy",
                "movflags": "faststart" if recode else "",
                "c:a": "mp3",
                "ar": "44100",
                "q:a": "2",
            })
            ffmpeg.execute()
