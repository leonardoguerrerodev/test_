"""
Exporta medidas exactas del gato a un JSON junto al .blend.

Uso (no necesita interfaz):
  blender -b mao_unrigged.blend -P medir_gato.py

Tambien sirve sobre el .blend guardado tras STAGE 1 (vuelca nombres y posiciones de los huesos ref).
Opcional: pon Empties con nombre en los puntos clave (p.ej. shoulder.l, elbow.l, wrist.l,
knee.l, hock.l, eye.l, neck_base, head_base, tail_base) y tambien se exportan.
"""
import bpy
import json
import os
import numpy as np

MESH_NAME = None      # None = mesh mas grande
N_SLICES = 80         # cortes a lo largo de Y y de Z
CELL = 0.01           # tamano de celda (x altura) para agrupar patas/cola
LEG_Z_MAX = 0.62      # cortes en Z hasta esta fraccion de la altura incluyen componentes
MIN_COUNT = 20        # ignora grupos con menos vertices (pelos sueltos)


def r(v, n=4):
    return round(float(v), n)


def rv(v):
    return [r(v[0]), r(v[1]), r(v[2])]


def pick_mesh():
    if MESH_NAME:
        return bpy.data.objects[MESH_NAME]
    best, bv = None, -1
    for o in bpy.context.scene.objects:
        if o.type != 'MESH':
            continue
        d = o.dimensions
        v = d.x * d.y * d.z
        if v > bv:
            best, bv = o, v
    if best is None:
        raise RuntimeError('No hay meshes')
    return best


def components(a, b, cell, min_count):
    """Componentes conexas 2D de puntos (a, b) sobre una grilla. Devuelve lista de indices."""
    ga = np.floor(a / cell).astype(np.int64)
    gb = np.floor(b / cell).astype(np.int64)
    cells = {}
    for i in range(len(a)):
        cells.setdefault((int(ga[i]), int(gb[i])), []).append(i)
    seen, out = set(), []
    for c in cells:
        if c in seen:
            continue
        stack, idxs = [c], []
        seen.add(c)
        while stack:
            cur = stack.pop()
            idxs.extend(cells[cur])
            for da in (-1, 0, 1):
                for db in (-1, 0, 1):
                    nb = (cur[0] + da, cur[1] + db)
                    if nb in cells and nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
        if len(idxs) >= min_count:
            out.append(np.array(idxs))
    return out


def comp_info(P, ii):
    q = P[ii]
    return {
        'n': int(len(ii)),
        'x': [r(q[:, 0].min()), r(q[:, 0].max())],
        'y': [r(q[:, 1].min()), r(q[:, 1].max())],
        'z': [r(q[:, 2].min()), r(q[:, 2].max())],
        'c': [r(q[:, 0].mean()), r(q[:, 1].mean()), r(q[:, 2].mean())],
    }


