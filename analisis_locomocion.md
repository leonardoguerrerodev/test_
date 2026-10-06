# Análisis de la locomoción de Mao

Compara los scripts de marcha y carrera (`walk_lib_v3.py`, `build_walk_v3.py`, `cat_locomotion_system-v2.py`) y las fórmulas del apunte con el modelo actual de Mao. Las medidas salen de `mao_rigged3.blend` (rig `Rig_Gato`), de `mao_rigify.blend` y del rig que genera Rigify con `rigify_cat_fit.py`, todas leídas con `bpy` 5.2.2. El código nuevo está en `mao_gait.py`.

## El mesh es el mismo

`Mao` mide `0.435 × 1.904 × 1.255` (ancho, largo, alto con orejas) en `mao_rigged3.blend` y en `mao_rigify.blend`. El lomo llega a `z=0.96` y el vientre a `0.42`. Las diferencias de tamaño entre los dos rigs vienen de los huesos, no del modelo.

## Qué se conserva

Estos datos no dependen del tamaño y se usan tal cual:

- Orden de apoyo trasera, delantera del mismo lado, trasera opuesta, delantera opuesta. v2 usa fases `0, 0.25, 0.5, 0.75`, igual que la fórmula del apunte. v3 usa `0, 0.21, 0.5, 0.71`, medido del video.
- Ciclo de 48 frames con 35 de apoyo (73 %).
- Apoyo lineal y balanceo con tangente igual a la velocidad del suelo.
- Elevación rápida con pico al 37 % del balanceo y descenso suave.
- Curva de pitch de la pata: de `-8°` a `52°`.
- Dos subidas y bajadas del cuerpo por zancada, contra-rotación de pelvis y tórax, onda de la cola con retraso por segmento.
- Todos los ángulos (roll de pelvis `2.5°`, de tórax `1°`, yaw `2°`, cabeceo `5.5°`) y todos los tiempos.

## Qué depende del rig

Medidas en reposo, en metros:

| medida | `Rig_Gato` | rig nuevo | escala |
|---|---|---|---|
| altura cadera a pie, trasera | 0.668 | 0.459 | 0.69 |
| altura hombro a pie, delantera | 0.679 | 0.505 | 0.74 |
| alcance trasera (suma de huesos) | 0.731 | 0.734 | 1.00 |
| alcance delantera | 0.690 | 0.614 | 0.89 |
| media separación de caderas | 0.091 | 0.119 | 1.31 |
| media separación de hombros | 0.114 | 0.130 | 1.15 |
| extensión en reposo, trasera | 92 % | 63 % | |
| extensión en reposo, delantera | 99 % | 83 % | |

`Rig_Gato` tiene las patas casi rectas en reposo. Por eso v3 hunde el cuerpo `D=0.08` al caminar: con las patas al 99 % no hay margen para mover el pie. En el rig nuevo las patas están plegadas, como las del mesh (corvejón a `y≈0.50`), y no hace falta hundir nada.

Extensión de la pata durante la marcha, aproximada con la pierna recta (`√(h² ± S/2)`):

| | apoyo medio | extremo del paso |
|---|---|---|
| `Rig_Gato` trasera, v3 | 80 % | 90 % |
| `Rig_Gato` delantera, v3 | 87 % | 96 % |
| rig nuevo trasera | 63 % | 70 % |
| rig nuevo delantera | 82 % | 90 % |

Con el 96 % de la delantera, la pata queda casi estirada en el extremo del paso. Es probablemente la razón por la que v3 bajó `STRIDE` de `0.63` a `0.58`; el script no lo dice.

## Cómo se adaptó cada parámetro

Regla general: las longitudes se expresan como fracción de la altura de la pata y se multiplican por la del rig nuevo. Con eso el ángulo de zancada queda igual que en el video.

