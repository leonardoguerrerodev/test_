import bpy
import math
import os
import sys
from mathutils import Vector, Matrix

# =======================================================================
# SISTEMA UNIFICADO DE LOCOMOCION PROCEDURAL (v3.0)
# Cambios respecto a v2.5:
#  - Las proporciones (zancada, altura de paso, agachado, rebote) se expresan
#    como RATIOS de la longitud real de la pata y se resuelven contra la
#    anatomía medida del rig (huesos en reposo).
#  - Ajuste automático: se evalúa la pose real (cadera/hombro por fotograma) y
#    la zancada se reduce / el cuerpo se agacha hasta que ninguna pata pida
#    más alcance del que tiene (MAX_REACH). Esto elimina el estiramiento del
#    mesh entre el final de la cadena IK y los huesos feet_* / paw3_*.
#  - Se fuerza modo OBJETO antes de animar y de guardar (el .blend fuente
#    está guardado en modo EDIT, donde la pose no se evalúa).
# =======================================================================

MAX_REACH = 0.985   # fracción máxima de la longitud de la pata que puede pedir el IK

# Controlador IK -> (hueso raíz de la cadena, huesos de la cadena)
LIMBS = {
    "paw_control_L":  ("paw1_L", ("paw1_L", "paw2_L")),
    "paw_control_R":  ("paw1_R", ("paw1_R", "paw2_R")),
    "leg3_control_L": ("leg1_L", ("leg1_L", "leg2_L", "leg3_L")),
    "leg3_control_R": ("leg1_R", ("leg1_R", "leg2_R", "leg3_R")),
}
FORE = ("paw_control_L", "paw_control_R")


class GaitConfig:
    def __init__(
        self,
        name,
        duration,
        stride_ratio,       # zancada total / longitud de pata delantera
        step_ratio,         # altura de paso / longitud de pata delantera
        ext_mid,            # extensión de la pata delantera en apoyo medio (0..1): menor = más agachado
        bounce_ratio,       # rebote vertical del cuerpo / longitud de pata delantera
        phases,
        duty_factor,
        damping_factor=1.0,
        sway_x=0.0,
        paw_in=0.0,
        foot_center=0.5,    # 0 = ciclo centrado en la posición de reposo, 1 = centrado bajo cadera/hombro
        # Dinámica de Columna (Spine)
        pitch_amp=0.0,
        pitch_t=0.5,
        pelvis_roll=0.0,
        pelvis_yaw=0.0,
        spine_flex=0.0,
        flex_t=0.9,
        # Dinámica de Cuello y Cabeza
        neck_dyn=0.0,
        head_comp=0.75,
        # Dinámica de la Cola
        tail_wave=0.0,
        tail_sway=0.0
    ):
        self.name = name
        self.duration = duration
        self.stride_ratio = stride_ratio
        self.step_ratio = step_ratio
        self.ext_mid = ext_mid
        self.bounce_ratio = bounce_ratio
        self.phases = phases
        self.duty_factor = duty_factor
        self.damping_factor = damping_factor
        self.sway_x = sway_x
        self.paw_in = paw_in
        self.foot_center = foot_center

        self.pitch_amp = pitch_amp
        self.pitch_t = pitch_t
        self.pelvis_roll = pelvis_roll
        self.pelvis_yaw = pelvis_yaw
        self.spine_flex = spine_flex
        self.flex_t = flex_t

        self.neck_dyn = neck_dyn
        self.head_comp = head_comp

        self.tail_wave = tail_wave
        self.tail_sway = tail_sway

        # Valores absolutos (metros). Los resuelve ProceduralAnimator.create_gait()
        self.stride_y = 0.0
        self.step_height = 0.0
        self.root_z_base = 0.0
        self.root_bounce = 0.0


def ensure_object_mode(rig):
    """El pose solo se evalúa en modo OBJETO/POSE. Fuerza OBJETO sobre el rig."""
    if rig is None:
        return
    try:
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.context.view_layer.objects.active = rig
        if rig.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
    except RuntimeError as e:
        print(f"ATENCIÓN: no se pudo cambiar a modo OBJETO ({e})")


