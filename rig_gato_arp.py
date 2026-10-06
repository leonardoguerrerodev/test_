"""
Rig de gato con Auto-Rig Pro (preset 'dog'), con landmarks en metros medidos sobre tu mesh (mao_unrigged_medidas.json).
Solo cabeza + ojos (sin rig facial). Sin orejas (KEEP_EARS = False).

EJECUTAR CON INTERFAZ (sin -b): ARP necesita un 3D Viewport.
  blender mao_unrigged.blend -P rig_gato_arp.py
o Scripting > Open > Run Script.

STAGE = 1 -> agrega rig_ref, borra huesos faciales y coloca columna/cuello/cabeza/cola/patas
             según los landmarks de abajo. Luego afinas a mano en Edit Mode.
STAGE = 2 -> Match to Rig + huesos de ojos + bind con pesos suaves por distancia.
"""
import bpy
import re
import contextlib
import numpy as np
from mathutils import Vector

# ---------------- CONFIG ----------------
STAGE = 1
MESH_NAME = None          # None = mesh más grande de la escena
RIG_PRESET = 'dog'        # sin ".blend"
KEEP_EARS = False
BIND = True
BIND_MODE = 'SMART'       # SMART: pesos por distancia | ARP: bind de ARP | AUTO: pesos automáticos
MAX_INFLUENCES = 3
WEIGHT_POWER = 3.0
SMOOTH_REPEAT = 2
EYE_R = 0.03              # radio de influencia del ojo (x altura)
# ----------------------------------------

# Landmarks en metros (coordenadas mundo del mesh medido), pares (y, z). Cabeza hacia -Y.
# Si el mesh real difiere del medido, se reescalan por bounding box.
EXP_MIN = (-0.2180, -0.9539, -0.0024)
EXP_MAX = (0.2166, 0.9509, 1.2516)

BODY = [(0.357, 0.809), (0.176, 0.855), (-0.005, 0.866), (-0.186, 0.866), (-0.366, 0.862), (-0.525, 0.866)]
NECK = [(-0.525, 0.866), (-0.626, 0.911), (-0.710, 0.973)]
HEAD = [(-0.710, 0.973), (-0.945, 0.936)]
TAIL = [(0.413, 0.843), (0.560, 0.760), (0.718, 0.691), (0.865, 0.651), (0.951, 0.637)]
FRONT = [(-0.446, 0.889), (-0.497, 0.685), (-0.513, 0.458), (-0.537, 0.118), (-0.610, 0.023), (-0.678, 0.009)]
FRONT_LAT = [0.120, 0.100, 0.090, 0.085, 0.0825, 0.0825]   # |x| en metros
HIND = [(0.379, 0.707), (0.270, 0.375), (0.504, 0.247), (0.465, 0.043), (0.375, 0.013)]
HIND_LAT = [0.125, 0.130, 0.100, 0.094, 0.094]
EYE_YZ, EYE_LAT = (-0.857, 1.043), 0.066

FACE_SUBSTR = ('jaw', 'lip', 'cheek', 'brow', 'lid', 'nose', 'nostril', 'tong', 'teeth',
               'tooth', 'chin', 'mouth', 'eye', 'whisker', 'snout', 'muzzle', 'facial')
AUX_SUBSTR = ('bank', 'heel', 'roll', 'pole', 'offset', 'cursor', 'guide', 'pad')
LEG_KINDS = ('shoulder', 'arm', 'forearm', 'hand', 'thigh', 'leg', 'foot', 'toes', 'toe', 'paw')

FR = {}


def log(*a):
    print('[ARP]', *a)


@contextlib.contextmanager
def view3d():
    ov = None
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                if region:
                    ov = dict(window=win, area=area, region=region,
                              space_data=area.spaces.active)
                    break
        if ov:
            break
    if ov is None:
        raise RuntimeError('No hay 3D Viewport. Corre Blender con interfaz (sin -b).')
    with bpy.context.temp_override(**ov):
        yield


