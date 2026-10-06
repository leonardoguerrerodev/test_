"""
Rigify (metarig Cat): ajusta el esqueleto al gato "Mao".

Las posiciones salen de las medidas del mesh (mao_unrigged_medidas.json) y de
las articulaciones ya validadas para el rig de ARP. Por cada hueso:
  - columna, cola, cuello, cabeza y las dos parejas de patas: posiciones
    explicitas (tabla EXPLICIT);
  - cara y orejas: mapa por ejes desde el metarig por defecto hasta la cabeza
    de Mao (ancho, largo y alto distintos);
  - huellas (dedos, palmas) y huesos que cuelgan del vientre: mapas por zona.
El script no depende de como dejaste el metarig: lee el metarig por defecto de
tu version de Rigify como referencia y escribe posiciones absolutas.

Uso:
  Con interfaz: abre el .blend, Scripting > Open > Run Script.
  Sin interfaz:  blender -b mao_rigify.blend -P rigify_cat_fit.py
                 (guarda mao_rigify_fitted.blend al lado del original)

Requisitos: Rigify activado y un armature llamado "metarig" (el de gato). Si no
existe, el script crea uno con el metarig de gato y lo ajusta.

Convencion: Z arriba, el gato mira a -Y, el lado .L esta en +X.
"""

import math
import os

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

TARGET_NAME = "metarig"   # armature a ajustar
MESH_NAMES = ["Mao"]      # si existe, se usa su bounding box para escalar/mover
# Solo en modo sin interfaz: "" = <archivo>_fitted.blend, o una ruta concreta.
OUTPUT_BLEND = ""

# ---------------------------------------------------------------------------
# Medidas del mesh de referencia (de mao_unrigged_medidas.json)
# ---------------------------------------------------------------------------

REF_BBOX_MIN = (-0.2180, -0.9539, -0.0024)
REF_BBOX_MAX = (0.2166, 0.9509, 1.2516)
CX = -0.0007  # eje de simetria

# ---------------------------------------------------------------------------
# Posiciones explicitas, coordenadas del mesh de referencia: {hueso: (head, tail)}
# Solo centro y lado .L; el .R se obtiene por espejo.
# ---------------------------------------------------------------------------

EXPLICIT = {
    # torso
    "spine":       ((CX, 0.3570, 0.8090), (CX, 0.1408, 0.8571)),
    "spine.001":   ((CX, 0.1408, 0.8571), (CX, -0.0810, 0.8660)),
    "spine.002":   ((CX, -0.0810, 0.8660), (CX, -0.3030, 0.8634)),
    "spine.003":   ((CX, -0.3030, 0.8634), (CX, -0.5250, 0.8660)),
    # cuello: spine.004 y .005 se reparten el tramo en 59% / 41%
    # (proporcion del metarig por defecto)
    "spine.004":   ((CX, -0.5250, 0.8660), (CX, -0.6344, 0.9292)),
    "spine.005":   ((CX, -0.6344, 0.9292), (CX, -0.7100, 0.9730)),
    # cabeza
    "spine.006":   ((CX, -0.7100, 0.9730), (CX, -0.8800, 1.0800)),
    "face":        ((CX, -0.7100, 0.9730), (CX, -0.7100, 1.0900)),
    # cola
    "tail.001":    ((CX, 0.3570, 0.8090), (CX, 0.5600, 0.7600)),
    "tail.002":    ((CX, 0.5600, 0.7600), (CX, 0.7180, 0.6910)),
    "tail.003":    ((CX, 0.7180, 0.6910), (CX, 0.8650, 0.6510)),
    "tail.004":    ((CX, 0.8650, 0.6510), (CX, 0.9510, 0.6370)),
    # pata trasera
    "pelvis.L":    ((0.1290, 0.4784, 0.7294), (0.1190, 0.4933, 0.5015)),
    "thigh.L":     ((0.1190, 0.4933, 0.5015), (0.1293, 0.2700, 0.3750)),
    "shin.L":      ((0.1293, 0.2700, 0.3750), (0.0993, 0.5040, 0.2470)),
    "foot.L":      ((0.0993, 0.5040, 0.2470), (0.0933, 0.4650, 0.0430)),
    "r_toe.L":     ((0.0933, 0.4650, 0.0430), (0.0933, 0.3750, 0.0130)),
    # pata delantera
    "shoulder.L":  ((0.1100, -0.4700, 0.7800), (0.1300, -0.5300, 0.5500)),
    "upper_arm.L": ((0.1300, -0.5300, 0.5500), (0.1400, -0.4000, 0.4400)),
    "forearm.L":   ((0.1400, -0.4000, 0.4400), (0.1000, -0.5450, 0.1900)),
    "hand.L":      ((0.1000, -0.5450, 0.1900), (0.0820, -0.5850, 0.0450)),
    "f_toe.L":     ((0.0820, -0.5850, 0.0450), (0.0820, -0.6770, 0.0120)),
}

