import logging

from .models import Spine

logger = logging.getLogger('spine-extractor')

quirks = {
    # Beeg Celica has no size
    'sailika/sailika$': { 'size': (1520, 6340)},
    'sailika/sailika2-rpgmakergame': { 'size': (256, 256)},

    'kuluomu/kuluomu_tutorial/kuluomu_tutorial': { 'all_scale': 0.5, 'all_position': (10, -15) },
    'main13_spine_luciya/main13_spine_luciya': { 'all_scale': 0.5, 'all_position': (0, -2) },
    'main13_spine_luna/main13_spine_luna': { 'all_scale': 0.65 },

    'uispine/uiturntable/uiturntablesailikacall': { 'size': (512, 512) },
    'uilivwarmactivityvinylspine': { 'size': (200, 200) },

    '2-11spine/lamiyaskin/lamiyaskinautowindow': { 'all_scale': 0.45, 'size': (1518, 856) },
    'lifu/chaolifudarkskin/chaolifudarkskinwindow': { 'size': (1518, 856) },
    'luciya/luciyasairen/luciyasairendrawcoating': { 'size': (1518, 856) },
    'luxiya-skin-qingrenjie/spineluxiyaskin': { 'size': (1518, 856) },
    '.*autowindow': { 'size': (1518, 856) },

    # Very old login screens
    r'spinelogin/1\.*': { 'size': (1920, 1080), 'all_pivot': (0.5, 0.5) },
}

def find_quirk(name: str):
    import re
    for k, v in quirks.items():
        if re.match(k, name):
            logger.debug(f'Applying quirk {v}')
            return v
    return None

def apply_quirk(spine: Spine):
    quirk = find_quirk(spine.name)
    if quirk is None:
        return

    if quirk.get('all_scale') is not None:
        for s in spine.spines:
            s.set_scale(quirk['all_scale'])

    if quirk.get('size') is not None:
        spine.found_size = quirk['size']

    if quirk.get('all_position') is not None:
        for s in spine.spines:
            s.position = quirk['all_position']

    if quirk.get('all_pivot') is not None:
        for s in spine.spines:
            s.pivot = quirk['all_pivot']

