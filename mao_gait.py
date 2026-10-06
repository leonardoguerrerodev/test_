"""
Locomocion de Mao sobre el rig que genera Rigify (metarig de gato).

Los scripts de referencia (walk_lib_v3.py, build_walk_v3.py,
cat_locomotion_system-v2.py) estan escritos para otro rig ("Rig_Gato") y con
longitudes absolutas. Este modulo conserva lo que esos scripts miden bien
(fases, ciclo, angulos, tiempos, curvas del video) y vuelve a calcular todo lo
que depende del tamano a partir de las medidas del rig que haya en la escena.

Ideas que se mantienen:
  - orden de apoyo trasera -> delantera del mismo lado -> trasera opuesta ...
    (fase pi/2 entre patas en v2, 0.21 de ciclo medido en v3)
  - apoyo lineal (el pie no se arrastra) y balanceo con tangente igual a la
    velocidad del suelo (sin patinazo al tocar)
  - elevacion rapida y descenso suave, pitch de la pata medido del video
  - rebote del cuerpo 2 veces por zancada, contra-rotacion de pelvis y torax
  - onda de la cola con retraso por segmento

Lo que cambia: toda longitud se expresa como fraccion de la altura de la pata
y se multiplica por la altura de la pata de Mao (ver MEDIDAS_REF y escalar()).

Uso (Blender, archivo con el rig generado por Rigify llamado "rig"):
    import mao_gait
    mao_gait.report()                      # tabla de medidas y escalas
    mao_gait.build("walk")                 # crea la accion "Mao_walk"
    mao_gait.build_all()                   # walk, stealth, normal, sprint
Sin interfaz:  blender -b mao_rigify_fitted.blend -P mao_gait.py
"""

import math
import os

# ---------------------------------------------------------------------------
# Rig de destino (nombres de controles del rig Rigify de gato)
# ---------------------------------------------------------------------------

RIG_NAME = "rig"
FEET = {  # clave: (control IK, hueso ORG del extremo, hueso ORG de la punta, lado, es_delantera)
    "H_R": ("foot_ik.R", "ORG-foot.R", "ORG-r_toe.R", -1, False),
    "H_L": ("foot_ik.L", "ORG-foot.L", "ORG-r_toe.L", +1, False),
    "F_R": ("hand_ik.R", "ORG-hand.R", "ORG-f_toe.R", -1, True),
    "F_L": ("hand_ik.L", "ORG-hand.L", "ORG-f_toe.L", +1, True),
}
HIP_BONE = {False: "ORG-thigh.", True: "ORG-upper_arm."}
CHAIN = {False: ("ORG-thigh.", "ORG-shin.", "ORG-foot."),
         True: ("ORG-upper_arm.", "ORG-forearm.", "ORG-hand.")}
TAIL = ["tail.001", "tail.002", "tail.003", "tail.004"]

# ---------------------------------------------------------------------------
# Medidas del rig para el que se escribieron los scripts de referencia
# (Rig_Gato en mao_rigged3.blend, mismo mesh, suelo en z=-0.584)
# ---------------------------------------------------------------------------

MEDIDAS_REF = {
    "h_hind": 0.668,     # altura cadera -> control del pie (en reposo)
    "h_front": 0.679,    # altura hombro -> control de la pata
    "reach_hind": 0.731, # suma muslo+pantorrilla+metatarso
    "reach_front": 0.690,
    "sink": 0.08,        # descenso del cuerpo con que se calibro v3 (build_walk_v3: D=0.08)
    "hip_half": 0.091,   # media separacion de caderas (x)
    "shoulder_half": 0.1135,
    "foot_len_hind": 0.088,
    "foot_len_front": 0.117,
}
# Inclinacion (grados, sobre la horizontal, + = hacia arriba) del reposo del cuello en Rig_Gato
REF_REST_INCL = {"chest": 1.4, "neck": 24.3, "head": 25.7}
# Postura estatica de v3 (nariz abajo = +): torax 8, cuello 13.5, cabeza -23 (relativos)
REF_STATIC_REL = (8.0, 13.5, -23.0)

