# ==============================================================================
# render_views.py
# Renderiza vistas ortográficas (PNG) y genera GIFs animados con Blender y ffmpeg.
# 
# Uso independiente:
#   blender -b archivo.blend -P render_views.py
#   blender -b archivo.blend -P render_views.py -- --fps 24 --res 600
#   blender -b -P render_views.py -- --blend archivo.blend --vistas lateral,frontal
# ==============================================================================

import bpy
import os
import sys
import math
import shutil
import argparse
import subprocess
from mathutils import Vector

def parse_arguments():
    raw_args = []
    if "--" in sys.argv:
        raw_args = sys.argv[sys.argv.index("--") + 1:]

    parser = argparse.ArgumentParser(description="Renderiza vistas ortográficas y GIFs desde Blender")
    parser.add_argument("--blend", type=str, default="", help="Ruta al archivo .blend (si no se pasó a Blender directamente)")
    parser.add_argument("--action", type=str, default="", help="Nombre de la acción/animación a activar")
    parser.add_argument("--vistas", type=str, default=os.environ.get("VISTAS", "lateral,frontal,trasera,inferior,superior"), help="Lista de vistas separadas por coma")
    parser.add_argument("--fps", type=int, default=int(os.environ.get("RENDER_FPS", 24)), help="FPS para la animación y el GIF")
    parser.add_argument("--res", type=int, default=int(os.environ.get("RENDER_RES", 600)), help="Resolución en píxeles (ancho y alto)")
    parser.add_argument("--out-dir", type=str, default="", help="Directorio raíz de salida")
    parser.add_argument("--no-gif", action="store_true", help="Omitir la generación de GIFs")

    return parser.parse_args(raw_args)

