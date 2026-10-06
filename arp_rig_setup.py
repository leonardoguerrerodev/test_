"""
Auto-Rig Pro: ubica los huesos de referencia de un humanoide segun medidas.

Uso (Blender 3.x / 4.x con Auto-Rig Pro activado):
  1. Importa o abre tu modelo en pose T (o A). Pies en el suelo, de frente a -Y.
  2. Edita la seccion CONFIG (abajo). Todo lo que dejes en None se calcula con
     proporciones humanas a partir de `height`.
  3. Pestana Scripting > Open > este archivo > Run Script.

Pasos que hace el script:
  a) crea (o reutiliza) el armature de referencia de ARP
  b) coloca cada hueso `*_ref.*` segun las medidas
  c) opcional: Match to Rig y Bind

Convencion: Z arriba, personaje mirando a -Y, lado izquierdo del personaje = +X
(los huesos `.l` van en +X, igual que ARP).

Los nombres de huesos y operadores de ARP salen de memoria de la API de ARP
3.6x/3.7x. No se probo contra Blender. Si un hueso u operador no existe en tu
version, el script lo omite y lo lista al final. Ejecuta arp_dump_ref_bones.py
para ver los nombres reales de tu version.
"""

import math

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

# Objetos a riggear. Vacio = usa los meshes seleccionados.
MESH_NAMES = []

# Medidas en unidades de Blender. None = calcular desde `height`.
# Si height es None se toma de la altura del bounding box de los meshes.
MEASURES = {
    "height": None,          # altura total, pies a coronilla
    "hip_height": None,      # suelo -> articulacion de la cadera
    "knee_height": None,     # suelo -> rodilla
    "ankle_height": None,    # suelo -> tobillo
    "hip_width": None,       # distancia entre las dos caderas (centro a centro)
    "foot_length": None,     # talon -> punta del pie
    "foot_width": None,      # ancho del pie
    "knee_forward": None,    # cuanto avanza la rodilla en -Y (define el eje de flexion)
    "chest_height": None,    # suelo -> base del cuello
    "shoulder_height": None, # suelo -> articulacion del hombro
    "shoulder_width": None,  # distancia entre las dos articulaciones del hombro
    "neck_length": None,
    "upper_arm_length": None,
    "forearm_length": None,
    "hand_length": None,     # muneca -> punta del dedo medio
    "elbow_back": None,      # cuanto retrocede el codo en +Y
}

# Pose de brazos: 0 = pose T, ~35-45 = pose A (grados hacia abajo).
ARM_ANGLE_DEG = 0.0

# Centro del personaje en el suelo. None = centro del bounding box en X/Y y
# minimo en Z.
ORIGIN = None  # por ejemplo (0.0, 0.0, 0.0)

# Cantidad de huesos de columna. None = detectar los que trae el armature de ARP.
SPINE_COUNT = None

# Reutilizar un armature de referencia que ya este en la escena en lugar de
# crear otro.
USE_EXISTING_REF = False

# Pasos automaticos despues de colocar los huesos.
AUTO_MATCH_TO_RIG = False   # genera el rig final de ARP
AUTO_BIND = False           # solo se aplica si AUTO_MATCH_TO_RIG es True

# ---------------------------------------------------------------------------
# Calculo de posiciones (sin dependencia de bpy)
# ---------------------------------------------------------------------------


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _norm(a):
    n = math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)
    return (a[0] / n, a[1] / n, a[2] / n)


def _lerp(a, b, t):
    return _add(a, _mul(_sub(b, a), t))


def resolve_measures(measures, height):
    """Rellena los None con proporciones humanas (Drillis y Contini)."""
    H = measures.get("height") or height
    d = {
        "height": H,
        "hip_height": 0.530 * H,
        "knee_height": 0.285 * H,
        "ankle_height": 0.039 * H,
        "hip_width": 0.100 * H,
        "foot_length": 0.152 * H,
        "foot_width": 0.055 * H,
        "knee_forward": 0.008 * H,
        "chest_height": 0.818 * H,
        "shoulder_height": 0.818 * H,
        "shoulder_width": 0.230 * H,
        "neck_length": 0.050 * H,
        "upper_arm_length": 0.186 * H,
        "forearm_length": 0.146 * H,
        "hand_length": 0.108 * H,
        "elbow_back": 0.005 * H,
    }
    for k, v in measures.items():
        if v is not None:
            d[k] = v
    d["height"] = H
    return d


# Longitud de cada falange como fraccion de hand_length, y offset lateral
# (en unidades de 0.0105 * height, + hacia atras en Y).
FINGERS = {
    "index":  ([0.18, 0.12, 0.09], -1.5),
    "middle": ([0.20, 0.13, 0.10], -0.5),
    "ring":   ([0.19, 0.125, 0.095], 0.5),
    "pinky":  ([0.14, 0.09, 0.08], 1.5),
}
THUMB = [0.17, 0.13, 0.10]
PALM_FRACTION = 0.50      # el inicio de los dedos esta a esta fraccion de la mano
THUMB_ANGLE_DEG = 40.0    # apertura del pulgar hacia -Y


