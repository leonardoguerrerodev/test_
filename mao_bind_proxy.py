"""
Liga el mesh "Mao" al rig generado por Rigify calculando los pesos sobre una copia limpia.

Por que hace falta: Ctrl+P > With Automatic Weights no funciona con este mesh. Tiene ~2000
islas desconectadas y ~100 000 aristas abiertas, y Blender avisa "Bone Heat Weighting: failed to
find solution for one or more bones" y deja todos los grupos de vertices vacios (la malla no se
deforma).

Que hace:
  1. Quita los grupos de vertices, los modificadores Armature y el padre actuales de Mao.
  2. Crea una copia (proxy) con Remesh de voxeles: una sola pieza, cerrada.
  3. Calcula los pesos automaticos del rig sobre el proxy.
  4. Pasa los pesos a Mao: para cada vertice toma el punto mas cercano de la superficie del proxy
     e interpola los pesos de su cara.
  5. Limita a 4 influencias por vertice, normaliza, borra el proxy y liga Mao al rig.

Los pesos se calculan con el rig en REPOSO aunque tenga una animacion asignada: se desasigna la accion
y se ponen a cero los controles que anima, y al terminar se restaura todo. (Con el rig en otra pose
los pesos salen mal.) Los huesos MCH que Rigify deja con una rotacion intencionada no se tocan.

Calidad: 8 influencias por vertice (con 4, las zonas donde se juntan hombro, brazo y vientre se
estiran: el percentil 99 del estiramiento de la pata delantera pasaba de 2.2 a 7.0 veces su area) y
suavizado de los pesos sobre el proxy. Si tu motor solo admite 4 influencias, pon MAX_INFLUENCES = 4.

Uso con interfaz: abre el .blend con "Mao" y "rig", Scripting > Run Script.
Sin interfaz:     blender -b mao_rig_generado.blend -P mao_bind_proxy.py
                  (guarda <archivo>_ligado.blend al lado del original)
"""

import os
import time

MESH_NAME = "Mao"
RIG_NAME = "rig"
VOXEL_SIZE = 0.02        # menor = proxy mas fiel (orejas, dedos) y mas lento
MAX_INFLUENCES = 8       # Godot 4 admite 8; Unity por defecto 4
SMOOTH_ITERATIONS = 30   # suavizado de pesos sobre el proxy (0 = sin suavizar)
SMOOTH_FACTOR = 0.5
MIN_WEIGHT = 1e-4


def _select_only(*objs, active=None):
    import bpy
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or objs[-1]


def _animated_bones(action):
    names = set()
    if action is None:
        return names
    for layer in action.layers:
        for strip in layer.strips:
            for cb in strip.channelbags:
                for fc in cb.fcurves:
                    if fc.data_path.startswith('pose.bones["'):
                        names.add(fc.data_path.split('"')[1])
    return names


def _smooth_weights(proxy, weights, names):
    """Suaviza los pesos sobre las aristas del proxy y deja las MAX_INFLUENCES mayores."""
    import numpy as np
    groups = sorted({g for w in weights for g in w})
    col = {g: i for i, g in enumerate(groups)}
    nv = len(weights)
    W = np.zeros((nv, len(groups)))
    for i, w in enumerate(weights):
        for g, v in w.items():
            W[i, col[g]] = v
    nb = [[] for _ in range(nv)]
    for e in proxy.data.edges:
        a, b = e.vertices
        nb[a].append(b)
        nb[b].append(a)
    idx = np.concatenate([np.array(x, dtype=int) for x in nb])
    cnt = np.array([len(x) for x in nb])
    start = np.concatenate([[0], np.cumsum(cnt)[:-1]])
    for _ in range(SMOOTH_ITERATIONS):
        mean = np.add.reduceat(W[idx], start, axis=0) / np.maximum(cnt, 1)[:, None]
        W = (1 - SMOOTH_FACTOR) * W + SMOOTH_FACTOR * mean
    drop = np.argsort(-W, axis=1)[:, MAX_INFLUENCES:]
    np.put_along_axis(W, drop, 0.0, axis=1)
    W /= np.maximum(W.sum(axis=1, keepdims=True), 1e-9)
    return [{groups[j]: float(W[i, j]) for j in np.nonzero(W[i] > MIN_WEIGHT)[0]} for i in range(nv)]