def object_mode():
    ob = bpy.context.object
    if ob and ob.mode != 'OBJECT':
        with view3d():
            bpy.ops.object.mode_set(mode='OBJECT')


def make_visible(obj):
    def walk(lc):
        found = obj.name in lc.collection.objects
        for c in lc.children:
            if walk(c):
                found = True
        if found:
            lc.exclude = False
            lc.hide_viewport = False
        return found
    walk(bpy.context.view_layer.layer_collection)
    obj.hide_viewport = False
    obj.hide_set(False)
    obj.hide_select = False


def select_only(obj):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def apply_transform(obj, location=False, rotation=False, scale=False):
    object_mode()
    if obj.name not in bpy.context.view_layer.objects:
        bpy.context.scene.collection.objects.link(obj)
    make_visible(obj)
    select_only(obj)
    with view3d():
        bpy.ops.object.transform_apply(location=location, rotation=rotation, scale=scale)


def world_bbox_mesh(obj):
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    return (Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))),
            Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))))


def world_bbox_arm(obj):
    pts = []
    for b in obj.data.bones:
        pts.append(obj.matrix_world @ b.head_local)
        pts.append(obj.matrix_world @ b.tail_local)
    return (Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))),
            Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))))


def pick_mesh():
    if MESH_NAME:
        return bpy.data.objects[MESH_NAME]
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not meshes:
        raise RuntimeError('No hay meshes en la escena')

    def vol(o):
        mn, mx = world_bbox_mesh(o)
        d = mx - mn
        return d.x * d.y * d.z
    return max(meshes, key=vol)


def find_ref():
    for o in bpy.data.objects:
        if o.type == 'ARMATURE' and any(re.search(r'_ref(\.|$)', b.name) for b in o.data.bones):
            return o
    return None


def find_rig():
    for o in bpy.data.objects:
        if o.type != 'ARMATURE':
            continue
        names = [b.name for b in o.data.bones]
        if any(re.search(r'_ref(\.|$)', n) for n in names):
            continue
        if any(n.startswith('c_') for n in names):
            return o
    return None


def set_frame(mesh):
    mn, mx = world_bbox_mesh(mesh)
    FR.update(mn=mn, mx=mx, L=mx.y - mn.y, H=mx.z - mn.z, W=mx.x - mn.x,
              cx=(mn.x + mx.x) / 2, cy=(mn.y + mx.y) / 2)


def lm(y, z, lat=0.0):
    sy = FR['L'] / (EXP_MAX[1] - EXP_MIN[1])
    sz = FR['H'] / (EXP_MAX[2] - EXP_MIN[2])
    sx = FR['W'] / (EXP_MAX[0] - EXP_MIN[0])
    return Vector((FR['cx'] + lat * sx,
                   FR['mn'].y + (y - EXP_MIN[1]) * sy,
                   FR['mn'].z + (z - EXP_MIN[2]) * sz))


# ---------------- clasificación de huesos ----------------
def base_of(n):
    n = re.sub(r'\.(l|r|x)$', '', n)
    n = re.sub(r'_ref$', '', n)
    return n.lower()


def kind_of(n):
    return re.sub(r'[_\d]+$', '', base_of(n))


def is_face(n):
    b = base_of(n)
    if any(s in b for s in FACE_SUBSTR):
        return True
    return (not KEEP_EARS) and b.startswith('ear')


def make_segs(pts, D, skip_first_ok=False):
    S = len(pts) - 1
    if D == S:
        return list(zip(pts[:-1], pts[1:]))
    if skip_first_ok and D == S - 1:
        return list(zip(pts[1:-1], pts[2:]))
    if D == 1:
        return [(pts[0], pts[-1])]
    ls = [(pts[i + 1] - pts[i]).length for i in range(S)]
    tot = sum(ls)

    def at(s):
        for i, l in enumerate(ls):
            if s <= l or i == S - 1:
                f = 0.0 if l < 1e-9 else min(s / l, 1.0)
                return pts[i].lerp(pts[i + 1], f)
            s -= l
    cuts = [at(tot * i / D) for i in range(D + 1)]
    return list(zip(cuts[:-1], cuts[1:]))


