import logging
import os

from ffmpeg import FFmpeg

from . import BaseVideoEncoder, Track, check_encoder_available

logger = logging.getLogger(__name__)


class WebMp4Encoder(BaseVideoEncoder):
    encoder: str = "h264"

    def setup(self):
        logger.debug("Checking for NVENC support")
        if check_encoder_available("h264_nvenc"):
            logger.debug("Found NVENC support")
            self.encoder = "h264_nvenc"

    def encode(self, base_output_path: str, video: list[Track], audio: list[Track]):
        output_file = base_output_path + ".mp4"
        os.makedirs(os.path.dirname(output_file), exist_ok=True)

        meta = {}
        ffmpeg = FFmpeg().option("y").option("hwaccel", "auto")

        for v in video:
            ffmpeg.input(v.path)
        for i, a in enumerate(audio):
            ffmpeg.input(a.path)
            if a.language is not None:
                meta[f"metadata:s:a:{i}"] = "language=" + a.language

        ffmpeg.output(
            output_file,
            {
                "c:v": self.encoder,
                "movflags": "+faststart",
                "c:a": "mp3",
                "ar": "44100",
                "q:a": "2",
                **meta,
            },
            map=[str(i) for i in range(len(audio) + len(video))],
        )

        self._execute(ffmpeg)