| parámetro | v3 | regla | Mao, walk |
|---|---|---|---|
| recorrido de apoyo (`STRIDE`) | 0.58 | proporcional a la altura efectiva de la pata (`0.668 − 0.08 = 0.588`) | 0.452, igual en las cuatro patas |
| altura de paso, trasera / delantera | 0.125 / 0.115 | misma fracción de la altura | 0.098 / 0.097 |
| hundimiento `D` | 0.08 | compensa las patas rectas | 0 |
| rebote del cuerpo | 0.02 | 3.4 % de la altura media de pata | 0.016 |
| balanceo lateral del cuerpo | 0.008 | ancho de caderas, `×1.31` | 0.0105 |
| avance del cuerpo | 0.005 | altura de pata | 0.004 |
| separación lateral de patas, tras / del | 0.018 / 0.008 | ancho, `×1.31` / `×1.15` | 0.024 / 0.009 |
| centro de apoyo trasero | `-0.08` | `-0.12` de la altura | `-0.055` |
| postura estática de tórax, cuello y cabeza | `8°, 13.5°, -23°` | se pasa a ángulos absolutos y se recalcula con el reposo nuevo | `7.3°, 20.0°, -22.3°` |
| cola | 5 segmentos | mismos ángulos y retrasos repartidos en 4 | |

La postura estática es el caso donde copiar el número da un resultado distinto. Los `8°, 13.5°, -23°` son relativos al reposo de `Rig_Gato`, donde el cuello sube `24°`. En el rig nuevo sube `30°`. El script los convierte a lo que se midió en el video (tórax `-6.6°`, cuello `2.8°`, cabeza `27.2°` sobre la horizontal) y vuelve a calcular el giro necesario.

La zancada es la misma en las cuatro patas porque el cuerpo avanza a una sola velocidad. Si cada par tuviera su recorrido, un par patinaría. Se toma el menor que permite cada pata. En walk limita la trasera por ángulo.

Velocidad resultante:

| | recorrido de apoyo | zancada completa | por frame | a 24 fps |
|---|---|---|---|---|
| v3 en `Rig_Gato` | 0.58 | 0.795 m | 0.0166 m | 0.40 m/s |
| walk en rig nuevo | 0.452 | 0.620 m | 0.0129 m | 0.31 m/s |

Las patas son más cortas, así que con los mismos 48 frames el gato avanza más despacio. Si quieres otra velocidad, cambia `T` o `stride` en `GAITS`.

## Fórmulas del apunte frente a los scripts

**Fases.** La fórmula de fase `φ, φ+π/2, φ+π, φ+3π/2` para LH, LF, RH, RF coincide con v2. v3 mide `0.21` en lugar de `0.25` entre la trasera y la delantera del mismo lado, y empieza por el lado derecho.

**Trayectoria del pie.** La elipse `x = S/2·cos(πt) + vt`, `y = H·sin(πt)` llega y sale del suelo con velocidad horizontal cero respecto al cuerpo. El pie en apoyo se mueve a `V` respecto al cuerpo. La diferencia es un salto de velocidad: el pie toca el suelo a `V` respecto al suelo y se detiene de golpe. En Mao serían `0.31 m/s` a 24 fps. El balanceo de v3 usa una spline cúbica con tangente igual a `V` en los dos extremos y toca con velocidad cero. `foot_path(..., swing="ellipse")` deja ver las dos.

**Cinemática inversa.** La ley de cosenos del apunte da los ángulos de cadera y rodilla para una pata de dos huesos. Rigify resuelve el IK por sí mismo. La fórmula sirve para comprobar el alcance: el pie solo llega si `√(h² + d²) ≤ Σ longitudes`. `resolve()` la usa con un margen del 97 %. Se verificó en el rig nuevo: el IK de la delantera sigue el control hasta `d = 0.30 m` y falla a `0.45 m` (error de 9 cm). El límite calculado es `0.32 m`.

**Centro de masa.** La gráfica muestra una oscilación de `±4.8 %` de la altura (20 a 22 cm sobre 21). v3 usa `±3.4 %`. En el módulo es el parámetro `bob`. Si lo subes a `0.048` el rebote de Mao pasa de `±0.016 m` a `±0.023 m`. El eje de la gráfica es un paso, no una zancada: por eso v3 usa dos oscilaciones por ciclo.

**Salto.** `y(t) = -g·t²/2 + v0·t + y0` se resuelve en `jump_land(apex, air_time, dy)`. La gravedad de escena sale de `g = 8·apex/air_time²`, no de 9.81: con el real un modelo de este tamaño tarda demasiado. Ejemplo para subir a una superficie a `0.8 m` con apex `0.9 m` y `0.9 s` de vuelo: `g = 8.89`, `v0 = 4.0`, llega a la superficie a los `0.6 s`. Es solo la trayectoria del cuerpo. Falta la pose de agacharse y de extender las patas.