# ---------------------------------------------------------------------------
# Marchas. Todo adimensional: longitudes como fraccion de la altura de la pata.
# stride = recorrido del pie durante el apoyo; lift = altura maxima del pie.
# ---------------------------------------------------------------------------

PITCH_STANCE = [(0.0, -6.0), (0.12, 0.0), (0.60, 0.0), (0.85, 14.0), (1.0, 30.0)]
PITCH_SWING = [(0.12, 52.0), (0.35, 38.0), (0.60, 12.0), (0.85, -8.0), (1.0, -6.0)]


def _gait(T, duty, td, stride, lift, bob, sink=0.0, bob_cycles=2, pitch=True,
          center_hind=-0.12, center_front=0.03, v3_body=False):
    return dict(T=T, duty=duty, td=td, stride=stride, lift=lift, bob=bob,
                sink=sink, bob_cycles=bob_cycles, pitch=pitch,
                center_hind=center_hind, center_front=center_front, v3_body=v3_body)


GAITS = {
    # v3: medido del video lateral. stride y lift de v3 divididos por la altura efectiva
    # de Rig_Gato con el cuerpo hundido (0.588 trasera, 0.599 delantera).
    "walk": _gait(T=48, duty=35 / 48,
                  td={"H_R": 0.0, "F_R": 0.21, "H_L": 0.50, "F_L": 0.71},
                  stride=(0.986, 0.968), lift=(0.213, 0.192), bob=0.034, v3_body=True),
    # v2: stride y altura de paso divididos por la altura de reposo de Rig_Gato (0.668 / 0.679)
    "stealth": _gait(T=40, duty=0.70,
                     td={"H_L": 0.0, "F_L": 0.25, "H_R": 0.5, "F_R": 0.75},
                     stride=(0.599, 0.589), lift=(0.120, 0.118), bob=0.015, sink=0.18,
                     pitch=False),
    "normal": _gait(T=24, duty=0.60,
                    td={"H_L": 0.0, "F_L": 0.25, "H_R": 0.5, "F_R": 0.75},
                    stride=(0.749, 0.736), lift=(0.180, 0.177), bob=0.045, pitch=False),
    "sprint": _gait(T=14, duty=0.35,
                    td={"H_L": 0.0, "F_L": 0.5, "H_R": 0.1, "F_R": 0.6},
                    stride=(1.796, 1.767), lift=(0.374, 0.368), bob=0.22, bob_cycles=1,
                    pitch=False, center_hind=0.0, center_front=0.0),
}

# Amplitudes angulares y laterales de v3 (angulos: no escalan; laterales: ancho del cuerpo)
V3_ANG = dict(pelvis_roll=2.5, thorax_roll=1.0, pelvis_yaw=2.0, neck_dyn=5.5)
V3_LAT = dict(sway_x=0.008, sway_y=0.005, track_hind=0.018, track_front=0.008)
V3_TAIL = dict(sway=(0.8, 0.8), wave=(0.8, 0.4), delay_sway=3.0, delay_wave=2.0, peak_frame=8)
# Aduccion del pie en el balanceo (m en Rig_Gato; se escala con el ancho). walk_lib_v3.py usa 0, pero la
# grafica de curvas que acompana a v3 muestra ~0.016 (trasera) y ~0.010 (delantera): activalo aqui.
PAW_IN = (0.0, 0.0)
REACH_MARGIN = 0.97   # no pedir mas del 97% de la longitud total de la cadena


# ---------------------------------------------------------------------------
# Utilidades matematicas propias
# ---------------------------------------------------------------------------