def main():
    args = parse_arguments()

    # 1. Resolver el archivo .blend activo
    if args.blend and os.path.isfile(args.blend):
        target_path = os.path.abspath(args.blend)
        if bpy.data.filepath != target_path:
            print(f"📂 Cargando archivo .blend: {target_path}")
            bpy.ops.wm.open_mainfile(filepath=target_path)

    filepath = bpy.data.filepath
    if filepath:
        HERE = os.path.dirname(os.path.abspath(filepath))
        blend_name = os.path.splitext(os.path.basename(filepath))[0]
    else:
        HERE = os.getcwd()
        blend_name = "escena"

    base_out = os.path.abspath(args.out_dir) if args.out_dir else HERE
    sc = bpy.context.scene

    print(f"\n{'='*60}")
    print(f"🎬 Renderizando Vistas para: {blend_name}.blend")
    print(f"{'='*60}")

    # 2. Configurar animación / acción si fue especificada
    if args.action:
        target_act = bpy.data.actions.get(args.action)
        if target_act:
            for obj in bpy.data.objects:
                if obj.type == 'ARMATURE':
                    if not obj.animation_data:
                        obj.animation_data_create()
                    obj.animation_data.action = target_act
            if hasattr(target_act, "frame_range"):
                sc.frame_start = int(target_act.frame_range[0])
                sc.frame_end = int(target_act.frame_range[1])
            print(f"⚡ Acción activada: {args.action} (Frames: {sc.frame_start}..{sc.frame_end})")
        else:
            print(f"⚠️ Advertencia: Acción '{args.action}' no encontrada en el archivo.")

    # Asegurar rango de frames válido
    if sc.frame_end < sc.frame_start:
        sc.frame_end = sc.frame_start

    print(f"⏱️ Rango de fotogramas a renderizar: {sc.frame_start} a {sc.frame_end} (Total: {sc.frame_end - sc.frame_start + 1} frames)")

    # 3. Calcular caja delimitadora del modelo evaluado en varios fotogramas
    mesh_objs = [o for o in bpy.data.objects if o.type == 'MESH' and not o.hide_render]
    if not mesh_objs:
        mesh_objs = [o for o in bpy.data.objects if o.type == 'MESH']

    if mesh_objs:
        dg = bpy.context.evaluated_depsgraph_get()
        all_pts = []
        f_start = sc.frame_start
        f_end = sc.frame_end
        sample_frames = sorted(list({f_start, (f_start + f_end) // 2, f_end}))

        for f in sample_frames:
            sc.frame_set(f)
            dg.update()
            for obj in mesh_objs:
                eval_obj = obj.evaluated_get(dg)
                for c in eval_obj.bound_box:
                    all_pts.append(eval_obj.matrix_world @ Vector(c))

        if all_pts:
            lo = Vector((min(p.x for p in all_pts), min(p.y for p in all_pts), min(p.z for p in all_pts)))
            hi = Vector((max(p.x for p in all_pts), max(p.y for p in all_pts), max(p.z for p in all_pts)))
            ctr = (lo + hi) / 2
            size = max(hi - lo) * 1.35
        else:
            ctr = Vector((0.0, 0.0, 0.0))
            size = 2.0
    else:
        ctr = Vector((0.0, 0.0, 0.0))
        size = 2.0

    # 4. Configurar cámara ortográfica
    if "cam_tmp" in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects["cam_tmp"], do_unlink=True)
    if "cam_tmp" in bpy.data.cameras:
        bpy.data.cameras.remove(bpy.data.cameras["cam_tmp"], do_unlink=True)

    cam_data = bpy.data.cameras.new("cam_tmp")
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = size
    cam_data.clip_start = 0.1
    cam_data.clip_end = 100.0
    cam = bpy.data.objects.new("cam_tmp", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam

    # 5. Configurar motor de render (Workbench rápido y limpio)
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.render.resolution_x = args.res
    sc.render.resolution_y = args.res
    sc.render.image_settings.file_format = 'PNG'
    sc.display.shading.light = 'STUDIO'
    sc.display.shading.color_type = 'MATERIAL'

    # 6. Definición de vistas
    D = 10.0
    VIEWS = {
        "lateral":  (Vector((1, 0, 0)),  (math.radians(90), 0, math.radians(90))),
        "frontal":  (Vector((0, -1, 0)), (math.radians(90), 0, 0)),
        "trasera":  (Vector((0, 1, 0)),  (math.radians(90), 0, math.radians(180))),
        "inferior": (Vector((0, 0, -1)), (math.radians(180), 0, 0)),
        "superior": (Vector((0, 0, 1)),  (0, 0, math.radians(180))),
    }

    selected_names = [v.strip().lower() for v in args.vistas.split(",") if v.strip().lower() in VIEWS]
    if not selected_names:
        selected_names = list(VIEWS.keys())

    # Carpetas de salida
    frames_base_dir = os.path.join(base_out, "frames", blend_name)
    gifs_dir = os.path.join(base_out, "gifs", blend_name)
    os.makedirs(frames_base_dir, exist_ok=True)
    os.makedirs(gifs_dir, exist_ok=True)

    # 7. Renderizar fotogramas PNG para cada vista
    rendered_views = []
    print("\n📸 Iniciando renderizado de fotogramas...")
    for name in selected_names:
        off, rot = VIEWS[name]
        cam.location = ctr + off * D
        cam.rotation_euler = rot

        view_frame_dir = os.path.join(frames_base_dir, name)
        os.makedirs(view_frame_dir, exist_ok=True)

        sc.render.filepath = os.path.join(view_frame_dir, "f_")
        print(f"  ▶ Renderizando vista '{name}'...")
        bpy.ops.render.render(animation=True)
        rendered_views.append(name)
        print(f"  ✓ Vista '{name}' completada ({len(os.listdir(view_frame_dir))} frames guardados)")

    # 8. Generar GIFs con ffmpeg
    if not args.no_gif:
        ffmpeg_bin = shutil.which("ffmpeg")
        if ffmpeg_bin:
            print("\n🎞️ Generando GIFs con ffmpeg...")
            for name in rendered_views:
                view_frame_dir = os.path.join(frames_base_dir, name)
                pattern = os.path.join(view_frame_dir, "f_%04d.png")

                gif_named = os.path.join(base_out, f"{blend_name}_{name}.gif")
                gif_sub = os.path.join(gifs_dir, f"{name}.gif")
                gif_simple = os.path.join(base_out, f"{name}.gif")

                cmd = [
                    ffmpeg_bin, "-y", "-loglevel", "error",
                    "-framerate", str(args.fps),
                    "-i", pattern,
                    "-vf", "split[a][b];[a]palettegen[p];[b][p]paletteuse",
                    gif_named
                ]
                res = subprocess.run(cmd)
                if res.returncode == 0:
                    shutil.copyfile(gif_named, gif_sub)
                    shutil.copyfile(gif_named, gif_simple)
                    size_kb = os.path.getsize(gif_named) / 1024
                    print(f"  ✓ GIF creado: {blend_name}_{name}.gif ({size_kb:.1f} KB)")
                else:
                    print(f"  ✗ Error al generar GIF para vista '{name}'")
        else:
            print("\n⚠️ ffmpeg no está instalado en el sistema. Los frames PNG están listos en:")
            print(f"   {frames_base_dir}")
            print("   Para generar GIFs, instala ffmpeg: sudo apt install ffmpeg")

    print(f"\n{'='*60}")
    print(f"✅ ¡Renderizado completo para {blend_name}!")
    print(f"📁 Frames PNG : {frames_base_dir}")
    print(f"🎞️ GIFs        : {base_out} (*_{{vista}}.gif y gifs/{blend_name}/)")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
