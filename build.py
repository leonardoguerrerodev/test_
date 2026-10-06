import bpy
import math
import os
import sys
from mathutils import Vector, Matrix

# =======================================================================
# SISTEMA UNIFICADO DE LOCOMOCION PROCEDURAL (v2.5)
# Incluye:
#  - Cinemática de patas con proyección fiel en espacio de armadura
#  - Amortiguación no lineal de almohadillas (damping_factor)
#  - Dinámica sagital de columna (resorte biológico de galope)
#  - Estabilización cefálica (reflejo vestíbulo-ocular / horizonte fijo)
#  - Onda inercial propagada en vértebras de la cola (tail1 a tail5)
# =======================================================================

class GaitConfig:
    def __init__(
        self,
        name,
        duration,
        stride_y,
        step_height,
        root_z_base,
        root_bounce,
        phases,
        duty_factor,
        damping_factor=1.0,
        sway_x=0.0,
        paw_in=0.0,
        # Dinámica de Columna (Spine)
        pitch_amp=0.0,      # Cabeceo sagital de la pelvis (grados)
        pitch_t=0.5,        # Desfase temporal del cabeceo (fracción de ciclo)
        pelvis_roll=0.0,    # Inclinación lateral de la pelvis (grados)
        pelvis_yaw=0.0,     # Guiñada lateral de la pelvis (grados)
        spine_flex=0.0,     # Flexión sagital de la columna/lomo (grados)
        flex_t=0.9,         # Desfase temporal del pico de flexión (vuelo recogido)
        # Dinámica de Cuello y Cabeza (Head & Neck)
        neck_dyn=0.0,       # Amortiguación y rebote dinámico del cuello (grados)
        head_comp=0.75,     # Ganancia de estabilización visual (contrarrotación)
        # Dinámica de la Cola (Tail)
        tail_wave=0.0,      # Intensidad de la onda vertical de la cola (latigazo)
        tail_sway=0.0       # Intensidad del balanceo lateral de la cola (contrapeso)
    ):
        self.name = name
        self.duration = duration          
        self.stride_y = stride_y          
        self.step_height = step_height    
        self.root_z_base = root_z_base    
        self.root_bounce = root_bounce    
        self.phases = phases              
        self.duty_factor = duty_factor    
        self.damping_factor = damping_factor
        self.sway_x = sway_x
        self.paw_in = paw_in

        # Parámetros de columna
        self.pitch_amp = pitch_amp
        self.pitch_t = pitch_t
        self.pelvis_roll = pelvis_roll
        self.pelvis_yaw = pelvis_yaw
        self.spine_flex = spine_flex
        self.flex_t = flex_t

        # Parámetros de cabeza/cuello
        self.neck_dyn = neck_dyn
        self.head_comp = head_comp

        # Parámetros de cola
        self.tail_wave = tail_wave
        self.tail_sway = tail_sway