def fit_ref_edit(ref):
    eb = ref.data.edit_bones
    W = ref.matrix_world
    inv = W.inverted()

    faces = [b.name for b in eb if is_face(b.name)]
    for n in faces:
        eb.remove(eb[n])
    log('Huesos faciales borrados:', faces)

    old = {b.name: (W @ b.head.copy(), W @ b.tail.copy()) for b in eb}
    groups, unclassified = {}, []
    for b in eb:
        n = b.name
        base, kind = base_of(n), kind_of(n)
        hw = old[n][0]
        key = None
        if any(a in base for a in AUX_SUBSTR):
            key = None
        elif kind == 'root' or kind.startswith('spine'):
            key = ('body',)
        elif kind.startswith('neck'):
            key = ('neck',)
        elif kind == 'head':
            key = ('head',)
        elif kind.startswith('tail'):
            key = ('tail',)
        elif kind in LEG_KINDS or kind.startswith(('toe', 'finger')):
            front = hw.y < FR['cy']
            if n.endswith('.l'):
                side = 1
            elif n.endswith('.r'):
                side = -1
            else:
                side = 1 if hw.x > FR['cx'] else -1
            key = ('leg', front, side)
        if key is None:
            unclassified.append(n)
        else:
            groups.setdefault(key, []).append(n)

    def place(names, pts, skip_first_ok=False):
        gset = set(names)

        def depth(n):
            d, p = 0, eb[n].parent
            while p:
                if p.name in gset:
                    d += 1
                p = p.parent
            return d
        depths = {n: depth(n) for n in names}
        uniq = sorted(set(depths.values()))
        segs = make_segs(pts, len(uniq), skip_first_ok)
        for n in names:
            a, c = segs[uniq.index(depths[n])]
            eb[n].head = inv @ a
            eb[n].tail = inv @ c

    for key, names in groups.items():
        if key == ('body',):
            place(names, [lm(*p) for p in BODY])
        elif key == ('neck',):
            place(names, [lm(*p) for p in NECK])
        elif key == ('head',):
            place(names, [lm(*p) for p in HEAD])
        elif key == ('tail',):
            place(names, [lm(*p) for p in TAIL])
        else:
            _, front, side = key
            if front:
                pts = [lm(y, z, lat * side) for (y, z), lat in zip(FRONT, FRONT_LAT)]
            else:
                pts = [lm(y, z, lat * side) for (y, z), lat in zip(HIND, HIND_LAT)]
            place(names, pts, skip_first_ok=front)
        log('Grupo', key, '->', names)

    classified = [n for names in groups.values() for n in names]
    for n in unclassified:
        if not classified:
            break
        m = min(classified, key=lambda c: (old[c][0] - old[n][0]).length)
        delta = (W @ eb[m].head) - old[m][0]
        eb[n].head = inv @ (old[n][0] + delta)
        eb[n].tail = inv @ (old[n][1] + delta)
    log('Huesos auxiliares (siguen a su vecino):', unclassified)


def fit_ref(ref):
    object_mode()
    select_only(ref)
    with view3d():
        bpy.ops.object.mode_set(mode='EDIT')
    try:
        fit_ref_edit(ref)
    finally:
        with view3d():
            bpy.ops.object.mode_set(mode='OBJECT')


