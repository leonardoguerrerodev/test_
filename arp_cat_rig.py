"""
Auto-Rig Pro (preset Dog): coloca los huesos de referencia del gato "Mao".

Las posiciones salen de las medidas del mesh (mao_unrigged_medidas.json) y del
rig de referencia que ya tenias (mao_ref_medidas.json):
  - Columna, cuello, cabeza, cola y patas traseras: se conservan de tu rig,
    porque coinciden con el mesh (corvejon y=0.50, rodilla y=0.27, pata
    trasera apoyada en y 0.36-0.49).
  - Patas delanteras (*_dupli_001): recalculadas. En tu rig tenian la cola de
    thigh_b en y=0.25 (zona de las patas traseras) y thigh_ref terminando en
    z=1.0 (sobre el lomo).
  - foot_bank_* y foot_heel_* de las cuatro patas: recalculados sobre el suelo
    (z=0). En tu rig las traseras estaban en z=0.33.

Uso en Blender (con Auto-Rig Pro activado):
  1. Abre el .blend con el mesh "Mao".
  2. Ajusta la seccion CONFIG.
  3. Scripting > Open > este archivo > Run Script.
  4. Revisa los huesos en el viewport y pulsa Match to Rig en el panel de ARP
     (o pon AUTO_MATCH_TO_RIG = True).

Convencion: Z arriba, el gato mira a -Y, el lado .l esta en +X.

Los nombres de huesos salen de tu JSON. Los operadores bpy.ops.arp.* salen de
memoria de la API de ARP y no se probaron contra Blender: si alguno no existe
en tu version, el script lo avisa y sigue.
"""

import math

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

# Nombre del mesh. Si no existe se usan los meshes seleccionados.
MESH_NAMES = ["Mao"]

# El mesh del archivo sin rig tiene escala 0.000116. ARP necesita la escala
# aplicada para el bind. True = Ctrl+A > Scale sobre el mesh si hace falta.
APPLY_MESH_SCALE = True

# Reutilizar un armature con huesos *_ref que no haya sido generado todavia.
USE_EXISTING_REF = True

# Tu escena tiene un rig ya generado ("rig", con c_traj). ARP no deja editar
# los huesos de referencia de un rig generado. True = borrar ese armature y
# crear uno nuevo con el preset Dog. False = el script se detiene y lo explica.
DELETE_OLD_RIG = False

AUTO_MATCH_TO_RIG = False   # ejecuta Match to Rig al terminar
AUTO_BIND = False           # solo si AUTO_MATCH_TO_RIG es True

# ---------------------------------------------------------------------------
# Medidas del mesh de referencia (de mao_unrigged_medidas.json)
# ---------------------------------------------------------------------------

REF_BBOX_MIN = (-0.2180, -0.9539, -0.0024)
REF_BBOX_MAX = (0.2166, 0.9509, 1.2516)
CENTER_X = -0.0007  # eje de simetria

# ---------------------------------------------------------------------------
# Huesos. {nombre: (head, tail)} en coordenadas del mesh de referencia.
# Solo el eje central (.x) y el lado izquierdo (.l); el .r se crea por espejo.
# ---------------------------------------------------------------------------

X = CENTER_X

# Conservado de tu rig: coincide con el mesh.
KEPT = {
    "root_ref.x":     ((X, 0.3570, 0.8090), (X, 0.1408, 0.8571)),
    "spine_01_ref.x": ((X, 0.1408, 0.8571), (X, -0.0810, 0.8660)),
    "spine_02_ref.x": ((X, -0.0810, 0.8660), (X, -0.3030, 0.8634)),
    "spine_03_ref.x": ((X, -0.3030, 0.8634), (X, -0.5250, 0.8660)),
    "neck_ref.x":     ((X, -0.5250, 0.8660), (X, -0.7100, 0.9730)),
    "head_ref.x":     ((X, -0.7100, 0.9730), (X, -0.9450, 0.9360)),
    "tail_00_ref.x":  ((X, 0.4130, 0.8430), (X, 0.5600, 0.7600)),
    "tail_01_ref.x":  ((X, 0.5600, 0.7600), (X, 0.7180, 0.6910)),
    "tail_02_ref.x":  ((X, 0.7180, 0.6910), (X, 0.8650, 0.6510)),
    "tail_03_ref.x":  ((X, 0.8650, 0.6510), (X, 0.9510, 0.6370)),
    # pata trasera izquierda
    "thigh_b_ref.l":  ((0.1290, 0.4784, 0.7294), (0.1190, 0.4933, 0.5015)),
    "thigh_ref.l":    ((0.1190, 0.4933, 0.5015), (0.1293, 0.2700, 0.3750)),
    "leg_ref.l":      ((0.1293, 0.2700, 0.3750), (0.0993, 0.5040, 0.2470)),
    "foot_ref.l":     ((0.0993, 0.5040, 0.2470), (0.0933, 0.4650, 0.0430)),
    "toes_ref.l":     ((0.0933, 0.4650, 0.0430), (0.0933, 0.3750, 0.0130)),
}

