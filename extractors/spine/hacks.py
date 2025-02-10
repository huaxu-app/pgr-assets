from .models import Spine

hack_db = {
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

}

def find_hack(name: str):
    import re
    for k, v in hack_db.items():
        if re.match(k, name):
            print(f"-> found hack {v}")
            return v
    return None

def apply_hack(spine: Spine):
    hack = find_hack(spine.name)
    if hack is None:
        return

    if hack.get('all_scale') is not None:
        for s in spine.spines:
            s.set_scale(hack['all_scale'])

    if hack.get('size') is not None:
        spine.found_size = hack['size']

    if hack.get('all_position') is not None:
        for s in spine.spines:
            s.position = hack['all_position']

