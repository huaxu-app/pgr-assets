import os.path
from typing import List

import UnityPy

import extractors
from sources import SourceSet


class CueSheet:
    id: int
    acb: str
    awb: str

    def __init__(self, id: int, acb: str, awb: str):
        self.id = id
        self.acb = acb
        self.awb = awb
        self.base_name = acb.split('/', 2)[2].split('.')[0].lower()


class CueRegistry:
    cues_by_acb: dict

    def __init__(self):
        self.cues_by_acb = {}

    def init(self, sources: SourceSet):
        env = UnityPy.load(sources.find_bundle('assets/temp/table/client/audio.ab'))
        cue_sheet_file = extractors.get_text_asset(env, 'assets/temp/table/client/audio/cuesheet.tab.bytes')

        cue_sheets = {int(id): CueSheet(int(id), acb, awb) for id, acb, awb, _ in
                      [line.split('\t') for line in cue_sheet_file.strip().split('\n')[1:]]}

        # Rekey the dict and use lower(acb) as key
        self.cues_by_acb = {cue_sheet.acb.lower(): cue_sheet for cue_sheet in cue_sheets.values()}

    def get_cue_sheet(self, acb: str) -> CueSheet:
        return self.cues_by_acb[acb.lower()]