def monotone_cubic(xs, ys):
    """Interpolador cubico monotono (Fritsch-Carlson). Devuelve f(x)."""
    n = len(xs)
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    m = [0.0] * n
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, n - 1):
        m[i] = 0.0 if d[i - 1] * d[i] <= 0 else (d[i - 1] + d[i]) / 2.0
    for i in range(n - 1):
        if d[i] == 0:
            m[i] = m[i + 1] = 0.0
            continue
        a, b = m[i] / d[i], m[i + 1] / d[i]
        s = a * a + b * b
        if s > 9:
            t = 3.0 / math.sqrt(s)
            m[i], m[i + 1] = t * a * d[i], t * b * d[i]

    def f(x):
        x = min(max(x, xs[0]), xs[-1])
        i = max(0, min(n - 2, next((k for k in range(n - 1) if xs[k + 1] >= x), n - 2)))
        t = (x - xs[i]) / h[i]
        return ((2 * t**3 - 3 * t**2 + 1) * ys[i] + (t**3 - 2 * t**2 + t) * h[i] * m[i]
                + (-2 * t**3 + 3 * t**2) * ys[i + 1] + (t**3 - t**2) * h[i] * m[i + 1])
    return f


def pitch_curve(duty):
    """Pitch de la pata (grados, + = talon arriba) en funcion de la fase 0..1 del ciclo."""
    xs = [f * duty for f, _ in PITCH_STANCE]
    ys = [v for _, v in PITCH_STANCE]
    for f, v in PITCH_SWING[0:]:
        xs.append(duty + f * (1 - duty))
        ys.append(v)
    return monotone_cubic(xs, ys)


def hermite(y0, y1, m0, m1, s):
    h00 = 2 * s**3 - 3 * s**2 + 1
    h10 = s**3 - 2 * s**2 + s
    h01 = -2 * s**3 + 3 * s**2
    h11 = s**3 - s**2
    return h00 * y0 + h10 * m0 + h01 * y1 + h11 * m1


def foot_path(p, T, duty, c, stride, lift, pitch_fn=None, swing="hermite"):
    """
    Posicion del pie respecto al cuerpo en el ciclo. p: frame dentro del ciclo (0..T).
    Devuelve (y, z, pitch_grados, s). y + = hacia atras (el gato mira a -Y); s = fraccion del
    balanceo (0..1) o None si el pie esta en apoyo.
    swing="hermite": tangente = velocidad del suelo en ambos extremos (sin patinazo).
    swing="ellipse": semielipse de la formula del apunte, para comparar.
    """
    st = duty * T
    sw = T - st
    V = stride / st
    p = p % T
    s = None
    if p < st:
        y = c + V * (p - st / 2)
        z = 0.0
    else:
        s = (p - st) / sw
        y0, y1 = c + V * st / 2, c - V * st / 2
        if swing == "ellipse":
            y = (y0 + y1) / 2 + (y0 - y1) / 2 * math.cos(math.pi * s)
            z = lift * math.sin(math.pi * s)
        else:
            y = hermite(y0, y1, V * sw, V * sw, s)
            z = lift * math.sin(math.pi * s**0.7) ** 1.1
    pitch = pitch_fn(p / T) if pitch_fn else 0.0
    return y, z, pitch, s


# ---------------------------------------------------------------------------
# Medidas del rig y escalas respecto a Rig_Gato
# ---------------------------------------------------------------------------