class ProceduralAnimator:
    def __init__(self, rig_name="Rig_Gato"):
        self.rig = bpy.data.objects.get(rig_name)
        self.limb = {}
        if not self.rig:
            print(f"ATENCIÓN: No se encontró el rig '{rig_name}'.")
            return
        ensure_object_mode(self.rig)
        self._measure_anatomy()

    # -------------------------------------------------------------------
    # Anatomía real del rig (huesos en reposo, espacio de armadura)
    # -------------------------------------------------------------------
    def _measure_anatomy(self):
        bones = self.rig.data.bones
        for ctl, (root, chain) in LIMBS.items():
            self.limb[ctl] = {
                "root": root,
                "L": sum(bones[b].length for b in chain),
                "rest": bones[ctl].head_local.copy(),
                "root_rest": bones[root].head_local.copy(),
            }
        fore = [self.limb[c] for c in FORE]
        self.ref_len = sum(i["L"] for i in fore) / len(fore)                       # longitud pata delantera
        self.rest_h = sum(i["root_rest"].z - i["rest"].z for i in fore) / len(fore)  # altura hombro->suelo en reposo
        print("Anatomía medida: " + ", ".join(
            f"{c}: L={i['L']:.3f}" for c, i in self.limb.items()) +
            f" | ref={self.ref_len:.3f} | h_reposo={self.rest_h:.3f}")

    # -------------------------------------------------------------------
    # Transformaciones matemáticas exactas (Espacio Armadura -> Local)
    # -------------------------------------------------------------------
    def to_local_vec(self, bone_name, v):
        r = self.rig.data.bones[bone_name].matrix_local.to_3x3()
        return r.inverted() @ Vector(v)

    def compose_rot(self, bone_name, rots):
        R = Matrix.Identity(3)
        for axis, ang in rots:
            R = Matrix.Rotation(ang, 3, Vector(axis)) @ R
        r_rest = self.rig.data.bones[bone_name].matrix_local.to_3x3()
        return (r_rest.inverted() @ R @ r_rest).to_quaternion()

    # -------------------------------------------------------------------
    # Generador principal del ciclo de marcha
    # -------------------------------------------------------------------
    def create_gait(self, config):
        if not self.rig:
            return
        ensure_object_mode(self.rig)

        if self.rig.animation_data is None:
            self.rig.animation_data_create()

        action_name = config.name
        if action_name in bpy.data.actions:
            bpy.data.actions.remove(bpy.data.actions[action_name])
        action = bpy.data.actions.new(action_name)
        action.use_fake_user = True
        self.rig.animation_data.action = action
        if hasattr(self.rig.animation_data, "action_slot") and hasattr(action, "slots") and len(action.slots):
            try:
                self.rig.animation_data.action_slot = action.slots[0]
            except Exception:
                pass

        bpy.context.scene.frame_start = 1
        bpy.context.scene.frame_end = config.duration

        # 0. Proporciones absolutas a partir de la anatomía real
        Lf = self.ref_len
        config.step_height = config.step_ratio * Lf
        config.root_bounce = config.bounce_ratio * Lf
        config.root_z_base = min(0.0, -(self.rest_h - config.ext_mid * Lf))
        requested_stride = config.stride_ratio * Lf

        # 1. Cuerpo: raíz, columna/cabeza y cola (no dependen de las patas)
        self.animate_root("CONTROLLER", config)
        self.animate_spine_and_head(config)
        self.animate_tail(config)

        # 2. Ajuste de alcance: agachar si hace falta y limitar zancada
        hips = self.sample_hips(config)
        for _ in range(6):
            excess = self.reach_excess(config, hips, 0.0)
            if excess <= 1e-4:
                break
            config.root_z_base -= excess + 0.002
            self.animate_root("CONTROLLER", config)
            hips = self.sample_hips(config)

        if self.reach_excess(config, hips, requested_stride) <= 0.0:
            stride = requested_stride
        else:
            lo, hi = 0.0, requested_stride
            for _ in range(30):
                mid = (lo + hi) / 2.0
                if self.reach_excess(config, hips, mid) <= 0.0:
                    lo = mid
                else:
                    hi = mid
            stride = lo
        config.stride_y = stride

        # 3. Patas con la zancada ya validada
        for foot, phase in config.phases.items():
            self.animate_foot(foot, config, phase, hips)

        # 4. Suavizado de curvas
        self.smooth_fcurves(action)

        speed_note = "" if stride >= requested_stride - 1e-6 else f" (pedida {requested_stride:.3f}, limitada por alcance de pata)"
        print(f"Generada animación: {config.name} | zancada {stride:.3f} m{speed_note} | "
              f"altura de paso {config.step_height:.3f} m | root_z {config.root_z_base:+.3f} m")

    # -------------------------------------------------------------------
    # Muestreo de cadera/hombro evaluados (incluye root, pelvis y rebote)
    # -------------------------------------------------------------------
    def sample_hips(self, config):
        sc = bpy.context.scene
        hips = {ctl: [] for ctl in self.limb}
        for f in range(1, config.duration + 1):
            sc.frame_set(f)
            bpy.context.view_layer.update()
            ev = self.rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
            for ctl, info in self.limb.items():
                hips[ctl].append(ev.pose.bones[info["root"]].head.copy())
        return hips

    # -------------------------------------------------------------------
    # Posición objetivo del pie (offset en espacio de armadura)
    # -------------------------------------------------------------------
    def foot_offset(self, bone_name, config, phase_offset, f, stride, shift_y=0.0):
        frames = config.duration
        df = config.duty_factor
        side_mult = -1.0 if bone_name.endswith("_R") else 1.0
        t = ((f / frames) + phase_offset) % 1.0

        if t < df:
            progress = t / df
            pos_y = (-stride / 2) + (progress * stride)
            pos_z = 0.0
            pos_x = 0.0
        else:
            progress = (t - df) / (1.0 - df)
            pos_y = (stride / 2) - ((math.sin(progress * math.pi - math.pi / 2) + 1) / 2 * stride)

            raw_z = math.sin(progress * math.pi)
            if progress > 0.5:
                fall_progress = (progress - 0.5) * 2.0
                cushion = math.pow(1.0 - fall_progress, config.damping_factor)
                pos_z = cushion * config.step_height
            else:
                pos_z = raw_z * config.step_height

            pos_x = -side_mult * config.paw_in * math.sin(progress * math.pi)

        return Vector((pos_x, pos_y + shift_y, pos_z))

    def center_shift(self, ctl, config, hips):
        """Desplazamiento Y del ciclo para centrarlo (parcialmente) bajo cadera/hombro."""
        mean_hip_y = sum(h.y for h in hips[ctl]) / len(hips[ctl])
        return config.foot_center * (mean_hip_y - self.limb[ctl]["rest"].y)

    def reach_excess(self, config, hips, stride):
        """Máximo (distancia cadera->objetivo - alcance permitido) sobre todas las patas y fotogramas."""
        worst = -1e9
        for ctl, phase in config.phases.items():
            info = self.limb[ctl]
            shift = self.center_shift(ctl, config, hips)
            limit = MAX_REACH * info["L"]
            for i, f in enumerate(range(1, config.duration + 1)):
                target = info["rest"] + self.foot_offset(ctl, config, phase, f, stride, shift)
                worst = max(worst, (target - hips[ctl][i]).length - limit)
        return worst

    # -------------------------------------------------------------------
    # 1. Patas: Apoyo, Vuelo, Amortiguación y Aducción
    # -------------------------------------------------------------------
    def animate_foot(self, bone_name, config, phase_offset, hips):
        bone = self.rig.pose.bones.get(bone_name)
        if not bone:
            return
        shift = self.center_shift(bone_name, config, hips)
        for f in range(1, config.duration + 1):
            off = self.foot_offset(bone_name, config, phase_offset, f, config.stride_y, shift)
            bone.location = self.to_local_vec(bone_name, off)
            bone.keyframe_insert(data_path="location", frame=f)

    # -------------------------------------------------------------------
    # 2. Raíz (CONTROLLER): Rebote vertical y Balanceo (Sway)
    # -------------------------------------------------------------------
    def animate_root(self, root_name, config):
        bone = self.rig.pose.bones.get(root_name)
        if not bone:
            return
        frames = config.duration
        bounce_freq = 2 if config.name != "Sprint" else 1
        sway_amp = getattr(config, 'sway_x', 0.0)

        for f in range(1, frames + 1):
            t = f / frames
            pos_z = config.root_z_base + math.sin(t * math.pi * 2 * bounce_freq) * config.root_bounce
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

        s1 = math.radians(8.0)
        s2 = math.radians(13.5)
        s4 = math.radians(-23.0)

        X = (1, 0, 0)
        Y = (0, 1, 0)
        Z = (0, 0, 1)

        for f in range(1, frames + 1):
            t = f / frames

            P = math.radians(config.pitch_amp) * math.cos(2 * math.pi * (t - config.pitch_t))
            roll = math.radians(config.pelvis_roll) * math.sin(2 * math.pi * t)
            yaw = math.radians(config.pelvis_yaw) * math.cos(2 * math.pi * t)

            if pelvis_bone:
                pelvis_bone.rotation_mode = 'QUATERNION'
                pelvis_bone.rotation_quaternion = self.compose_rot(
                    "pelvis", [(X, P), (Y, roll), (Z, yaw)]
                )
                pelvis_bone.keyframe_insert(data_path="rotation_quaternion", frame=f)

            F = math.radians(config.spine_flex) * math.cos(2 * math.pi * (t - config.flex_t))
            tr = -roll

            if thorax_bone:
                thorax_bone.rotation_mode = 'QUATERNION'
                thorax_bone.rotation_quaternion = self.compose_rot(
                    "Bone.001", [(X, s1 + F), (Y, tr), (Z, -1.5 * yaw)]
                )
                thorax_bone.keyframe_insert(data_path="rotation_quaternion", frame=f)

            dyn = math.radians(config.neck_dyn) * math.cos(2 * math.pi * t * bounce_freq)

            if neck_bone:
                neck_bone.rotation_mode = 'QUATERNION'
                neck_bone.rotation_quaternion = self.compose_rot(
                    "Bone.002", [(X, s2 + dyn), (Y, 0.3 * tr)]
                )
                neck_bone.keyframe_insert(data_path="rotation_quaternion", frame=f)

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

        X = (1, 0, 0)
        Z = (0, 0, 1)

        for f in range(1, frames + 1):
            t = f / frames

            for i, bn in enumerate(tail_bones, 1):
                bone = self.rig.pose.bones.get(bn)
                if not bone:
                    continue
                bone.rotation_mode = 'QUATERNION'

                t_lag = (i * 0.08) % 1.0
                t_wave = (t - t_lag) % 1.0

                wave_amp = math.radians((0.8 + 0.45 * i) * config.tail_wave)
                wave = wave_amp * math.cos(2 * math.pi * t_wave * bounce_freq)

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
# CONFIGURACIONES DE MARCHA (GAITS) - proporciones relativas a la pata
# stride_ratio / step_ratio / bounce_ratio: múltiplos de la longitud de pata delantera
# ext_mid: extensión de la pata en apoyo medio (1.0 = recta, 0.8 = agachado)
# El ajuste automático recorta stride_ratio si la pata no alcanza.
# =======================================================================