# Recalculado desde el mesh. Huella de las patas (ground_contacts del JSON):
#   trasera x 0.031-0.147, y 0.362-0.493 | delantera x 0.022-0.132, y -0.681..-0.528
# Banks: x del centro de la huella +/- medio ancho. bank_01 = lado externo,
# igual que en tu rig (x mayor en el .l).
RECALC = {
    # pata trasera: solo apoyo en el suelo
    "foot_heel_ref.l":    ((0.0935, 0.4950, 0.0), (0.0935, 0.4700, 0.0)),
    "foot_bank_01_ref.l": ((0.1515, 0.4400, 0.0), (0.1515, 0.4150, 0.0)),
    "foot_bank_02_ref.l": ((0.0355, 0.4400, 0.0), (0.0355, 0.4150, 0.0)),
    # pata delantera izquierda
    "thigh_b_ref_dupli_001.l":  ((0.1100, -0.4700, 0.7800), (0.1300, -0.5300, 0.5500)),
    "thigh_ref_dupli_001.l":    ((0.1300, -0.5300, 0.5500), (0.1400, -0.4000, 0.4400)),
    "leg_ref_dupli_001.l":      ((0.1400, -0.4000, 0.4400), (0.1000, -0.5450, 0.1900)),
    "foot_ref_dupli_001.l":     ((0.1000, -0.5450, 0.1900), (0.0820, -0.5850, 0.0450)),
    "toes_ref_dupli_001.l":     ((0.0820, -0.5850, 0.0450), (0.0820, -0.6770, 0.0120)),
    "foot_heel_ref_dupli_001.l":    ((0.0820, -0.5350, 0.0), (0.0820, -0.5600, 0.0)),
    "foot_bank_01_ref_dupli_001.l": ((0.1370, -0.5850, 0.0), (0.1370, -0.6100, 0.0)),
    "foot_bank_02_ref_dupli_001.l": ((0.0270, -0.5850, 0.0), (0.0270, -0.6100, 0.0)),
}


def build_layout():
    """Une las tablas y crea el lado derecho espejando en X."""
    left_and_axis = dict(KEPT)
    left_and_axis.update(RECALC)
    out = dict(left_and_axis)
    for name, (h, t) in left_and_axis.items():
        if name.endswith(".l"):
            mir = lambda v: (2 * CENTER_X - v[0], v[1], v[2])
            out[name[:-2] + ".r"] = (mir(h), mir(t))
    return out


def fit_transform(actual_min, actual_max):
    """
    Devuelve una funcion que lleva coordenadas del mesh de referencia al mesh
    actual: escala uniforme por el largo en Y, centro en X/Y y suelo en Z.
    Si el mesh no se movio es la identidad.
    """
    ref_len = REF_BBOX_MAX[1] - REF_BBOX_MIN[1]
    s = (actual_max[1] - actual_min[1]) / ref_len
    ref_cx = (REF_BBOX_MIN[0] + REF_BBOX_MAX[0]) / 2.0
    ref_cy = (REF_BBOX_MIN[1] + REF_BBOX_MAX[1]) / 2.0
    cx = (actual_min[0] + actual_max[0]) / 2.0
    cy = (actual_min[1] + actual_max[1]) / 2.0

    def f(p):
        return ((p[0] - ref_cx) * s + cx,
                (p[1] - ref_cy) * s + cy,
                (p[2] - REF_BBOX_MIN[2]) * s + actual_min[2])
    return f, s


def transformed_layout(actual_min, actual_max):
    f, s = fit_transform(actual_min, actual_max)
    layout = {n: (f(h), f(t)) for n, (h, t) in build_layout().items()}
    return layout, s


# ---------------------------------------------------------------------------
# Parte Blender
# ---------------------------------------------------------------------------