# Mapas por zona: x' = ax + bx * (x - x0), igual para y y z. (valor_mao, escala, valor_default)
# Cara: del metarig por defecto a la cabeza de Mao.
#   y: punta de la nariz -0.280 -> -0.954, base de la cabeza -0.186 -> -0.710
#   z: menton 0.195 -> 0.855, frente 0.267 -> 1.100
FACE = {"x": (CX, 3.3, 0.0), "y": (-0.710, 2.596, -0.186), "z": (0.855, 3.4, 0.195)}
# Orejas: la punta pasa de (0.051, 0.288) a (0.143, 1.25); la base de z=0.266 a 1.10.
EAR = {"x": (0.105, 1.52, 0.026), "y": (-0.800, 1.0, -0.236), "z": (1.100, 6.8, 0.266)}
# Dedos y palmas, anclados en el centro de la huella y en la bola del pie.
HIND_PAW = {"x": (0.0935, 4.3, 0.0355), "y": (0.465, 3.0, 0.153), "z": (0.043, 1.8, 0.017)}
FRONT_PAW = {"x": (0.0820, 4.5, 0.0305), "y": (-0.585, 3.8, -0.126), "z": (0.045, 1.8, 0.011)}

# Huesos que cuelgan de la columna (vientre, pecho, pelvis central): factor con
# el que se amplifica la distancia al eje de la columna.
BODY_DEPTH_SCALE = 4.5
BODY_WIDTH_SCALE = 3.3

FACE_PREFIXES = ("nose", "lip", "jaw", "chin", "brow", "lid", "forehead",
                 "temple", "cheek", "eye", "teeth", "tongue", "face")
LOWER_BODY = ("belly.C", "Breast.C", "pelvis.C")


# ---------------------------------------------------------------------------
# Geometria
# ---------------------------------------------------------------------------


def _axis(m, v):
    return (m["x"][0] + m["x"][1] * (v[0] - m["x"][2]),
            m["y"][0] + m["y"][1] * (v[1] - m["y"][2]),
            m["z"][0] + m["z"][1] * (v[2] - m["z"][2]))


def _interp(x, xs, ys):
    """Interpolacion lineal con extremos fijos. xs puede ir ascendente o descendente."""
    pts = sorted(zip(xs, ys))
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)


def _region(name):
    if name in EXPLICIT or (name.endswith(".R") and name[:-2] + ".L" in EXPLICIT):
        return "explicit"
    if name.startswith("ear."):
        return "ear"
    if name in LOWER_BODY:
        return "lower"
    if name.startswith("f_"):
        return "front_paw"
    if name.startswith("r_"):
        return "hind_paw"
    if name.startswith(FACE_PREFIXES):
        return "face"
    return None


def _side(name):
    if name.endswith(".R"):
        return "R"
    if name.endswith(".L"):
        return "L"
    return "C"


def _mirror_pt(p):
    return (-p[0], p[1], p[2])


def _mirror_out(p):
    return (2 * CX - p[0], p[1], p[2])