# 1. Caminata Furtiva
stealth_gait = GaitConfig(
    name="Stealth_Walk",
    duration=40,
    stride_ratio=0.58,
    step_ratio=0.12,
    ext_mid=0.81,
    bounce_ratio=0.02,
    phases={"paw_control_L": 0.25, "paw_control_R": 0.75, "leg3_control_L": 0.0, "leg3_control_R": 0.5},
    duty_factor=0.7,
    damping_factor=1.5,
    sway_x=0.008,
    paw_in=0.004,
    pitch_amp=1.0, pitch_t=0.5,
    pelvis_roll=1.5, pelvis_yaw=0.8,
    spine_flex=1.5, flex_t=0.0,
    neck_dyn=0.8, head_comp=0.8,
    tail_wave=0.6, tail_sway=0.8
)

# 2. Caminata Normal
normal_gait = GaitConfig(
    name="Normal_Walk",
    duration=24,
    stride_ratio=0.72,
    step_ratio=0.17,
    ext_mid=0.86,
    bounce_ratio=0.04,
    phases={"paw_control_L": 0.25, "paw_control_R": 0.75, "leg3_control_L": 0.0, "leg3_control_R": 0.5},
    duty_factor=0.6,
    damping_factor=1.2,
    sway_x=0.010,
    paw_in=0.006,
    pitch_amp=2.0, pitch_t=0.5,
    pelvis_roll=2.0, pelvis_yaw=1.0,
    spine_flex=3.0, flex_t=0.0,
    neck_dyn=1.8, head_comp=0.7,
    tail_wave=1.2, tail_sway=1.4
)

# 3. Galope / Sprint Felino
sprint_gait = GaitConfig(
    name="Sprint",
    duration=14,
    stride_ratio=1.30,
    step_ratio=0.28,
    ext_mid=0.76,
    bounce_ratio=0.09,
    phases={"paw_control_L": 0.5, "paw_control_R": 0.6, "leg3_control_L": 0.0, "leg3_control_R": 0.1},
    duty_factor=0.35,
    damping_factor=1.0,
    sway_x=0.002,
    paw_in=0.008,
    pitch_amp=6.0,
    pitch_t=0.55,
    pelvis_roll=0.5,
    pelvis_yaw=0.6,
    spine_flex=9.5,
    flex_t=0.92,
    neck_dyn=4.0,
    head_comp=0.78,
    tail_wave=3.2,
    tail_sway=1.2
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
    ensure_object_mode(animator.rig)

    print("[4/4] Guardando nuevo archivo...")
    bpy.ops.wm.save_as_mainfile(filepath=OUT)

    print("\n" + "=" * 50)
    print(f"¡ÉXITO! Archivo con animaciones guardado en:\n{OUT}")
    print("=" * 50 + "\n")