def _get_meshes():
    import bpy
    meshes = [bpy.data.objects[n] for n in MESH_NAMES
              if n in bpy.data.objects and bpy.data.objects[n].type == "MESH"]
    if not meshes:
        meshes = [o for o in bpy.context.selected_objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("No se encontro el mesh. Revisa MESH_NAMES o selecciona el mesh.")
    return meshes


def _select_only(obj):
    import bpy
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _apply_scale(meshes):
    import bpy
    for me in meshes:
        if all(abs(s - 1.0) < 1e-6 for s in me.scale):
            continue
        print("Aplicando escala de '%s' (escala %s)" % (me.name, tuple(round(s, 6) for s in me.scale)))
        _select_only(me)
        try:
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        except RuntimeError as e:
            print("No se pudo aplicar la escala de '%s' (datos compartidos?): %s" % (me.name, e))


def _world_bbox(meshes):
    from mathutils import Vector
    pts = []
    for o in meshes:
        pts.extend(o.matrix_world @ Vector(c) for c in o.bound_box)
    lo = tuple(min(p[i] for p in pts) for i in range(3))
    hi = tuple(max(p[i] for p in pts) for i in range(3))
    return lo, hi


def _ref_armatures():
    import bpy
    return [o for o in bpy.data.objects
            if o.type == "ARMATURE" and "root_ref.x" in o.data.bones]


def _is_generated(arm):
    return "c_traj" in arm.data.bones


def _append_ref_armature():
    import bpy
    before = set(bpy.data.objects.keys())
    last_err = None
    for rig_type in ("dog", "quadruped"):
        try:
            bpy.ops.arp.append_arp(rig_type=rig_type)
            break
        except (TypeError, AttributeError, RuntimeError) as e:
            last_err = e
    else:
        raise RuntimeError(
            "No se pudo crear el armature con bpy.ops.arp.append_arp. Activa Auto-Rig Pro "
            "o agrega el preset Dog a mano y vuelve a correr con USE_EXISTING_REF = True. (%s)"
            % last_err)
    for n in bpy.data.objects.keys():
        if n not in before and bpy.data.objects[n].type == "ARMATURE":
            return bpy.data.objects[n]
    found = _ref_armatures()
    return found[0] if found else None


def _prepare_armature():
    import bpy
    candidates = _ref_armatures()
    generated = [a for a in candidates if _is_generated(a)]
    fresh = [a for a in candidates if not _is_generated(a)]

    if generated:
        if not DELETE_OLD_RIG:
            raise RuntimeError(
                "'%s' ya es un rig generado por ARP: sus huesos de referencia no se pueden "
                "editar asi. Opciones: (a) pulsa 'Edit Reference Bones' en el panel de ARP y "
                "corre el script otra vez, o (b) pon DELETE_OLD_RIG = True para borrarlo y "
                "crear uno nuevo con el preset Dog." % generated[0].name)
        for a in generated:
            print("Borrando rig generado '%s'" % a.name)
            bpy.data.objects.remove(a, do_unlink=True)

    if USE_EXISTING_REF and fresh:
        return fresh[0]
    return _append_ref_armature()


def run():
    import bpy
    from mathutils import Vector

    meshes = _get_meshes()
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    if APPLY_MESH_SCALE:
        _apply_scale(meshes)

    bb_min, bb_max = _world_bbox(meshes)
    layout, s = transformed_layout(bb_min, bb_max)
    print("Bounding box del mesh: min=%s max=%s" % (
        tuple(round(v, 4) for v in bb_min), tuple(round(v, 4) for v in bb_max)))
    if abs(s - 1.0) > 0.01:
        print("AVISO: el mesh mide %.1f%% del mesh de referencia en Y; las posiciones se escalaron." % (s * 100))

    arm = _prepare_armature()
    if arm is None:
        raise RuntimeError("No se encontro el armature de referencia (root_ref.x).")
    if arm.hide_get():
        arm.hide_set(False)
    arm.hide_viewport = False
    _select_only(arm)

    if any(abs(v - 1.0) > 1e-6 for v in arm.scale) or any(abs(r) > 1e-6 for r in arm.rotation_euler):
        print("AVISO: el armature tiene escala o rotacion; aplicalas (Ctrl+A) y repite si las posiciones salen movidas.")
    inv = arm.matrix_world.inverted()

    # Con simetria X activa, mover un hueso .l mueve tambien el .r.
    mirror_state = arm.data.use_mirror_x
    arm.data.use_mirror_x = False

    bpy.ops.object.mode_set(mode="EDIT")
    ebones = arm.data.edit_bones
    missing, placed = [], 0
    for name, (h, t) in layout.items():
        eb = ebones.get(name)
        if eb is None:
            missing.append(name)
            continue
        eb.head = inv @ Vector(h)
        eb.tail = inv @ Vector(t)
        placed += 1
    unplaced = [eb.name for eb in ebones if "_ref" in eb.name and eb.name not in layout]
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.data.use_mirror_x = mirror_state

    print("Huesos de referencia colocados: %d de %d" % (placed, len(layout)))
    if missing:
        print("No existen en este armature (omitidos): " + ", ".join(sorted(missing)))
    if unplaced:
        print("Huesos *_ref del armature que este script no coloca: " + ", ".join(sorted(unplaced)))

    if AUTO_MATCH_TO_RIG:
        _select_only(arm)
        if not hasattr(bpy.ops.arp, "match_to_rig"):
            print("Esta version de ARP no expone bpy.ops.arp.match_to_rig. Usa el boton Match to Rig.")
        else:
            bpy.ops.arp.match_to_rig()
            if AUTO_BIND:
                _bind(meshes)
    else:
        print("Revisa los huesos y pulsa Match to Rig en el panel de ARP.")


def _bind(meshes):
    import bpy
    rigs = [o for o in bpy.data.objects if o.type == "ARMATURE" and _is_generated(o)]
    if not rigs:
        print("No se encontro el rig generado; omito el bind.")
        return
    bpy.ops.object.select_all(action="DESELECT")
    for me in meshes:
        me.select_set(True)
    rigs[0].select_set(True)
    bpy.context.view_layer.objects.active = rigs[0]
    for op_name in ("bind_to_rig", "bind"):
        op = getattr(bpy.ops.arp, op_name, None)
        if op is not None:
            op()
            print("Bind hecho con bpy.ops.arp.%s" % op_name)
            return
    print("No se encontro un operador de bind en ARP. Haz el bind desde la pestana Skin.")


if __name__ == "__main__":
    run()
