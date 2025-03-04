
import UnityPy

from pgr_assets import extractors
from pgr_assets.sources import SourceSet
from pgr_assets.sources.sourceset import BlobNotFoundException


class CueSheet:
    id: int
    acb: str
    awb: str

    def __init__(self, id: int, acb: str, awb: str):
        self.id = id
        self.acb = acb
        self.awb = awb
        self.base_name = acb.split('/', 2)[2].split('.')[0].lower()


def get_cue_references(sources: SourceSet):
    try:
        source = 'table'
        separator = '\t'
        env = UnityPy.load(sources.find_bundle('assets/temp/table/client/audio.ab'))
    except BlobNotFoundException:
        source = 'bytes'
        separator = ','
        env = UnityPy.load(sources.find_bundle('assets/temp/bytes/client/audio.ab'))
    sheet = extractors.get_text_asset(env, f'assets/temp/{source}/client/audio/cuesheet.tab.bytes', allow_binary_table_convert=True)
    return (line.split(separator) for line in sheet.strip().splitlines(keepends=False)[1:])


class CueRegistry:
    cues_by_acb: dict

    def __init__(self):
        self.cues_by_acb = {}

    def init(self, sources: SourceSet):
        cue_sheets = {int(id): CueSheet(int(id), acb, awb) for id, acb, awb, _ in get_cue_references(sources)}

        # Rekey the dict and use lower(acb) as key
        self.cues_by_acb = {cue_sheet.acb.lower(): cue_sheet for cue_sheet in cue_sheets.values()}

    def get_cue_sheet(self, acb: str) -> CueSheet | None:
        return self.cues_by_acb.get(acb.lower(), None)
