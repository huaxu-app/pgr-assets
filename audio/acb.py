# Heavily modified PyCriCodecs.ACBj
import logging
import os
import struct

from PyCriCodecs import UTF, AWB, UTFTypeValues, UTFType, HCA

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

    def get_waveform_for_cue_idx(self, idx: int) -> int:
        # Grab the synth reference
        synth_idx = self.payload[0]['CueTable'][idx]['ReferenceIndex'][1]
        waveform_reference = self.payload[0]['SynthTable'][synth_idx]['ReferenceItems'][1]
        return struct.unpack('>H', waveform_reference[2:])[0]

    def extract(self, decode: bool = False, key: int = 0, dirname: str = ""):
        """ Extracts audio files in an AWB/ACB without preserving filenames. """
        if dirname:
            os.makedirs(dirname, exist_ok=True)

        # Have to do this because the index one is broken
        waveforms = list(self.awb.getfiles())

        for cue_name_entry in self.payload[0]['CueNameTable']:
            cue_name = cue_name_entry['CueName'][1]
            cue_idx = cue_name_entry['CueIndex'][1]
            try:
                waveform_reference_idx = self.get_waveform_for_cue_idx(cue_idx)

                ext = self.get_extension(self.payload[0]['WaveformTable'][waveform_reference_idx]['EncodeType'][1])
                data = waveforms[waveform_reference_idx]

                if decode and ext == ".hca":
                    hca = HCA(data, key=key, subkey=self.awb.subkey).decode()
                    open(os.path.join(dirname, str(cue_name) + ".wav"), "wb").write(hca)
                else:
                    open(os.path.join(dirname, f"{cue_name}{ext}"), "wb").write(data)
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