def main():
    mesh = pick_mesh()
    n = len(mesh.data.vertices)
    co = np.empty(n * 3, np.float32)
    mesh.data.vertices.foreach_get('co', co)
    co = co.reshape(n, 3).astype(np.float64)
    M = np.array(mesh.matrix_world, np.float64)
    P = co @ M[:3, :3].T + M[:3, 3]

    mn, mx = P.min(0), P.max(0)
    L, H, W = mx[1] - mn[1], mx[2] - mn[2], mx[0] - mn[0]
    cx = (mn[0] + mx[0]) / 2

    data = {
        'blender': bpy.app.version_string,
        'mesh': mesh.name,
        'verts': n,
        'matrix_world': [[r(x, 6) for x in row] for row in M],
        'dimensions': rv(mesh.dimensions),
        'bbox_min': rv(mn), 'bbox_max': rv(mx),
        'size_x_width': r(W), 'size_y_length': r(L), 'size_z_height': r(H),
        'center_x': r(cx),
        'cursor': rv(bpy.context.scene.cursor.location),
    }

    # puntos extremos
    i_nose, i_tail, i_top = P[:, 1].argmin(), P[:, 1].argmax(), P[:, 2].argmax()
    data['extremes'] = {
        'min_y_vertex': rv(P[i_nose]), 'max_y_vertex': rv(P[i_tail]), 'max_z_vertex': rv(P[i_top]),
    }
    for side, mask in (('ear_top_x_pos', P[:, 0] > cx), ('ear_top_x_neg', P[:, 0] < cx)):
        idx = np.nonzero(mask)[0]
        j = idx[P[idx, 2].argmax()]
        data['extremes'][side] = rv(P[j])

    # contactos con el suelo (patas)
    gm = np.nonzero(P[:, 2] < mn[2] + 0.012 * H)[0]
    data['ground_contacts'] = [comp_info(P, gm[c])
                               for c in components(P[gm, 0], P[gm, 1], CELL * H, 5)]

    # cortes a lo largo de Y (cabeza -> cola segun eje Y)
    ys = np.linspace(mn[1], mx[1], N_SLICES + 1)
    sy = []
    for i in range(N_SLICES):
        m = (P[:, 1] >= ys[i]) & (P[:, 1] < ys[i + 1] + (1e-9 if i == N_SLICES - 1 else 0))
        if m.sum() < 5:
            continue
        q = P[m]
        sy.append({
            'y': [r(ys[i]), r(ys[i + 1])], 'n': int(m.sum()),
            'z_min': r(q[:, 2].min()), 'z_p1': r(np.percentile(q[:, 2], 1)),
            'z_p50': r(np.percentile(q[:, 2], 50)),
            'z_p99': r(np.percentile(q[:, 2], 99)), 'z_max': r(q[:, 2].max()),
            'x_min': r(q[:, 0].min()), 'x_p1': r(np.percentile(q[:, 0], 1)),
            'x_p99': r(np.percentile(q[:, 0], 99)), 'x_max': r(q[:, 0].max()),
            'c': [r(q[:, 0].mean()), r(q[:, 2].mean())],
        })
    data['slices_y'] = sy

    # cortes a lo largo de Z (altura): extension y componentes (patas, cola)
    zs = np.linspace(mn[2], mx[2], N_SLICES + 1)
    sz = []
    for i in range(N_SLICES):
        m = (P[:, 2] >= zs[i]) & (P[:, 2] < zs[i + 1] + (1e-9 if i == N_SLICES - 1 else 0))
        if m.sum() < 5:
            continue
        idx = np.nonzero(m)[0]
        q = P[idx]
        item = {
            'z': [r(zs[i]), r(zs[i + 1])], 'n': int(len(idx)),
            'y_min': r(q[:, 1].min()), 'y_max': r(q[:, 1].max()),
            'x_min': r(q[:, 0].min()), 'x_max': r(q[:, 0].max()),
        }
        if zs[i] <= mn[2] + LEG_Z_MAX * H:
            item['components'] = [comp_info(P, idx[c])
                                  for c in components(q[:, 0], q[:, 1], CELL * H, MIN_COUNT)]
        sz.append(item)
    data['slices_z'] = sz

    # armaturas (huesos ref o rig final)
    arms = []
    for o in bpy.data.objects:
        if o.type != 'ARMATURE':
            continue
        W_ = o.matrix_world
        arms.append({
            'object': o.name,
            'bones': [{
                'name': b.name,
                'parent': b.parent.name if b.parent else None,
                'head': rv(W_ @ b.head_local), 'tail': rv(W_ @ b.tail_local),
                'connect': b.use_connect, 'deform': b.use_deform,
            } for b in o.data.bones],
        })
    data['armatures'] = arms

    # empties con nombre (landmarks puestos a mano)
    data['empties'] = {o.name: rv(o.matrix_world.translation)
                       for o in bpy.data.objects if o.type == 'EMPTY'}

    base = os.path.splitext(os.path.basename(bpy.data.filepath) or 'modelo')[0]
    folder = os.path.dirname(bpy.data.filepath) or os.getcwd()
    out = os.path.join(folder, base + '_medidas.json')
    with open(out, 'w') as f:
        json.dump(data, f, separators=(',', ':'))

    print('[MEDIR] Mesh:', mesh.name, '| verts:', n)
    print('[MEDIR] Ancho X: %.4f  Largo Y: %.4f  Alto Z: %.4f' % (W, L, H))
    print('[MEDIR] bbox min', rv(mn), 'max', rv(mx))
    print('[MEDIR] Cortes Y:', len(sy), '| cortes Z:', len(sz), '| armaturas:', len(arms),
          '| empties:', len(data['empties']))
    print('[MEDIR] Archivo:', out, '(%d KB)' % (os.path.getsize(out) // 1024))


main()