def measure(rig):
    """Lee el reposo del rig: alturas de pata, alcance, anchos y largo del cuerpo."""
    from mathutils import Vector
    M = rig.matrix_world
    B = rig.data.bones

    def head(n): return M @ B[n].head_local
    def tail(n): return M @ B[n].tail_local

    m = {"legs": {}}
    for key, (ctrl, org_end, org_tip, side, front) in FEET.items():
        sfx = "R" if side < 0 else "L"
        hip = head(HIP_BONE[front] + sfx)
        end, tip = tail(org_end), tail(org_tip)
        lens = [B[n + sfx].length for n in CHAIN[front]]
        m["legs"][key] = dict(hip=hip, end=end, tip=tip, lens=lens, reach=sum(lens),
                              h=hip.z - end.z, dist=(hip - end).length,
                              ctrl=head(ctrl), foot_len=(tip - end).length)
    h, f = m["legs"]["H_L"], m["legs"]["F_L"]
    m["h_hind"], m["h_front"] = h["h"], f["h"]
    m["hip_half"] = abs(h["hip"].x)
    m["shoulder_half"] = abs(f["hip"].x)
    m["body_len"] = h["hip"].y - f["hip"].y
    m["ground"] = min(l["tip"].z for l in m["legs"].values())
    return m


def escalar(m):
    """Factores de escala de longitudes: nuevo rig / Rig_Gato (con el hundimiento de v3)."""
    r = MEDIDAS_REF
    return {
        "hind": m["h_hind"] / (r["h_hind"] - r["sink"]),
        "front": m["h_front"] / (r["h_front"] - r["sink"]),
        "hind_rest": m["h_hind"] / r["h_hind"],
        "front_rest": m["h_front"] / r["h_front"],
        "width_hind": m["hip_half"] / r["hip_half"],
        "width_front": m["shoulder_half"] / r["shoulder_half"],
        "mean": (m["h_hind"] + m["h_front"]) / (r["h_hind"] + r["h_front"] - 2 * r["sink"]),
    }


def resolve(name, m, overrides=None):
    """
    Convierte una marcha adimensional en longitudes del rig actual.
    El recorrido de apoyo es el MISMO en las cuatro patas: el cuerpo avanza a una sola velocidad
    (V = recorrido / frames de apoyo); si cada par tuviera su propio recorrido, un par patinaria
    sobre el suelo. Se toma el menor de los recorridos que permite cada pata (angulo de zancada
    y alcance del IK).
    """
    g = dict(GAITS[name])
    g.update(overrides or {})
    h = {False: m["h_hind"], True: m["h_front"]}
    cand, limit = {}, {}
    out = dict(g)
    out["lift_abs"], out["center_abs"] = {}, {}
    for key, (_, _, _, side, front) in FEET.items():
        S = g["stride"][1 if front else 0] * h[front]
        c = (g["center_front"] if front else g["center_hind"]) * h[front]
        leg = m["legs"][key]
        dmax = math.sqrt(max((REACH_MARGIN * leg["reach"]) ** 2 - leg["h"] ** 2, 0.0))
        smax = 2 * max(dmax - abs(c), 0.0)
        cand[key] = min(S, smax)
        limit[key] = "alcance" if S > smax else "angulo"
        out["lift_abs"][key] = g["lift"][1 if front else 0] * h[front]
        out["center_abs"][key] = c
    key_min = min(cand, key=cand.get)
    out["stride_common"] = cand[key_min]
    out["stride_limit"] = (key_min, limit[key_min])
    out["stride_abs"] = {k: cand[key_min] for k in FEET}
    out["clamped"] = {k: limit[k] == "alcance" for k in FEET}
    out["speed_per_frame"] = cand[key_min] / (g["duty"] * g["T"])
    out["bob_abs"] = g["bob"] * (m["h_hind"] + m["h_front"]) / 2
    out["sink_abs"] = g["sink"] * (m["h_hind"] + m["h_front"]) / 2
    return out