## Problemas encontrados

1. **v2 no funciona tal cual en `Rig_Gato`.** Busca los huesos `FL_foot`, `FR_foot`, `HL_foot`, `HR_foot` y `Root`. Ninguno existe en `Rig_Gato` (sus controles son `paw_control_*`, `leg3_control_*` y `CONTROLLER`). `pose.bones.get()` devuelve `None` y la función termina sin error y sin animar nada. Además escribe `location` en ejes locales del hueso, y en `Rig_Gato` esos ejes no coinciden con los globales: el eje Y local de las patas apunta hacia atrás y el del `CONTROLLER` hacia arriba. Con el nombre corregido, `bone.location[2]` movería el cuerpo de lado. Las acciones guardadas en `mao_rigged3.blend` ya tienen los ejes corregidos (`CONTROLLER[1]` es el vertical), así que se adaptaron a mano. v3 lo resuelve convirtiendo desde espacio armature con la matriz de reposo. `mao_gait.py` hace lo mismo.
2. **El sprint de v2 pide más de lo que alcanza la pata.** `stride_y = 1.2` es 1.8 veces la altura de la pata. A `±0.6 m` del cuerpo la cadera está a `√(0.6² + 0.7²) = 0.92 m` del pie, con un alcance de `0.69` a `0.73`. En el rig nuevo la delantera se limita a `0.631` y el script lo avisa.
3. **`PAW_IN` vale 0 en v3, pero la gráfica de curvas muestra aducción de `0.016` (trasera) y `0.010` (delantera).** No puedo saber cuál de las dos es la intención. Si el eje de la gráfica es el X global, el pie derecho se mueve hacia afuera, y eso contradice el título. En `mao_gait.py` es `PAW_IN`, desactivado como en v3. Positivo acerca el pie a la línea media.
4. **El rig generado salía 14 cm corrido.** No viene de los scripts de marcha. `metarig` estaba en `y=-0.141` y Rigify genera el rig en el origen con las coordenadas locales del metarig. `rigify_cat_fit.py` ahora aplica la ubicación junto con la escala y la rotación.

## Resultados en el rig nuevo

Se generó el rig con Rigify a partir del metarig ajustado, se aplicó cada marcha y se evaluó fotograma a fotograma con `bpy` 5.2.2.

| marcha | frames | recorrido de apoyo | zancada | limita | error IK máx | punta bajo el suelo |
|---|---|---|---|---|---|---|
| walk (v3) | 48 | 0.452 | 0.620 m | trasera, ángulo | 0.1 mm | 0 |
| stealth (v2) | 40 | 0.275 | 0.393 m | trasera, ángulo | 0.1 mm | 0 |
| normal (v2) | 24 | 0.344 | 0.573 m | trasera, ángulo | 0.0 mm | 0 |
| sprint (v2) | 14 | 0.631 | 1.804 m | delantera, alcance | 0.1 mm | 0 |

En walk, los apoyos caen en los frames 19 (H_R), 29 (F_R), 43 (H_L) y 5 (F_L), con el orden y el retardo de 10 frames que mide v3. El pitch recorre de `-8°` a `51°`. La gráfica `mao_gait_curves.png` tiene el mismo formato que la tuya.

## Qué no se probó

- El bind de `Mao` al rig nuevo. Las curvas se midieron sobre los huesos, no sobre la deformación del mesh.
- Cómo se ve la animación en el viewport. Conviene mirar de perfil el tórax y el cuello con la postura estática, y el paso de la delantera.
- La rodilla trasera abierta (`KNEE_FLARE`) y la escápula de v3 no se portaron: Rigify no tiene esos huesos.
- Las gráficas de apoyo y de energía del apunte son cualitativas. No hay datos del video para comprobar los números absolutos.

## Uso

```python
import mao_gait
mao_gait.report()          # medidas del rig actual y escalas
mao_gait.build("walk")     # acción Mao_walk
mao_gait.build_all()       # walk, stealth, normal, sprint
```

Con el rig generado por Rigify y llamado `rig`. Sin interfaz: `blender -b mao_rigify_fitted.blend -P mao_gait.py` guarda `*_animado.blend`.