class ProceduralAnimator:
    def __init__(self, rig_name="Rig_Gato"):
        self.rig = bpy.data.objects.get(rig_name)
        if not self.rig:
            print(f"ATENCIÓN: No se encontró el rig '{rig_name}'.")

    # -------------------------------------------------------------------
    # Transformaciones matemáticas exactas (Espacio Armadura -> Local)
    # -------------------------------------------------------------------
    def to_local_vec(self, bone_name, v):
        """Proyecta un vector de traslación (X, Y, Z) definido en espacio de armadura
        al sistema de coordenadas de traslación local del hueso en reposo."""
        r = self.rig.data.bones[bone_name].matrix_local.to_3x3()
        return r.inverted() @ Vector(v)

    def compose_rot(self, bone_name, rots):
        """Aplica una secuencia de tuplas (eje, ángulo_radianes) definidas en espacio
        de armadura y calcula el cuaternión local exacto para el hueso en pose."""
        R = Matrix.Identity(3)
        for axis, ang in rots:
            R = Matrix.Rotation(ang, 3, Vector(axis)) @ R
        r_rest = self.rig.data.bones[bone_name].matrix_local.to_3x3()
        return (r_rest.inverted() @ R @ r_rest).to_quaternion()

    # -------------------------------------------------------------------
    # Generador principal del ciclo de marcha
    # -------------------------------------------------------------------
    def create_gait(self, config):
        if not self.rig: return
        
        if self.rig.animation_data is None:
            self.rig.animation_data_create()
        
        action_name = config.name
        if action_name in bpy.data.actions:
            bpy.data.actions.remove(bpy.data.actions[action_name])
        action = bpy.data.actions.new(action_name)
        action.use_fake_user = True
        self.rig.animation_data.action = action
        
        bpy.context.scene.frame_start = 1
        bpy.context.scene.frame_end = config.duration
        
        # 1. Cinemática de extremidades (4 controladores IK de patas)
        for foot, phase in config.phases.items():
            self.animate_foot(foot, config, phase)
            
        # 2. Desplazamiento del centro de masa (CONTROLLER: rebote y balanceo)
        self.animate_root("CONTROLLER", config)

        # 3. Dinámica sagital y estabilización de columna, cuello y cabeza
        self.animate_spine_and_head(config)

        # 4. Dinámica ondulatoria inercial de la cola (tail1 a tail5)
        self.animate_tail(config)

        # 5. Suavizado de curvas
        self.smooth_fcurves(action)
        print(f"Generada animación exitosamente: {config.name}")

    # -------------------------------------------------------------------
    # 1. Patas: Apoyo, Vuelo, Amortiguación y Aducción
    # -------------------------------------------------------------------
    def animate_foot(self, bone_name, config, phase_offset):
        bone = self.rig.pose.bones.get(bone_name)
        if not bone: return
        
        frames = config.duration
        df = config.duty_factor
        side_mult = -1.0 if bone_name.endswith("_R") else 1.0
        paw_in = getattr(config, 'paw_in', 0.0)
        
        for f in range(1, frames + 1):
            t = ((f / frames) + phase_offset) % 1.0
            
            if t < df:
                # Fase de apoyo (Stance): Contacto plano, firme y recto
                progress = t / df
                pos_y = (-config.stride_y / 2) + (progress * config.stride_y)
                pos_z = 0.0
                pos_x = 0.0
            else:
                # Fase aérea (Swing): Vuelo parabólico, amortiguación y retorno
                progress = (t - df) / (1.0 - df)
                pos_y = (config.stride_y / 2) - ((math.sin(progress * math.pi - math.pi / 2) + 1) / 2 * config.stride_y)
                
                # Simulación de amortiguación no lineal de almohadillas
                raw_z = math.sin(progress * math.pi)
                if progress > 0.5: # Fase descendente (impacto)
                    fall_progress = (progress - 0.5) * 2.0 
                    cushion = math.pow(1.0 - fall_progress, config.damping_factor)
                    pos_z = cushion * config.step_height
                else:
                    pos_z = raw_z * config.step_height

                # Aducción sutil hacia el plano medio (evita apertura de patas al frente)
                pos_x = -side_mult * paw_in * math.sin(progress * math.pi)
            
            bone.location = self.to_local_vec(bone_name, (pos_x, pos_y, pos_z))
            bone.keyframe_insert(data_path="location", frame=f)

    # -------------------------------------------------------------------
    # 2. Raíz (CONTROLLER): Rebote vertical y Balanceo (Sway)
    # -------------------------------------------------------------------
    def animate_root(self, root_name, config):
        bone = self.rig.pose.bones.get(root_name)
        if not bone: return
        frames = config.duration
        bounce_freq = 2 if config.name != "Sprint" else 1
        sway_amp = getattr(config, 'sway_x', 0.0)

        for f in range(1, frames + 1):
            t = f / frames
            # Rebote vertical real en Z global
            pos_z = config.root_z_base + math.sin(t * math.pi * 2 * bounce_freq) * config.root_bounce
            # Balanceo lateral de estabilización (Sway) en X global
            pos_x = math.sin(t * math.pi * 2) * sway_amp
            
            bone.location = self.to_local_vec(root_name, (pos_x, 0.0, pos_z))
            bone.keyframe_insert(data_path="location", frame=f)

    # -------------------------------------------------------------------
    # 3. Columna, Cuello y Cabeza: Flexión sagital y Reflejo Vestíbulo-Ocular
    # -------------------------------------------------------------------
    def animate_spine_and_head(self, config):
        pelvis_bone = self.rig.pose.bones.get("pelvis")
        thorax_bone = self.rig.pose.bones.get("Bone.001")
        neck_bone = self.rig.pose.bones.get("Bone.002")
        head_bone = self.rig.pose.bones.get("Bone.004")

        frames = config.duration
        bounce_freq = 2 if config.name != "Sprint" else 1

        # Posturas estáticas naturales del modelo anatómico (radianes)
        # s1: inclinación dorsal, s2: ángulo del cuello, s4: orientación del cráneo
        s1 = math.radians(8.0)
        s2 = math.radians(13.5)
        s4 = math.radians(-23.0)

        X = (1, 0, 0) # Eje sagital (Pitch: cabeceo arriba/abajo)
        Y = (0, 1, 0) # Eje longitudinal (Roll: inclinación lateral)
        Z = (0, 0, 1) # Eje vertical (Yaw: guiñada izquierda/derecha)

        for f in range(1, frames + 1):
            t = f / frames

            # --- A. Pelvis: Cabeceo sagital, Roll e inclinación ---
            # P: Cabeceo sagital de la cadera (positivo = empuje hacia abajo/adelante)
            P = math.radians(config.pitch_amp) * math.cos(2 * math.pi * (t - config.pitch_t))
            # Roll: inclinación lateral según alternancia de apoyos
            roll = math.radians(config.pelvis_roll) * math.sin(2 * math.pi * t)
            # Yaw: ligera guiñada por asimetría de empuje
            yaw = math.radians(config.pelvis_yaw) * math.cos(2 * math.pi * t)

            if pelvis_bone:
                pelvis_bone.rotation_mode = 'QUATERNION'
                pelvis_bone.rotation_quaternion = self.compose_rot(
                    "pelvis", [(X, P), (Y, roll), (Z, yaw)]
                )
                pelvis_bone.keyframe_insert(data_path="rotation_quaternion", frame=f)

            # --- B. Columna Lumbar / Tórax (Bone.001): Resorte y Flexión ---
            # F: Arqueo sagital del lomo (resorte biológico que propulsa el galope)
            F = math.radians(config.spine_flex) * math.cos(2 * math.pi * (t - config.flex_t))
            # tr: Contrarrotación de tórax para mantener caja torácica alineada
            tr = -roll

            if thorax_bone:
                thorax_bone.rotation_mode = 'QUATERNION'
                thorax_bone.rotation_quaternion = self.compose_rot(
                    "Bone.001", [(X, s1 + F), (Y, tr), (Z, -1.5 * yaw)]
                )
                thorax_bone.keyframe_insert(data_path="rotation_quaternion", frame=f)

            # --- C. Cuello (Bone.002): Amortiguación del pistón torácico ---
            # dyn: Absorbe el impacto vertical del lomo y pecho
            dyn = math.radians(config.neck_dyn) * math.cos(2 * math.pi * t * bounce_freq)

            if neck_bone:
                neck_bone.rotation_mode = 'QUATERNION'
                neck_bone.rotation_quaternion = self.compose_rot(
                    "Bone.002", [(X, s2 + dyn), (Y, 0.3 * tr)]
                )
                neck_bone.keyframe_insert(data_path="rotation_quaternion", frame=f)

            # --- D. Cabeza (Bone.004): Estabilización de la mirada (Gaze Lock) ---
            # Compensación activa: contrarrotación opuesta al cabeceo y flexión corporal
            pitch_head = s4 - 0.5 * dyn - config.head_comp * (P + F)
            roll_head = -0.4 * (roll + tr)
            yaw_head = 0.8 * yaw

            if head_bone:
                head_bone.rotation_mode = 'QUATERNION'
                head_bone.rotation_quaternion = self.compose_rot(
                    "Bone.004", [(X, pitch_head), (Y, roll_head), (Z, yaw_head)]
                )
                head_bone.keyframe_insert(data_path="rotation_quaternion", frame=f)

    # -------------------------------------------------------------------
    # 4. Cola: Onda Inercial Propagada (tail1 a tail5)
    # -------------------------------------------------------------------
    def animate_tail(self, config):
        tail_bones = ["tail1", "tail2", "tail3", "tail4", "tail5"]
        frames = config.duration
        bounce_freq = 2 if config.name != "Sprint" else 1

        X = (1, 0, 0) # Pitch vertical
        Z = (0, 0, 1) # Yaw horizontal (balanceo lateral)

        for f in range(1, frames + 1):
            t = f / frames

            for i, bn in enumerate(tail_bones, 1):
                bone = self.rig.pose.bones.get(bn)
                if not bone: continue
                bone.rotation_mode = 'QUATERNION'

                # Desfase temporal acumulativo de la onda hacia la punta
                t_lag = (i * 0.08) % 1.0
                t_wave = (t - t_lag) % 1.0

                # A. Onda vertical (Pitch): latigazo inercial sincronizado con el lomo
                wave_amp = math.radians((0.8 + 0.45 * i) * config.tail_wave)
                wave = wave_amp * math.cos(2 * math.pi * t_wave * bounce_freq)

                # B. Onda lateral (Yaw): contrapeso dinámico para estabilizar giro
                sway_amp = math.radians(0.8 * (1.0 + 0.7 * i) * config.tail_sway)
                sway = sway_amp * math.sin(2 * math.pi * (t - (i * 0.12) % 1.0))

                bone.rotation_quaternion = self.compose_rot(
                    bn, [(Z, sway), (X, wave)]
                )
                bone.keyframe_insert(data_path="rotation_quaternion", frame=f)

    # -------------------------------------------------------------------
    # 5. Suavizado de curvas (F-Curves / Bezier)
    # -------------------------------------------------------------------
    def smooth_fcurves(self, action):
        if hasattr(action, "slots"):
            for slot in action.slots:
                for layer in action.layers:
                    for strip in layer.strips:
                        channelbag = strip.channelbag(slot)
                        if channelbag and hasattr(channelbag, "fcurves"):
                            for fcurve in channelbag.fcurves:
                                for kf in fcurve.keyframe_points:
                                    kf.interpolation = 'BEZIER'
                                    kf.handle_left_type = 'AUTO'
                                    kf.handle_right_type = 'AUTO'
                                fcurve.update()
        elif hasattr(action, "fcurves"):
            for fcurve in action.fcurves:
                for kf in fcurve.keyframe_points:
                    kf.interpolation = 'BEZIER'
                    kf.handle_left_type = 'AUTO'
                    kf.handle_right_type = 'AUTO'
                fcurve.update()