def compute_layout(m, spine_count=3, arm_angle_deg=0.0):
    """
    Devuelve {nombre_hueso: (head, tail)} con el origen en (0, 0, 0)
    y los pies en z = 0. Solo huesos del lado izquierdo (.l) y centrales (.x);
    el lado derecho se obtiene con mirror_layout().
    """
    H = m["height"]
    layout = {}

    # --- eje central ---------------------------------------------------
    hip_z = m["hip_height"]
    root_tail_z = hip_z + 0.06 * H
    layout["root_ref.x"] = ((0, 0, hip_z), (0, 0, root_tail_z))

    neck_base_z = m["chest_height"]
    spine_start = (0, 0, root_tail_z)
    spine_end = (0, 0, neck_base_z)
    for i in range(spine_count):
        a = _lerp(spine_start, spine_end, i / spine_count)
        b = _lerp(spine_start, spine_end, (i + 1) / spine_count)
        layout["spine_%02d_ref.x" % (i + 1)] = (a, b)

    head_base_z = neck_base_z + m["neck_length"]
    layout["neck_ref.x"] = ((0, 0, neck_base_z), (0, 0, head_base_z))
    layout["head_ref.x"] = ((0, 0, head_base_z), (0, 0, m["height"]))

    # --- pierna .l -----------------------------------------------------
    hx = m["hip_width"] / 2.0
    knee = (hx, -m["knee_forward"], m["knee_height"])
    ankle = (hx, 0.0, m["ankle_height"])
    layout["thigh_ref.l"] = ((hx, 0.0, hip_z), knee)
    layout["leg_ref.l"] = (knee, ankle)

    fl = m["foot_length"]
    heel_y = 0.27 * fl
    ball_y = heel_y - 0.70 * fl
    tip_y = heel_y - fl
    az = m["ankle_height"]
    ball = (hx, ball_y, 0.40 * az)
    tip = (hx, tip_y, 0.20 * az)
    layout["foot_ref.l"] = (ankle, ball)
    layout["toes_01_ref.l"] = (ball, tip)

    fw = m["foot_width"] / 2.0
    eps = 0.01 * fl
    layout["bank_01_ref.l"] = ((hx - fw, ball_y, 0.0), (hx - fw, ball_y - eps, 0.0))
    layout["bank_02_ref.l"] = ((hx + fw, ball_y, 0.0), (hx + fw, ball_y - eps, 0.0))
    layout["heel_ref.l"] = ((hx, heel_y, 0.0), (hx, heel_y - eps, 0.0))

    # --- brazo .l ------------------------------------------------------
    ang = math.radians(arm_angle_deg)
    d = (math.cos(ang), 0.0, -math.sin(ang))
    sx = m["shoulder_width"] / 2.0
    sz = m["shoulder_height"]
    shoulder_joint = (sx, 0.0, sz)
    clav_head = (0.02 * H, 0.0, sz + 0.01 * H)
    layout["shoulder_ref.l"] = (clav_head, shoulder_joint)

    elbow = _add(_add(shoulder_joint, _mul(d, m["upper_arm_length"])),
                 (0.0, m["elbow_back"], 0.0))
    wrist = _add(elbow, _mul(d, m["forearm_length"]))
    layout["arm_ref.l"] = (shoulder_joint, elbow)
    layout["forearm_ref.l"] = (elbow, wrist)
    hl = m["hand_length"]
    layout["hand_ref.l"] = (wrist, _add(wrist, _mul(d, PALM_FRACTION * hl)))

    # --- dedos .l ------------------------------------------------------
    knuckle_base = _add(wrist, _mul(d, PALM_FRACTION * hl))
    spacing = 0.0105 * H
    for name, (segs, lat) in FINGERS.items():
        p = _add(knuckle_base, (0.0, lat * spacing, 0.0))
        for i, frac in enumerate(segs):
            q = _add(p, _mul(d, frac * hl))
            layout["%s%d_ref.l" % (name, i + 1)] = (p, q)
            p = q

    t = math.radians(THUMB_ANGLE_DEG)
    td = _norm(_add(_mul(d, math.cos(t)), (0.0, -math.sin(t), 0.0)))
    p = _add(wrist, _add(_mul(d, 0.12 * hl), (0.0, -2.2 * spacing, 0.0)))
    for i, frac in enumerate(THUMB):
        q = _add(p, _mul(td, frac * hl))
        layout["thumb%d_ref.l" % (i + 1)] = (p, q)
        p = q

    return layout


def mirror_layout(layout):
    """Agrega los huesos .r reflejando en X los .l."""
    out = dict(layout)
    for name, (h, t) in layout.items():
        if name.endswith(".l"):
            flip = lambda v: (-v[0], v[1], v[2])
            out[name[:-2] + ".r"] = (flip(h), flip(t))
    return out


