import logging
import os

from ffmpeg import FFmpeg

from . import BaseVideoEncoder, Track, check_encoder_available

logger = logging.getLogger(__name__)

language_names = {
    "ja": "Japanese",
    "en": "English",
    "zh": "Chinese",
    "yue": "Cantonese",
}


class HlsEncoder(BaseVideoEncoder):
    encoder: str = "h264"

    def setup(self):
        logger.debug("Checking for NVENC support")
        if check_encoder_available("h264_nvenc"):
            logger.debug("Found NVENC support")
            self.encoder = "h264_nvenc"

    def encode(self, base_output_path: str, video: list[Track], audio: list[Track]):
        stream_name = os.path.basename(base_output_path)
        stream_dir = os.path.join(
            os.path.dirname(base_output_path), "streams", stream_name
        )
        os.makedirs(stream_dir, exist_ok=True)

        ffmpeg = FFmpeg().option("y").option("hwaccel", "auto")

        var_stream_map = []
        audio_names: dict[int, str] = {}

        for i, v in enumerate(video):
            ffmpeg.input(v.path)
            var_stream_map.append(f"v:{i},name:video{i},agroup:audio")
        for i, a in enumerate(audio):
            ffmpeg.input(a.path)
            kvs = [f"a:{i}", "agroup:audio", f"default:{'yes' if i == 0 else 'no'}"]

            name = f"audio{i}"
            if a.language is not None:
                name = a.language
                kvs.append("language:" + a.language)
            kvs.append(f"name:{name}")
            audio_names[i] = language_names.get(name, name)

            var_stream_map.append(",".join(kvs))

        ffmpeg.output(
            os.path.join(stream_dir, "%v.m3u8"),
            {
                "c:v": self.encoder,
                "c:a": "aac",
                "b:a": "96k",
                "q:a": "2",
                "hls_time": "2",
                "hls_playlist_type": "vod",
                "master_pl_name": "master.m3u8",
                "hls_segment_filename": os.path.join(stream_dir, "%v.%d.ts"),
                "var_stream_map": " ".join(var_stream_map),
            },
            map=[str(i) for i in range(len(audio) + len(video))],
        )

        self._execute(ffmpeg)

        # Afterward, the names of the audio tracks are wrong. We gotta fix that.
        # See: https://trac.ffmpeg.org/ticket/11560
        master_path = os.path.join(stream_dir, "master.m3u8")
        with open(master_path, "r+") as f:
            content = f.read()

            for i, name in audio_names.items():
                content = content.replace(f"audio_{i + 1}", name)

            f.seek(0)
            f.write(content)
            f.truncate()