# ---------------- pesos ----------------
def compute_weights(P, A, C, eps, K, power, chunk=40000):
    n, B = len(P), len(A)
    K = min(K, B)
    idx_out = np.empty((n, K), np.int32)
    w_out = np.empty((n, K), np.float32)
    AB = C - A
    L2 = np.maximum((AB * AB).sum(1), 1e-12)
    for s in range(0, n, chunk):
        Pc = P[s:s + chunk]
        m = len(Pc)
        D = np.empty((B, m), np.float32)
        for bi in range(B):
            t = np.clip(((Pc - A[bi]) @ AB[bi]) / L2[bi], 0.0, 1.0)
            D[bi] = np.linalg.norm(Pc - (A[bi] + t[:, None] * AB[bi]), axis=1)
        idx = np.argpartition(D, K - 1, axis=0)[:K]
        d = np.take_along_axis(D, idx, axis=0)
        w = 1.0 / (d + eps) ** power
        w /= w.sum(axis=0, keepdims=True)
        w[w < 0.04] = 0.0
        w /= w.sum(axis=0, keepdims=True)
        idx_out[s:s + m] = idx.T
        w_out[s:s + m] = w.T
    return idx_out, w_out


def add_eye_bones(rig):
    head_b = next((b for b in rig.data.bones if b.use_deform and re.match(r'^head', b.name)), None)
    if head_b is None:
        log('AVISO: no se halló hueso deform de cabeza; ojos sin parent')
    object_mode()
    select_only(rig)
    with view3d():
        bpy.ops.object.mode_set(mode='EDIT')
    eyes = []
    try:
        inv = rig.matrix_world.inverted()
        fwd = Vector((0, -1, 0)) * 0.03 * FR['H']
        for side, sgn in (('l', 1), ('r', -1)):
            c = lm(EYE_YZ[0], EYE_YZ[1], EYE_LAT * sgn)
            e = rig.data.edit_bones.new('eye.' + side)
            e.head = inv @ c
            e.tail = inv @ (c + fwd)
            e.use_deform = True
            if head_b:
                e.parent = rig.data.edit_bones[head_b.name]
            eyes.append(('eye.' + side, c))
    finally:
        with view3d():
            bpy.ops.object.mode_set(mode='OBJECT')
    return eyes


def smart_bind(mesh, rig, eyes):
    deform = [b for b in rig.data.bones if b.use_deform and not b.name.startswith('eye.')]
    mw = rig.matrix_world
    A = np.array([tuple(mw @ b.head_local) for b in deform], np.float32)
    C = np.array([tuple(mw @ b.tail_local) for b in deform], np.float32)

    n = len(mesh.data.vertices)
    co = np.empty(n * 3, np.float32)
    mesh.data.vertices.foreach_get('co', co)
    co = co.reshape(n, 3)
    M = np.array(mesh.matrix_world, np.float32)
    P = co @ M[:3, :3].T + M[:3, 3]

    idx, w = compute_weights(P, A, C, 0.002 * FR['H'], MAX_INFLUENCES, WEIGHT_POWER)

    eye_w = []
    total = np.zeros(n, np.float32)
    for name, c in eyes:
        d = np.linalg.norm(P - np.array(tuple(c), np.float32), axis=1)
        we = np.clip(1.0 - d / (EYE_R * FR['H']), 0.0, 1.0) ** 2
        eye_w.append((name, we))
        total += we
    w *= np.clip(1.0 - total, 0.0, 1.0)[:, None]

    mesh.vertex_groups.clear()
    q = np.round(w / 0.05).astype(np.int32)
    for bi, b in enumerate(deform):
        mask = (idx == bi) & (q > 0)
        if not mask.any():
            continue
        rows = np.nonzero(mask)[0]
        levels = q[mask]
        vg = mesh.vertex_groups.new(name=b.name)
        for lv in np.unique(levels):
            vg.add(rows[levels == lv].tolist(), float(lv) * 0.05, 'ADD')
    for name, we in eye_w:
        qe = np.round(we / 0.05).astype(np.int32)
        if not (qe > 0).any():
            continue
        vg = mesh.vertex_groups.new(name=name)
        for lv in np.unique(qe[qe > 0]):
            vg.add(np.nonzero(qe == lv)[0].tolist(), float(lv) * 0.05, 'ADD')

    for m in list(mesh.modifiers):
        if m.type == 'ARMATURE':
            mesh.modifiers.remove(m)
    mesh.parent = rig
    mesh.parent_type = 'OBJECT'
    mesh.matrix_parent_inverse = rig.matrix_world.inverted()
    mod = mesh.modifiers.new('Armature', 'ARMATURE')
    mod.object = rig

    object_mode()
    select_only(mesh)
    try:
        with view3d():
            bpy.ops.object.vertex_group_normalize_all(group_select_mode='ALL', lock_active=False)
            if SMOOTH_REPEAT:
                bpy.ops.object.vertex_group_smooth(group_select_mode='ALL', factor=0.5,
                                                   repeat=SMOOTH_REPEAT)
                bpy.ops.object.vertex_group_normalize_all(group_select_mode='ALL', lock_active=False)
    except Exception as e:
        log('Normalize/smooth falló (no crítico):', e)
    log('Bind SMART ok. Grupos:', len(mesh.vertex_groups))