def run():
    import bpy
    from mathutils.bvhtree import BVHTree
    from mathutils.interpolate import poly_3d_calc

    mesh, rig = bpy.data.objects.get(MESH_NAME), bpy.data.objects.get(RIG_NAME)
    if mesh is None or mesh.type != "MESH":
        raise RuntimeError("No existe el mesh '%s'." % MESH_NAME)
    if rig is None or rig.type != "ARMATURE":
        raise RuntimeError("No existe el rig '%s'. Genera el rig con Rigify primero." % RIG_NAME)
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    if any(abs(v - 1.0) > 1e-6 for v in mesh.scale):
        raise RuntimeError("'%s' tiene escala %s. Aplica la escala (Ctrl+A > All Transforms) y repite."
                           % (MESH_NAME, tuple(mesh.scale)))

    # 0. el rig en reposo mientras se calculan los pesos
    anim = rig.animation_data
    saved_action = anim.action if anim else None
    if anim:
        anim.action = None
    for nme in _animated_bones(saved_action):
        pb = rig.pose.bones.get(nme)
        if pb is not None:
            pb.location = (0, 0, 0)
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.scale = (1, 1, 1)
    bpy.context.view_layer.update()

    # 1. limpiar
    mesh.vertex_groups.clear()
    for md in list(mesh.modifiers):
        if md.type == "ARMATURE":
            mesh.modifiers.remove(md)
    if mesh.parent is not None:
        _select_only(mesh)
        bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")

    # 2. proxy
    proxy = mesh.copy()
    proxy.data = mesh.data.copy()
    proxy.name = MESH_NAME + "_proxy"
    bpy.context.collection.objects.link(proxy)
    md = proxy.modifiers.new("proxy_remesh", "REMESH")
    md.mode, md.voxel_size = "VOXEL", VOXEL_SIZE
    _select_only(proxy)
    bpy.ops.object.modifier_apply(modifier="proxy_remesh")
    print("Proxy: %d vertices (voxel %.3f)" % (len(proxy.data.vertices), VOXEL_SIZE))

    # 3. pesos automaticos sobre el proxy
    _select_only(proxy, rig, active=rig)
    bpy.ops.object.parent_set(type="ARMATURE_AUTO", keep_transform=True)
    names = {g.index: g.name for g in proxy.vertex_groups}
    pw = [{names[g.group]: g.weight for g in v.groups} for v in proxy.data.vertices]
    empty = sum(1 for w in pw if not w)
    if empty == len(pw):
        raise RuntimeError("Los pesos automaticos fallaron tambien en el proxy. Prueba con otro "
                           "VOXEL_SIZE (por ejemplo 0.03) o revisa que los huesos esten dentro del mesh.")
    print("Pesos sobre el proxy: %d de %d vertices sin pesos" % (empty, len(pw)))
    if SMOOTH_ITERATIONS > 0:
        pw = _smooth_weights(proxy, pw, names)

    # 4. transferir al mesh original
    t = time.time()
    groups = {n: mesh.vertex_groups.new(name=n) for n in names.values()}
    bvh = BVHTree.FromObject(proxy, bpy.context.evaluated_depsgraph_get())
    pco = [v.co.copy() for v in proxy.data.vertices]
    polys = [tuple(p.vertices) for p in proxy.data.polygons]
    for v in mesh.data.vertices:
        loc, _n, fi, _d = bvh.find_nearest(v.co)
        verts = polys[fi]
        bary = poly_3d_calc([pco[i] for i in verts], loc)
        acc = {}
        for b, i in zip(bary, verts):
            for gname, gw in pw[i].items():
                acc[gname] = acc.get(gname, 0.0) + b * gw
        for gname, gw in acc.items():
            if gw > MIN_WEIGHT:
                groups[gname].add([v.index], gw, "REPLACE")
    print("Pesos transferidos en %.0f s" % (time.time() - t))

    # 5. limitar, normalizar, borrar proxy y ligar
    _select_only(mesh)
    bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=MAX_INFLUENCES)
    bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)
    data = proxy.data
    bpy.data.objects.remove(proxy, do_unlink=True)
    bpy.data.meshes.remove(data)
    _select_only(mesh, rig, active=rig)
    bpy.ops.object.parent_set(type="ARMATURE", keep_transform=True)

    if anim:
        anim.action = saved_action
    bpy.context.view_layer.update()

    unweighted = sum(1 for v in mesh.data.vertices if not v.groups)
    print("Listo: %d grupos, %d vertices sin pesos de %d" % (
        len(mesh.vertex_groups), unweighted, len(mesh.data.vertices)))
    if unweighted:
        print("AVISO: hay vertices sin pesos; no se deformaran. Baja VOXEL_SIZE.")

    if bpy.app.background and bpy.data.filepath:
        out = os.path.splitext(bpy.data.filepath)[0] + "_ligado.blend"
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("Guardado: " + out)


if __name__ == "__main__":
    run()