class Fitter:
    """
    reference: {nombre: (head, tail, zaxis)} del metarig por defecto, en espacio
    del armature. Devuelve posiciones en coordenadas del mesh de referencia.
    """

    def __init__(self, reference):
        self.ref = reference
        spine = ["spine", "spine.001", "spine.002", "spine.003"]
        self.yd = [reference[n][0][1] for n in spine] + [reference["spine.003"][1][1]]
        self.zd = [reference[n][0][2] for n in spine] + [reference["spine.003"][1][2]]
        self.ym = [EXPLICIT[n][0][1] for n in spine] + [EXPLICIT["spine.003"][1][1]]
        self.zm = [EXPLICIT[n][0][2] for n in spine] + [EXPLICIT["spine.003"][1][2]]

    def _lower(self, p):
        y2 = _interp(p[1], self.yd, self.ym)
        z_spine_d = _interp(p[1], self.yd, self.zd)
        z_spine_m = _interp(y2, self.ym, self.zm)
        return (CX + BODY_WIDTH_SCALE * p[0], y2,
                z_spine_m - BODY_DEPTH_SCALE * (z_spine_d - p[2]))

    def _point(self, region, p):
        if region == "face":
            return _axis(FACE, p)
        if region == "ear":
            return _axis(EAR, p)
        if region == "hind_paw":
            return _axis(HIND_PAW, p)
        if region == "front_paw":
            return _axis(FRONT_PAW, p)
        if region == "lower":
            return self._lower(p)
        raise KeyError(region)

    def fit(self, name):
        """Devuelve (head, tail, zaxis) o None si el hueso no tiene regla."""
        if name not in self.ref:
            return None
        region = _region(name)
        if region is None:
            return None
        side = _side(name)
        h, t, z = self.ref[name]
        flip = side == "R"

        if region == "explicit":
            key = name[:-2] + ".L" if flip else name
            eh, et = EXPLICIT[key]
            if flip:
                eh, et = _mirror_out(eh), _mirror_out(et)
            return eh, et, _rotate_roll(h, t, z, eh, et)

        # zonas por mapa: se trabaja siempre en el lado .L / centro
        if flip:
            h, t, z = _mirror_pt(h), _mirror_pt(t), _mirror_pt(z)
        nh = self._point(region, h)
        nt = self._point(region, t)
        nz = _rotate_roll(h, t, z, nh, nt)
        if flip:
            nh, nt, nz = _mirror_out(nh), _mirror_out(nt), _mirror_pt(nz)
        return nh, nt, nz


def _rotate_roll(h, t, z, nh, nt):
    """Gira el eje Z del hueso con la misma rotacion que lleva su direccion a la nueva."""
    from mathutils import Vector
    d0 = Vector(t) - Vector(h)
    d1 = Vector(nt) - Vector(nh)
    if d0.length < 1e-9 or d1.length < 1e-9:
        return tuple(z)
    q = d0.rotation_difference(d1)
    return tuple(q @ Vector(z))


def fit_transform(actual_min, actual_max):
    """Del mesh de referencia al mesh actual: escala en Y, centro X/Y, suelo en Z."""
    s = (actual_max[1] - actual_min[1]) / (REF_BBOX_MAX[1] - REF_BBOX_MIN[1])
    rcx = (REF_BBOX_MIN[0] + REF_BBOX_MAX[0]) / 2.0
    rcy = (REF_BBOX_MIN[1] + REF_BBOX_MAX[1]) / 2.0
    cx = (actual_min[0] + actual_max[0]) / 2.0
    cy = (actual_min[1] + actual_max[1]) / 2.0

    def f(p):
        return ((p[0] - rcx) * s + cx, (p[1] - rcy) * s + cy,
                (p[2] - REF_BBOX_MIN[2]) * s + actual_min[2])
    return f, s


# ---------------------------------------------------------------------------
# Parte Blender
# ---------------------------------------------------------------------------


def build_reference():
    """Crea un metarig de gato por defecto, lee sus huesos y lo borra."""
    import bpy
    from mathutils import Vector
    if not hasattr(bpy.ops.object, "armature_cat_metarig_add"):
        import addon_utils
        addon_utils.enable("rigify", default_set=False)
    before = set(bpy.data.objects.keys())
    mode = bpy.context.object.mode if bpy.context.object else "OBJECT"
    if mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.armature_cat_metarig_add()
    obj = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before][0]
    ref = {}
    for b in obj.data.bones:
        z = b.matrix_local.to_3x3() @ Vector((0, 0, 1))
        ref[b.name] = (tuple(b.head_local), tuple(b.tail_local), tuple(z))
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.armatures.remove(data)
    return ref


