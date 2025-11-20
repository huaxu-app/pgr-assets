import dataclasses
import os
import tempfile
import typing
from ffmpeg import FFmpeg, FFmpegError

@dataclasses.dataclass
class Track:
    name: str
    path: str

    language: str | None = None

class BaseVideoEncoder(typing.Protocol):
    def setup(self):
        """
        Setup encoders. Only called when video encoding will be performed
        :return:
        """
        ...

    def encode(self, base_output_path: str, video: list[Track], audio: list[Track]):
        """
        Encode a video
        :param base_output_path: The target output path, without extensions
        :param video: Video tracks
        :param audio: AUdio tracks
        :return:
        """
        ...

def check_encoder_available(encoder: str):
    try:
        ffmpeg = FFmpeg().input("color=c=black:s=320x240:d=0.1", f="lavfi").output('-', f="null", vcodec=encoder)
        ffmpeg.execute()
        return True
    except FFmpegError as e:
        return False
