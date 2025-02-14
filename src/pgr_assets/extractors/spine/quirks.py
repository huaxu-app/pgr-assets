import dataclasses
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
    'luolan/luolantutorial/luolantutorial': { 'all_scale': 0.26, 'all_position': (0, 5) },
    'nier-2bskin/spinenier2bskin1': { 'all_scale': 0.33, 'all_position': (40, -20) },

    'uispine/uiturntable/uiturntablesailikacall': { 'size': (512, 512) },
    'uilivwarmactivityvinylspine': { 'size': (200, 200) },

    '2-11spine/lamiyaskin/lamiyaskinautowindow': { 'all_scale': 0.45, 'size': (1518, 856) },
    'lifu/chaolifudarkskin/chaolifudarkskinwindow': { 'size': (1518, 856) },
    'luciya/luciyasairen/luciyasairendrawcoating': { 'size': (1518, 856) },
    'luxiya-skin-qingrenjie/spineluxiyaskin': { 'size': (1518, 856) },
    '.*autowindow': { 'size': (1518, 856) },

    'selena/selenaactivity': { 'all_scale': 0.5 },
    'activityspine/activitybianka/activitybianka$': { 'all_scale': 0.3, 'render': 'short' },
    'activityspine/activitybuouxiong/activitybuouxiong': { 'all_position':  (0, 0) },
    'activityspine/activityhanying/activityhanying': { 'all_scale': 0.5 },
    'activityspine/activityli/activitylifuben': { 'all_scale': 0.5 },
    'activityspine/activity21/activity21': { 'all_scale': 0.26 },
    'activityspine/activityspinechunjieqishi': { 'render': 'short' },

    'uispine/uigoldenminerspine': { 'all_scale': 0.14, 'size': (100, 100) },
    '2-12spine/uihitmouse2-12spine': { 'all_scale': 1, 'size': (1000, 1000), 'all_pivot': (0.5, 0.5) },
    'uihitmousespine': { 'all_scale': 1, 'size': (1000, 1000), 'all_pivot': (0.5, 0.5) },

    # Very old login screens
    r'spinelogin/1.18': { 'size': (1920, 1080), 'all_pivot': (0.5, 0.5), 'all_position': (6, 20) },
    r'spinelogin/1.21': { 'size': (1920, 1080), 'all_pivot': (0.5, 0.5), 'all_position': (0, -90) },
    r'spinelogin/1.22': { 'size': (1920, 1080), 'all_pivot': (0.5, 0.5), 'all_position': (0, 40) },
    r'spinelogin/1\.*': { 'size': (1920, 1080), 'all_pivot': (0.5, 0.5) },
}

@dataclasses.dataclass
class GlueQuirk:
    name: str
    # Things that should be together, but aren't. In order
    layers: list[str]

quirks_glue = {
    'selena/selenaactivity/selenaactivitybg': GlueQuirk('selena/selenaactivity', [ 'selena/selenaactivity/selenaactivitybg', 'selena/selenaactivity/selenaactivityqg' ]),
    'activityspine/activityspineyuandan/activityspineyuandanbg': GlueQuirk('activityspine/activityspineyuandan', [ 'activityspine/activityspineyuandan/activityspineyuandanbg', 'activityspine/activityspineyuandan/activityspineyuandanqg' ]),
    'activityspine/activityspinechunjieqishi/activityqishibg':  GlueQuirk('activityspine/activityspinechunjieqishi', [ 'activityspine/activityspinechunjieqishi/activityqishibg', 'activityspine/activityspinechunjieqishi/activityqishirole', 'activityspine/activityspinechunjieqishi/activityqishiqg' ]),
    'activityspine/activityhakama/activityhakamabg': GlueQuirk('activityspine/activityhakama', [ 'activityspine/activityhakama/activityhakamabg', 'activityspine/activityhakama/activityhakamaqg' ]),
}


quirks_skip = set(layer for quirk in quirks_glue.values() for layer in quirk.layers if layer not in quirks_glue)

def find_quirk(name: str) -> dict|None:
    import re
    for k, v in quirks.items():
        if re.match(k, name):
            logger.debug(f'Applying quirk {v}')
            return v
    return None

def apply_quirk(spine: Spine) -> None:
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

    if quirk.get('render') is not None:
        spine.render_quirk = quirk['render']

def should_skip(name: str) -> bool:
    return name in quirks_skip

def find_glue(name: str) -> GlueQuirk|None:
    return quirks_glue.get(name, None)