def translate_layout(layout, origin):
    return {n: (_add(h, origin), _add(t, origin)) for n, (h, t) in layout.items()}


# ---------------------------------------------------------------------------
# Parte Blender
# ---------------------------------------------------------------------------


def _world_bbox(objs):
    import bpy  # noqa: F401
    from mathutils import Vector
    pts = []
    for o in objs:
        pts.extend(o.matrix_world @ Vector(c) for c in o.bound_box)
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    zs = [p.z for p in pts]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _find_ref_armature():
    import bpy
    for o in bpy.data.objects:
        if o.type == "ARMATURE" and "root_ref.x" in o.data.bones:
            return o
    return None


def _append_ref_armature():
    import bpy
    before = {o.name for o in bpy.data.objects}
    last_err = None
    for rig_type in ("human", "humanoid"):
        try:
            bpy.ops.arp.append_arp(rig_type=rig_type)
            break
        except (TypeError, AttributeError, RuntimeError) as e:
            last_err = e
    else:
        raise RuntimeError(
            "No se pudo llamar bpy.ops.arp.append_arp. Esta activado Auto-Rig Pro? (%s)"
            % last_err)
    new = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before]
    for o in new:
        if o.type == "ARMATURE" and "root_ref.x" in o.data.bones:
            return o
    return _find_ref_armature()


def _detect_spine_count(arm):
    n = 0
    while "spine_%02d_ref.x" % (n + 1) in arm.data.bones:
        n += 1
    return n


def run():
    import bpy
    from mathutils import Vector

    if MESH_NAMES:
        meshes = [bpy.data.objects[n] for n in MESH_NAMES]
    else:
        meshes = [o for o in bpy.context.selected_objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("Selecciona el mesh del personaje o completa MESH_NAMES.")

    bb_min, bb_max = _world_bbox(meshes)
    origin = ORIGIN or ((bb_min[0] + bb_max[0]) / 2.0,
                        (bb_min[1] + bb_max[1]) / 2.0,
                        bb_min[2])
    height = bb_max[2] - bb_min[2]

    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    arm = _find_ref_armature() if USE_EXISTING_REF else None
    if arm is None:
        bpy.context.scene.cursor.location = Vector(origin)
        arm = _append_ref_armature()
    if arm is None:
        raise RuntimeError("No se encontro el armature de referencia (root_ref.x).")

    spine_count = SPINE_COUNT or _detect_spine_count(arm) or 3
    m = resolve_measures(MEASURES, height)
    layout = translate_layout(
        mirror_layout(compute_layout(m, spine_count, ARM_ANGLE_DEG)), origin)

    # El armature debe estar sin transformaciones para escribir coordenadas
    # de mundo directo sobre los huesos.
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    if any(abs(s - 1.0) > 1e-6 for s in arm.scale) or any(abs(r) > 1e-6 for r in arm.rotation_euler):
        print("AVISO: el armature tiene escala o rotacion; las posiciones pueden salir movidas.")
    inv = arm.matrix_world.inverted()

    bpy.ops.object.mode_set(mode="EDIT")
    ebones = arm.data.edit_bones
    missing = []
    placed = 0
    for name, (h, t) in layout.items():
        eb = ebones.get(name)
        if eb is None:
            missing.append(name)
            continue
        eb.head = inv @ Vector(h)
        eb.tail = inv @ Vector(t)
        placed += 1
    bpy.ops.object.mode_set(mode="OBJECT")

    print("Huesos de referencia colocados: %d" % placed)
    if missing:
        print("No existen en este armature (omitidos): " + ", ".join(sorted(missing)))
    print("Medidas usadas:")
    for k, v in sorted(m.items()):
        print("  %-18s %.4f" % (k, v))

    if AUTO_MATCH_TO_RIG:
        bpy.ops.object.select_all(action="DESELECT")
        arm.select_set(True)
        bpy.context.view_layer.objects.active = arm
        if not hasattr(bpy.ops.arp, "match_to_rig"):
            print("Esta version de ARP no expone bpy.ops.arp.match_to_rig. "
                  "Usa el boton Match to Rig.")
        else:
            bpy.ops.arp.match_to_rig()
            if AUTO_BIND:
                _bind(meshes)
    else:
        print("Revisa los huesos en el viewport y pulsa Match to Rig en el panel de ARP.")


def _bind(meshes):
    import bpy
    rig = None
    for o in bpy.data.objects:
        if o.type == "ARMATURE" and "c_traj" in o.data.bones:
            rig = o
            break
    if rig is None:
        print("No se encontro el rig generado; omito el bind.")
        return
    bpy.ops.object.select_all(action="DESELECT")
    for me in meshes:
        me.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    for op_name in ("bind_to_rig", "bind"):
        op = getattr(bpy.ops.arp, op_name, None)
        if op is not None:
            op()
            print("Bind hecho con bpy.ops.arp.%s" % op_name)
            return
    print("No se encontro un operador de bind en ARP. Haz el bind desde la pestana Skin.")


if __name__ == "__main__":
    run()
