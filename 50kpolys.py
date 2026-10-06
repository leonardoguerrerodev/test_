import bpy
import sys

# Buscar el objeto por su nombre exacto en la escena
obj_name = "Mao"
obj = bpy.data.objects.get(obj_name)

if obj and obj.type == 'MESH':
    # Hacer que el objeto sea el activo y esté seleccionado en el contexto actual
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    
    current_faces = len(obj.data.polygons)
    target_faces = 50000
    
    if current_faces > target_faces:
        ratio = target_faces / current_faces
        
        # Crear y configurar el modificador Decimate
        decimate_mod = obj.modifiers.new(name="Reduccion_200k", type='DECIMATE')
        decimate_mod.ratio = ratio
        
        # Aplicar el modificador de forma definitiva
        bpy.ops.object.modifier_apply(modifier=decimate_mod.name)
        print(f"ÉXITO: '{obj_name}' reducido de {current_faces} a ~{target_faces} polígonos.")
    else:
        print(f"AVISO: '{obj_name}' ya tiene {current_faces} polígonos. No requiere reducción.")
        
    # Guardar automáticamente los cambios en el archivo .blend activo
    bpy.ops.wm.save_mainfile()
else:
    print(f"ERROR: No se encontró un objeto de tipo MESH llamado '{obj_name}' en el archivo.")
    sys.exit(1)