def report(rig=None):
    import bpy
    rig = rig or bpy.data.objects[RIG_NAME]
    m = measure(rig)
    r = MEDIDAS_REF
    s = escalar(m)
    print("%-34s %9s %9s %8s" % ("medida", "Rig_Gato", "rig nuevo", "escala"))
    rows = [("altura cadera->pie (trasera)", r["h_hind"], m["h_hind"]),
            ("altura hombro->pie (delantera)", r["h_front"], m["h_front"]),
            ("alcance trasera", r["reach_hind"], m["legs"]["H_L"]["reach"]),
            ("alcance delantera", r["reach_front"], m["legs"]["F_L"]["reach"]),
            ("media separacion de caderas", r["hip_half"], m["hip_half"]),
            ("media separacion de hombros", r["shoulder_half"], m["shoulder_half"])]
    for n, a, b in rows:
        print("%-34s %9.3f %9.3f %8.2f" % (n, a, b, b / a))
    print("extension en reposo trasera: %.0f%%  delantera: %.0f%%" % (
        100 * m["legs"]["H_L"]["dist"] / m["legs"]["H_L"]["reach"],
        100 * m["legs"]["F_L"]["dist"] / m["legs"]["F_L"]["reach"]))
    print("escalas usadas:", {k: round(v, 3) for k, v in s.items()})
    return m


# ---------------------------------------------------------------------------
# Rig: conversion de vectores de armature a espacio local del hueso
# ---------------------------------------------------------------------------

def _rest3(rig, name):
    return rig.data.bones[name].matrix_local.to_3x3()


def _loc(rig, name, v):
    from mathutils import Vector
    return _rest3(rig, name).inverted() @ (rig.matrix_world.to_3x3().inverted() @ Vector(v))


def _quat(rig, name, rots):
    """rots: lista de (eje, angulo_rad) en espacio armature, en orden."""
    from mathutils import Matrix, Vector
    R = Matrix.Identity(3)
    for axis, ang in rots:
        R = Matrix.Rotation(ang, 3, Vector(axis)) @ R
    r = _rest3(rig, name)
    return (r.inverted() @ R @ r).to_quaternion()


X, Y, Z = (1, 0, 0), (0, 1, 0), (0, 0, 1)
D2R = math.pi / 180.0


def _incl_bone(rig, name):
    """Inclinacion (grados) de un hueso sobre la horizontal, + = punta hacia arriba, mirando a -Y."""
    b = rig.data.bones[name]
    dy = b.head_local.y - b.tail_local.y
    dz = b.tail_local.z - b.head_local.z
    return math.degrees(math.atan2(dz, dy))


def static_pose(rig):
    """
    La postura estatica de v3 esta en angulos RELATIVOS al reposo de Rig_Gato. Se convierte a
    angulos ABSOLUTOS (los que se midieron en el video) y se vuelve a relativizar con el
    reposo del rig nuevo. Devuelve (torax, cuello, cabeza) en radianes, nariz abajo = +.
    """
    t, n, h = REF_STATIC_REL
    abs_chest = REF_REST_INCL["chest"] - t
    abs_neck = REF_REST_INCL["neck"] - (t + n)
    abs_head = REF_REST_INCL["head"] - (t + n + h)
    rt = _incl_bone(rig, "ORG-spine.003") - abs_chest
    rn = (_incl_bone(rig, "neck") - abs_neck) - rt
    rh = (_incl_bone(rig, "head") - abs_head) - (rt + rn)
    return rt * D2R, rn * D2R, rh * D2R


# ---------------------------------------------------------------------------
# Construccion de la accion
# ---------------------------------------------------------------------------

