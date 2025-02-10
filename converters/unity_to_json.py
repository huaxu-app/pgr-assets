from UnityPy import classes

def object_to_json(obj):
    if isinstance(obj, classes.PPtr):
        return f"PPtr({obj.path_id})"
    if isinstance(obj, classes.ComponentPair):
        return {
            '__type': type(obj).__name__,
            'component': object_to_json(obj.component)
        }
    elif isinstance(obj, classes.Object):
        return {
            '__type': type(obj).__name__,
            '__path_id': (None if obj.object_reader is None else obj.object_reader.path_id),
        } | {k: object_to_json(v) for k, v in obj.__dict__.items()}
    elif isinstance(obj, classes.Vector2f):
        return [obj.x, obj.y]
    elif isinstance(obj, classes.Vector3f):
        return [obj.x, obj.y, obj.z]
    elif isinstance(obj, classes.Vector4f):
        return [obj.x, obj.y, obj.z, obj.w]
    elif isinstance(obj, classes.Quaternionf):
        return [obj.x, obj.y, obj.z, obj.w]
    elif isinstance(obj, classes.ColorRGBA):
        return 'rgba(%d, %d, %d, %d)' % (obj.r, obj.g, obj.b, obj.a)
    elif isinstance(obj, classes.UnityPropertySheet):
        return {
            'm_Colors': None if obj.m_Colors is None else{k: object_to_json(v) for (k, v) in obj.m_Colors},
            'm_Floats': None if obj.m_Floats is None else {k: object_to_json(v) for (k, v) in obj.m_Floats},
            'm_Ints': None if obj.m_Ints is None else {k: object_to_json(v) for (k, v) in obj.m_Ints},
            'm_TexEnvs': None if obj.m_TexEnvs is None else {k: object_to_json(v) for (k, v) in obj.m_TexEnvs},
        }
    elif isinstance(obj, (list, tuple)):
        return [object_to_json(x) for x in obj]
    elif isinstance(obj, dict):
        return {k: object_to_json(v) for k, v in obj.items()}
    return obj

def jsonify(obj: classes.Object):
    seen = set()
    queue = [obj]
    output = {}

    while queue:
        obj = queue.pop(0)
        if isinstance(obj, classes.PPtr):
            if obj.path_id == 0 and obj.file_id == 0:
                continue

            if obj.path_id in seen:
                continue
            seen.add(obj.path_id)

            try:
                obj = obj.read()
            except AttributeError:
                continue
            except FileNotFoundError:
                continue

        if isinstance(obj, classes.ComponentPair):
            queue.append(obj.component)

        if isinstance(obj, classes.Object):
            path_id = None if obj.object_reader is None else obj.object_reader.path_id
            if path_id is None or path_id in output:
                continue
            jsony = object_to_json(obj)
            output[path_id] = jsony
            for k, v in obj.__dict__.items():
                if isinstance(v, (list, tuple)):
                    queue.extend(v)
                elif isinstance(v, dict):
                    queue.extend(v.values())
                else:
                    queue.append(v)

    return output