def _world_bbox(meshes):
    from mathutils import Vector
    pts = []
    for o in meshes:
        pts.extend(o.matrix_world @ Vector(c) for c in o.bound_box)
    return (tuple(min(p[i] for p in pts) for i in range(3)),
            tuple(max(p[i] for p in pts) for i in range(3)))


def compute_fit(reference, transform):
    """Resultados finales en coordenadas del mesh actual."""
    fitter = Fitter(reference)
    out, skipped = {}, []
    for name in reference:
        r = fitter.fit(name)
        if r is None:
            skipped.append(name)
            continue
        h, t, z = r
        out[name] = (transform(h), transform(t), z)
    return out, skipped


def apply_fit(arm, results):
    """Escribe head, tail y roll en el armature (coordenadas de mundo)."""
    import bpy
    from mathutils import Vector

    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    inv = arm.matrix_world.inverted()
    rot_inv = inv.to_3x3()
    mirror_state = arm.data.use_mirror_x
    arm.data.use_mirror_x = False

    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    connected = {b.name: b.use_connect for b in eb}
    for b in eb:
        b.use_connect = False
    missing, placed = [], 0
    for name, (h, t, z) in results.items():
        b = eb.get(name)
        if b is None:
            missing.append(name)
            continue
        b.head = inv @ Vector(h)
        b.tail = inv @ Vector(t)
        b.align_roll(rot_inv @ Vector(z))
        placed += 1
    for b in eb:
        b.use_connect = connected[b.name]
    extra = [b.name for b in eb if b.name not in results]
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.data.use_mirror_x = mirror_state
    return placed, missing, extra


def run():
    import bpy

    meshes = [bpy.data.objects[n] for n in MESH_NAMES
              if n in bpy.data.objects and bpy.data.objects[n].type == "MESH"]
    if meshes:
        bb_min, bb_max = _world_bbox(meshes)
        transform, s = fit_transform(bb_min, bb_max)
        print("Mesh %s: min=%s max=%s" % (
            [m.name for m in meshes],
            tuple(round(v, 4) for v in bb_min), tuple(round(v, 4) for v in bb_max)))
        if abs(s - 1.0) > 0.01:
            print("AVISO: el mesh mide %.1f%% de la referencia en Y; las posiciones se escalaron." % (s * 100))
    else:
        transform = lambda p: p
        print("AVISO: no se encontro el mesh %s; se usan las coordenadas de referencia." % MESH_NAMES)

    arm = bpy.data.objects.get(TARGET_NAME)
    if arm is None or arm.type != "ARMATURE":
        before = set(bpy.data.objects.keys())
        bpy.ops.object.armature_cat_metarig_add()
        arm = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before][0]
        print("No habia armature '%s'; se creo uno nuevo con el metarig de gato." % TARGET_NAME)
    if arm.hide_get():
        arm.hide_set(False)
    arm.hide_viewport = False
    if any(abs(v - 1.0) > 1e-6 for v in arm.scale) or any(abs(r) > 1e-6 for r in arm.rotation_euler):
        print("AVISO: '%s' tiene escala o rotacion; aplicalas (Ctrl+A) si algo sale movido." % arm.name)

    reference = build_reference()
    results, skipped = compute_fit(reference, transform)
    placed, missing, extra = apply_fit(arm, results)

    print("Huesos colocados: %d de %d del metarig por defecto" % (placed, len(reference)))
    if skipped:
        print("Sin regla en este script (no se tocan): " + ", ".join(sorted(skipped)))
    if missing:
        print("No existen en '%s' (omitidos): %s" % (arm.name, ", ".join(sorted(missing))))
    if extra:
        print("Huesos de '%s' que el script no conoce (no se tocan): %s" % (arm.name, ", ".join(sorted(extra))))

    arm.show_in_front = True

    if bpy.app.background and bpy.data.filepath:
        out = OUTPUT_BLEND or os.path.splitext(bpy.data.filepath)[0] + "_fitted.blend"
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("Guardado: " + out)
    else:
        print("Listo. Revisa el esqueleto y pulsa Generate Rig en las propiedades del armature.")


if __name__ == "__main__":
    run()
