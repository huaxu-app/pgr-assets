AUDIO_DIR = "audio"


def sheet_base_name(acb: str) -> str:
    """Strip the Criware prefix and extension, preserving language folders."""
    return acb.split("/", 2)[2].split(".")[0].lower()


def cue_stem(cue_name: str) -> str:
    return cue_name.lower()


def cue_path(base_name: str, cue_name: str) -> str:
    return f"{AUDIO_DIR}/{base_name}/{cue_stem(cue_name)}"