# =======================================================================
# CONFIGURACIONES DE MARCHA (GAITS)
# =======================================================================

# 1. Caminata Furtiva: movimientos sigilosos, flexión contenida, cola baja
stealth_gait = GaitConfig(
    name="Stealth_Walk",
    duration=40,
    stride_y=0.4,
    step_height=0.08,
    root_z_base=-0.12,
    root_bounce=0.015,
    phases={"paw_control_L": 0.25, "paw_control_R": 0.75, "leg3_control_L": 0.0, "leg3_control_R": 0.5},
    duty_factor=0.7,
    damping_factor=1.5,
    sway_x=0.008,
    paw_in=0.004,
    # Dinámica sutil
    pitch_amp=1.0, pitch_t=0.5,
    pelvis_roll=1.5, pelvis_yaw=0.8,
    spine_flex=1.5, flex_t=0.0,
    neck_dyn=0.8, head_comp=0.8,
    tail_wave=0.6, tail_sway=0.8
)

# 2. Caminata Normal: balanceo armónico, lomo con ondulación suave
normal_gait = GaitConfig(
    name="Normal_Walk",
    duration=24,
    stride_y=0.5,
    step_height=0.12,
    root_z_base=0.0,
    root_bounce=0.03,
    phases={"paw_control_L": 0.25, "paw_control_R": 0.75, "leg3_control_L": 0.0, "leg3_control_R": 0.5},
    duty_factor=0.6,
    damping_factor=1.2,
    sway_x=0.010,
    paw_in=0.006,
    # Dinámica estándar
    pitch_amp=2.0, pitch_t=0.5,
    pelvis_roll=2.0, pelvis_yaw=1.0,
    spine_flex=3.0, flex_t=0.0,
    neck_dyn=1.8, head_comp=0.7,
    tail_wave=1.2, tail_sway=1.4
)

