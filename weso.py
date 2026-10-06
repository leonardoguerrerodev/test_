import bpy
import json
import os

# Buscar la primera armadura disponible en el archivo .blend
obj = None
for o in bpy.data.objects:
    if o.type == 'ARMATURE':
        obj = o
        break

if obj:
    print(f"Esqueleto encontrado: {obj.name}")
    rig_data = {
        "armature_name": obj.name,
        "bones": {}
    }
    
    # Extraer la información de los huesos
    for p_bone in obj.pose.bones:
        e_bone = p_bone.bone
        custom_shape_name = p_bone.custom_shape.name if p_bone.custom_shape else "None"
        
        rig_data["bones"][p_bone.name] = {
            "pose_transform": {
                "location": list(p_bone.location),
                "rotation_euler": list(p_bone.rotation_euler) if p_bone.rotation_mode == 'XYZ' else list(p_bone.rotation_quaternion),
                "scale": list(p_bone.scale)
            },
            "edit_structure": {
                "head": list(e_bone.head),
                "tail": list(e_bone.tail),
                "length": e_bone.length,
                "parent": e_bone.parent.name if e_bone.parent else "None"
            },
            "rig_display": {
                "custom_shape": custom_shape_name
            }
        }
        
    # Guardar en la misma carpeta donde estás ejecutando el comando
    output_path = os.path.join(os.getcwd(), "export_rig_data.json")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(rig_data, f, indent=4)
        
    print(f"ÉXITO: Datos exportados correctamente en: {output_path}")
else:
    print("ERROR: No se encontró ninguna ARMATURE en el archivo .blend.")