# ---------------- etapas ----------------
def stage1():
    object_mode()
    mesh = pick_mesh()
    log('Mesh:', mesh.name)
    apply_transform(mesh, rotation=True, scale=True)
    set_frame(mesh)

    before = set(bpy.data.objects)
    with view3d():
        bpy.ops.arp.append_arp(rig_preset=RIG_PRESET)
    new = [o for o in bpy.data.objects if o not in before and o.type == 'ARMATURE']
    ref = find_ref() if not new else new[0]
    if ref is None:
        raise RuntimeError('No se encontró rig_ref tras append_arp')
    log('Ref rig:', ref.name)
    for o in bpy.data.objects:
        if o not in before and o is not ref:
            try:
                o.select_set(False)
                o.hide_set(True)
            except Exception:
                pass
    object_mode()

    m_min, m_max = FR['mn'], FR['mx']
    r_min, r_max = world_bbox_arm(ref)
    sy = FR['L'] / (r_max.y - r_min.y) if r_max.y - r_min.y > 1e-6 else 1.0
    sz = FR['H'] / (r_max.z - r_min.z) if r_max.z - r_min.z > 1e-6 else 1.0
    ref.scale = (sy, sy, sz)
    apply_transform(ref, scale=True)

    r_min, r_max = world_bbox_arm(ref)
    ref.location += Vector((FR['cx'] - (r_min.x + r_max.x) / 2,
                            FR['cy'] - (r_min.y + r_max.y) / 2,
                            m_min.z - r_min.z))
    apply_transform(ref, location=True)

    fit_ref(ref)
    ref.show_in_front = True
    log('Bones ref:', sorted(b.name for b in ref.data.bones))
    log('Stage 1 listo. Ajusta rig_ref en Edit Mode, guarda, y corre con STAGE = 2.')


def stage2():
    object_mode()
    mesh = pick_mesh()
    set_frame(mesh)
    ref = find_ref()
    if ref is None:
        raise RuntimeError('No hay rig_ref. Corre STAGE = 1 primero')

    select_only(ref)
    with view3d():
        bpy.ops.arp.match_to_rig()
    object_mode()

    rig = find_rig()
    if rig is None:
        raise RuntimeError('match_to_rig no generó el rig final')
    log('Rig generado:', rig.name)

    eyes = add_eye_bones(rig)
    if not BIND:
        return

    if BIND_MODE == 'SMART':
        smart_bind(mesh, rig, eyes)
        return

    object_mode()
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    mesh.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    if BIND_MODE == 'ARP':
        try:
            with view3d():
                bpy.ops.arp.bind_to_rig()
            log('Bind ARP ok')
            return
        except Exception as e:
            log('arp.bind_to_rig falló:', e, '-> AUTO')
            for o in bpy.context.view_layer.objects:
                o.select_set(False)
            mesh.select_set(True)
            rig.select_set(True)
            bpy.context.view_layer.objects.active = rig
    bpy.ops.object.parent_set(type='ARMATURE_AUTO')
    log('Bind AUTO ok')


if STAGE == 1:
    stage1()
else:
    stage2()
