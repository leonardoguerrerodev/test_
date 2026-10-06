"""
Imprime los huesos del armature activo (nombre, head, tail, padre) y los guarda
en un JSON junto al .blend. Sirve para ver los nombres reales de los huesos de
referencia de tu version de ARP y para comparar con las proporciones del rig
descuadrado.

Uso: selecciona el armature de referencia, Scripting > Run Script.
"""

import json
import os

import bpy

arm = bpy.context.object
if arm is None or arm.type != "ARMATURE":
    raise RuntimeError("Selecciona un armature.")

rows = []
for b in arm.data.bones:
    h = arm.matrix_world @ b.head_local
    t = arm.matrix_world @ b.tail_local
    rows.append({
        "name": b.name,
        "head": [round(v, 5) for v in h],
        "tail": [round(v, 5) for v in t],
        "parent": b.parent.name if b.parent else None,
    })
    print("%-24s head=(%.4f, %.4f, %.4f) tail=(%.4f, %.4f, %.4f)" % ((b.name,) + tuple(h) + tuple(t)))

print("Total: %d huesos" % len(rows))

if bpy.data.filepath:
    out = os.path.join(os.path.dirname(bpy.data.filepath), arm.name + "_bones.json")
    with open(out, "w") as f:
        json.dump(rows, f, indent=2)
    print("JSON guardado en " + out)