# 3. Galope / Sprint Felino:
# - Gran flexión del lomo (resorte sagital de 9.5°)
# - Cabeza estabilizada en el horizonte (head_comp=0.78)
# - Cola con onda propagada de latigazo vertical y contrapeso lateral
sprint_gait = GaitConfig(
    name="Sprint",
    duration=14,
    stride_y=1.2,
    step_height=0.25,
    root_z_base=0.05,
    root_bounce=0.08,
    phases={"paw_control_L": 0.5, "paw_control_R": 0.6, "leg3_control_L": 0.0, "leg3_control_R": 0.1},
    duty_factor=0.35,
    damping_factor=1.0,
    sway_x=0.002,
    paw_in=0.008,
    # Dinámica de galope
    pitch_amp=6.0,      # Cabeceo sagital de cadera (6°)
    pitch_t=0.55,       # Sincronizado con despegue trasero
    pelvis_roll=0.5,    # Roll mínimo (galope recto)
    pelvis_yaw=0.6,     # Asimetría controlada de zancada
    spine_flex=9.5,     # Flexión sagital potente del lomo (9.5°)
    flex_t=0.92,        # Máximo arco en la fase de vuelo recogida
    neck_dyn=4.0,       # Absorción del pistón torácico
    head_comp=0.78,     # Estabilización visual activa contra cabeceo
    tail_wave=3.2,      # Latigazo vertical inercial
    tail_sway=1.2       # Contrapeso lateral
)