def build(name="walk", overrides=None, static=True, action_name=None):
    import bpy
    rig = bpy.data.objects[RIG_NAME]
    m = measure(rig)
    sc = escalar(m)
    g = resolve(name, m, overrides)
    T, duty = g["T"], g["duty"]
    st = duty * T
    pf = pitch_curve(duty) if g["pitch"] else None
    sw_ = sc["width_hind"]

    # asegura IK en las 4 patas
    for n in ("thigh_parent.L", "thigh_parent.R", "upper_arm_parent.L", "upper_arm_parent.R"):
        if n in rig.pose.bones:
            rig.pose.bones[n]["IK_FK"] = 0.0

    aname = action_name or ("Mao_" + name)
    if aname in bpy.data.actions:
        bpy.data.actions.remove(bpy.data.actions[aname])
    act = bpy.data.actions.new(aname)
    act.use_fake_user = True
    rig.animation_data_create()
    rig.animation_data.action = act
    pbs = rig.pose.bones
    for pb in pbs:
        pb.rotation_mode = "QUATERNION"

    shift = 12.5 * T / 32.0 if g["v3_body"] else 0.0
    td = {k: (v * T + shift) % T for k, v in g["td"].items()}
    t_ref = td.get("H_R", td.get("H_L", 0.0))
    s_neck = static_pose(rig) if (static and g["v3_body"]) else (0.0, 0.0, 0.0)

    for f in range(1, T + 2):
        t = (f - 1) % T
        w1 = 2 * math.pi * (t - t_ref) / T
        n = g["bob_cycles"]
        peak = t_ref - 0.224 * T if g["v3_body"] else t_ref - 0.25 * T
        w2 = 2 * math.pi * n * (t - peak) / T

        ypaw = {}
        for key, (ctrl, _, _, side, front) in FEET.items():
            c = g["center_abs"][key]
            y, z, pitch, s = foot_path((t - td[key]) % T, T, duty, c, g["stride_abs"][key],
                                       g["lift_abs"][key], pf)
            ypaw[key] = y - c
            wscale = sc["width_front"] if front else sc["width_hind"]
            lat = V3_LAT["track_front" if front else "track_hind"] * wscale
            # aduccion en el balanceo: la pata se acerca a la linea media (+ = hacia el centro)
            pin = PAW_IN[1 if front else 0] * wscale
            xin = -side * pin * math.sin(math.pi * s) ** 1.2 if s is not None else 0.0
            pb = pbs[ctrl]
            pb.location = _loc(rig, ctrl, (side * lat + xin, y, z))
            pb.rotation_quaternion = _quat(rig, ctrl, [(X, pitch * D2R)])
            pb.keyframe_insert("location", frame=f, group=ctrl)
            pb.keyframe_insert("rotation_quaternion", frame=f, group=ctrl)

        # cuerpo: sube y baja n veces por zancada, balanceo lateral y avance
        dz = -g["sink_abs"] + g["bob_abs"] * math.cos(w2)
        dy = V3_LAT["sway_y"] * sc["mean"] * math.cos(w2 - 0.8) if g["v3_body"] else 0.0
        dx = V3_LAT["sway_x"] * sw_ * math.sin(w1) if g["v3_body"] else 0.0
        pbs["torso"].location = _loc(rig, "torso", (dx, dy, dz))
        pbs["torso"].keyframe_insert("location", frame=f, group="torso")

        if g["v3_body"]:
            yaw = V3_ANG["pelvis_yaw"] * D2R * math.cos(w1)
            gph = math.cos(2 * math.pi * (t - (t_ref - (T - st) / 2)) / T)
            roll = V3_ANG["pelvis_roll"] * D2R * gph
            tr = -V3_ANG["thorax_roll"] * D2R * gph
            dyn = V3_ANG["neck_dyn"] * D2R * math.cos(w2)
            pbs["hips"].rotation_quaternion = _quat(rig, "hips", [(Y, roll), (Z, yaw)])
            pbs["chest"].rotation_quaternion = _quat(
                rig, "chest", [(X, s_neck[0]), (Y, tr), (Z, -1.6 * yaw)])
            pbs["neck"].rotation_quaternion = _quat(rig, "neck", [(X, s_neck[1] + dyn), (Y, 0.3 * tr)])
            pbs["head"].rotation_quaternion = _quat(
                rig, "head", [(X, s_neck[2] - 0.5 * dyn), (Y, -0.4 * (roll + tr)), (Z, 0.8 * yaw)])
            for nme in ("hips", "chest", "neck", "head"):
                pbs[nme].keyframe_insert("rotation_quaternion", frame=f, group=nme)
            # cola: la onda del video tenia 5 segmentos; se reparte en los 4 del rig nuevo
            for j, tn in enumerate(TAIL):
                i = 1 + 4.0 * j / (len(TAIL) - 1)
                sway = D2R * V3_TAIL["sway"][0] * (1 + V3_TAIL["sway"][1] * i) * math.sin(
                    2 * math.pi * (t - V3_TAIL["delay_sway"] * i) / T)
                wave = D2R * (V3_TAIL["wave"][0] + V3_TAIL["wave"][1] * i) * math.cos(
                    2 * math.pi * 2 * (t - V3_TAIL["delay_wave"] * i - V3_TAIL["peak_frame"]) / T)
                pbs[tn].rotation_quaternion = _quat(rig, tn, [(Z, sway), (X, wave)])
                pbs[tn].keyframe_insert("rotation_quaternion", frame=f, group=tn)

    try:  # ciclico
        for layer in act.layers:
            for strip in layer.strips:
                for cb in strip.channelbags:
                    for fc in cb.fcurves:
                        fc.modifiers.new("CYCLES")
    except Exception as e:  # API de acciones distinta
        print("cycles:", e)
    bpy.context.scene.frame_start, bpy.context.scene.frame_end = 1, T
    lim, why = g["stride_limit"]
    print("%s: recorrido de apoyo %.3f m (limita la pata %s por %s), %.4f m/frame, "
          "zancada completa %.3f m" % (name, g["stride_common"], lim, why, g["speed_per_frame"],
                                       g["speed_per_frame"] * T))
    return act


