# Heavily modified PyCriCodecs.ACBj
import logging
import os
import struct

from PyCriCodecs import UTF, AWB, UTFTypeValues, UTFType, HCA
from ffmpeg import FFmpeg

logger = logging.getLogger('audio.acb')


class ACB(UTF):
    """ An ACB is basically a giant @UTF table. Use this class to extract any ACB. """
    __slots__ = ["payload", "awb"]
    payload: list
    awb: AWB

    def __init__(self, acb, awb='') -> None:
        self.payload = UTF(acb).get_payload()
        if awb:
            self.awb = AWB(awb)
        else:
            self.awb = None
        self.acbparse(self.payload)

    def acbparse(self, payload: list) -> None:
        """ Recursively parse the payload. """
        for dict in range(len(payload)):
            for k, v in payload[dict].items():
                if v[0] == UTFTypeValues.bytes:
                    if v[1].startswith(
                            UTFType.UTF.value):  # or v[1].startswith(UTFType.EUTF.value): # ACB's never gets encrypted?
                        par = UTF(v[1]).get_payload()
                        payload[dict][k] = par
                        self.acbparse(par)
        self.load_awb()

    def load_awb(self) -> None:
        if self.awb is not None:
            return

        self.awb = AWB(self.payload[0]['AwbFile'][1])

    def get_waveform_for_cue_idx(self, idx: int) -> int|None:
        # Grab the synth reference
        cue_entry = self.payload[0]['CueTable'][idx]
        sequence_index = cue_entry['ReferenceIndex'][1]
        reference_type = cue_entry['ReferenceType'][1]
        # logger.debug(f"Cue[{idx}]: ReferenceType={reference_type}, ReferenceIndex={sequence_index}")
        if reference_type != 3:
            raise RuntimeError(f"Reference type {reference_type} not supported for cue {idx}")

        sequence = self.payload[0]['SequenceTable'][sequence_index]
        num_tracks = sequence['NumTracks'][1]
        if num_tracks == 0:
            return None
        track_index = struct.unpack('>H', sequence['TrackIndex'][1][:2])[0]
        # logger.debug(f"Sequence[{sequence_index}]: NumTracks={num_tracks}, TrackIndex={track_index}")

        track = self.payload[0]['TrackTable'][track_index]
        event_index = track['EventIndex'][1]
        # logger.debug(f"Track[{track_index}]: EventIndex={event_index}")

        track_event = self.payload[0]['TrackEventTable'][event_index]
        command = track_event['Command'][1]
        # Kinda unsure about this one
        synth_index = struct.unpack('<L', command[-4:])[0]
        # logger.debug(f"TrackEvent[{event_index}]: SynthIndex={synth_index}")

        synth_reference_items = self.payload[0]['SynthTable'][synth_index]['ReferenceItems'][1]
        waveform_index = struct.unpack('>H', synth_reference_items[2:])[0]
        # logger.debug(f"Synth[{sequence_index}]: Index={waveform_index}")

        waveform = self.payload[0]['WaveformTable'][waveform_index]
        streaming = waveform['Streaming'][1] > 0
        if streaming:
            waveform_id = waveform['StreamAwbId'][1]
        else:
            waveform_id = waveform['MemoryAwbId'][1]
        # logger.debug(f"Waveform[{waveform_index}]: Id={waveform_id}, Streaming={streaming}")
        return waveform_id

    def extract(self, key: int, dirname: str = "", encode=False):
        """ Extracts audio files in an AWB/ACB without preserving filenames. """
        if dirname:
            os.makedirs(dirname, exist_ok=True)

        # Have to do this because the index one is broken
        waveforms = list(self.awb.getfiles())

        tables = self.payload[0]

        for cue_id, cue_name_entry in enumerate(tables['CueNameTable']):
            cue_name = str(cue_name_entry['CueName'][1]).lower()
            cue_idx = cue_name_entry['CueIndex'][1]
            # logger.debug(f"CueName[{cue_id}]: CueIndex={cue_idx}, CueName={cue_name}")
            try:
                waveform_id = self.get_waveform_for_cue_idx(cue_idx)
                if waveform_id is None:
                    continue

                data = waveforms[waveform_id]
                audio = HCA(data, key=key, subkey=self.awb.subkey).decode()

                if encode:
                    ffmpeg = (FFmpeg()
                              .option('y')
                              .option('hwaccel', 'auto')
                              .input('pipe:0')
                              .output(os.path.join(dirname, cue_name + ".mp3"), {'c:a': 'libmp3lame', 'q:a': 2})
                              )

                    ffmpeg.execute(audio)
                else:
                    open(os.path.join(dirname, str(cue_name) + ".wav"), "wb").write(audio)
            except IndexError:
                logger.warning(f"Failed to extract {cue_name} with index {cue_idx}: waveform index out of range")

    def extract_old(self, decode: bool = False, key: int = 0, dirname: str = ""):
        """ Extracts audio files in an AWB/ACB without preserving filenames. """
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        filename = 0
        for i in self.awb.getfiles():
            print(filename, len(i))
            Extension: str = self.get_extension(self.payload[0]['WaveformTable'][filename]['EncodeType'][1])
            if decode and Extension == ".hca":
                hca = HCA(i, key=key, subkey=self.awb.subkey).decode()
                open(os.path.join(dirname, str(filename) + ".wav"), "wb").write(hca)
                filename += 1
            else:
                open(os.path.join(dirname, f"{filename}{Extension}"), "wb").write(i)
                filename += 1

    def get_extension(self, EncodeType: int) -> str:
        if EncodeType == 0 or EncodeType == 3:
            return ".adx"  # Maybe 0 is ahx?
        elif EncodeType == 2 or EncodeType == 6:
            return ".hca"
        elif EncodeType == 7 or EncodeType == 10:
            return ".vag"
        elif EncodeType == 8:
            return ".at3"
        elif EncodeType == 9:
            return ".bcwav"
        elif EncodeType == 11 or EncodeType == 18:
            return ".at9"
        elif EncodeType == 12:
            return ".xma"
        elif EncodeType == 13 or EncodeType == 4 or EncodeType == 5:
            return ".dsp"
        elif EncodeType == 19:
            return ".m4a"
        else:
            return ""