# =======================================================================
# EJECUCIÓN AUTOMATIZADA POR LOTES
# =======================================================================
if __name__ == "__main__":
    try:
        HERE = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        HERE = os.path.abspath(".")

    SRC = os.path.join(HERE, "mao_rigged3.blend")
    OUT = os.path.join(HERE, "mao_animado_v2.blend")

    print(f"\n[1/4] Abriendo archivo fuente: {SRC}")
    try:
        bpy.ops.wm.open_mainfile(filepath=SRC)
    except RuntimeError as e:
        print(f"ERROR: No se pudo abrir {SRC}. Asegúrate de que el archivo existe en esa ruta.")
        sys.exit(1)

    print("[2/4] Generando animaciones procedurales completas...")
    animator = ProceduralAnimator(rig_name="Rig_Gato")
    animator.create_gait(stealth_gait)
    animator.create_gait(normal_gait)
    animator.create_gait(sprint_gait)

    print("[3/4] Rebobinando escena...")
    bpy.context.scene.frame_set(1)
    
    print("[4/4] Guardando nuevo archivo...")
    bpy.ops.wm.save_as_mainfile(filepath=OUT)

    print("\n" + "="*50)
    print(f"¡ÉXITO! Archivo con animaciones guardado en:\n{OUT}")
    print("="*50 + "\n")