def build_all():
    import bpy
    acts = [build(n) for n in GAITS]
    bpy.context.scene.frame_set(1)
    return acts


# ---------------------------------------------------------------------------
# Salto: y(t) = -g t^2 / 2 + v0 t + y0
# ---------------------------------------------------------------------------

def jump_params(apex, air_time):
    """
    apex: altura maxima sobre el punto de salida; air_time: segundos en el aire (salida y
    llegada a la misma altura). g_escena = 8 apex / air_time^2: en un modelo mas grande que
    un gato real, g real (9.81) da saltos demasiado lentos; esta g hace que apex y tiempo sean
    los que se piden.
    """
    g = 8.0 * apex / air_time ** 2
    v0 = g * air_time / 2.0
    return g, v0


def jump_land(apex, air_time, dy):
    """
    Salto que sube a `apex` sobre el punto de salida y aterriza en una superficie a altura dy
    (dy > 0: sube a la camioneta; dy < 0: baja). Devuelve (g, v0, t_aterrizaje). Con dy distinto
    de 0 el tiempo hasta la superficie es t = (v0 + sqrt(v0^2 - 2 g dy)) / g.
    """
    g, v0 = jump_params(apex, air_time)
    disc = v0 * v0 - 2 * g * dy
    if disc < 0:
        raise ValueError("apex insuficiente para llegar a dy=%.3f" % dy)
    return g, v0, (v0 + math.sqrt(disc)) / g


def jump_curve(apex, air_time, fps=24, y0=0.0):
    g, v0 = jump_params(apex, air_time)
    n = max(2, int(round(air_time * fps)))
    return [(-g * t * t / 2 + v0 * t + y0) for t in (i / fps for i in range(n + 1))]


if __name__ == "__main__":
    import bpy
    if RIG_NAME in bpy.data.objects:
        report()
        build_all()
        bpy.data.objects[RIG_NAME].animation_data.action = bpy.data.actions["Mao_walk"]
        bpy.context.scene.frame_set(1)
        if bpy.app.background and bpy.data.filepath:
            out = os.path.splitext(bpy.data.filepath)[0] + "_animado.blend"
            bpy.ops.wm.save_as_mainfile(filepath=out)
            print("Guardado: " + out)
    else:
        print("No hay un objeto '%s'. Genera el rig con Rigify primero." % RIG_NAME)
