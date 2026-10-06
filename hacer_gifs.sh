#!/usr/bin/env bash
# ==============================================================================
# hacer_gifs.sh
# Renderiza vistas ortográficas a PNG y genera GIFs a partir de un archivo .blend.
# Pregunta de forma interactiva qué archivo .blend procesar si no se pasa como argumento.
# ==============================================================================

set -e

# Ir al directorio del script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================================="
echo " 🎬 RENDERIZADOR PROCEDURAL DE VISTAS Y GIFS (Blender)"
echo "=========================================================="

# 1. Comprobar herramientas necesarias
if ! command -v blender &> /dev/null; then
    echo "❌ Error: 'blender' no está instalado o no se encuentra en el PATH."
    exit 1
fi

if ! command -v ffmpeg &> /dev/null; then
    echo "⚠️  Aviso: 'ffmpeg' no está instalado."
    echo "   Se generarán los frames PNG pero no los GIFs."
    echo "   Instala ffmpeg con: sudo apt install ffmpeg"
    echo ""
fi

# 2. Detectar archivos .blend en el directorio actual (excluyendo .blend1, etc.)
shopt -s nullglob
BLEND_FILES=( *.blend )
shopt -u nullglob

SELECTED_BLEND=""

# Si se pasó como argumento directo por CLI (ej: ./hacer_gifs.sh mao_animado_v2.blend)
if [ -n "$1" ]; then
    CANDIDATE="$1"
    if [[ "$CANDIDATE" != *.blend ]] && [ -f "${CANDIDATE}.blend" ]; then
        CANDIDATE="${CANDIDATE}.blend"
    fi
    if [ -f "$CANDIDATE" ]; then
        SELECTED_BLEND="$CANDIDATE"
        echo "📂 Archivo seleccionado por argumento: $SELECTED_BLEND"
    else
        echo "❌ Error: El archivo '$1' no existe en $SCRIPT_DIR"
        exit 1
    fi
fi

# 3. Preguntar interactivamente si no se pasó argumento
if [ -z "$SELECTED_BLEND" ]; then
    if [ ${#BLEND_FILES[@]} -eq 0 ]; then
        echo "⚠️ No se encontraron archivos .blend en la carpeta actual."
        echo ""
        read -r -p "Escribe la ruta o nombre del archivo .blend a procesar: " MANUAL_INPUT
        MANUAL_INPUT="$(echo "$MANUAL_INPUT" | xargs)"
        if [ -n "$MANUAL_INPUT" ]; then
            if [[ "$MANUAL_INPUT" != *.blend ]] && [ -f "${MANUAL_INPUT}.blend" ]; then
                MANUAL_INPUT="${MANUAL_INPUT}.blend"
            fi
            if [ -f "$MANUAL_INPUT" ]; then
                SELECTED_BLEND="$MANUAL_INPUT"
            else
                echo "❌ Error: El archivo '$MANUAL_INPUT' no existe."
                exit 1
            fi
        else
            echo "❌ Operación cancelada: No se especificó ningún archivo."
            exit 1
        fi
    else
        echo "Archivos .blend encontrados en la carpeta:"
        echo ""
        for i in "${!BLEND_FILES[@]}"; do
            idx=$((i + 1))
            echo "  [$idx] ${BLEND_FILES[$i]}"
        done
        echo ""

        while [ -z "$SELECTED_BLEND" ]; do
            read -r -p "👉 ¿Qué archivo .blend quieres renderizar? (Número [1-${#BLEND_FILES[@]}] o nombre): " USER_INPUT
            USER_INPUT="$(echo "$USER_INPUT" | xargs)"

            if [[ "$USER_INPUT" =~ ^[0-9]+$ ]] && [ "$USER_INPUT" -ge 1 ] && [ "$USER_INPUT" -le ${#BLEND_FILES[@]} ]; then
                idx=$((USER_INPUT - 1))
                SELECTED_BLEND="${BLEND_FILES[$idx]}"
            elif [ -n "$USER_INPUT" ]; then
                CANDIDATE="$USER_INPUT"
                if [[ "$CANDIDATE" != *.blend ]] && [ -f "${CANDIDATE}.blend" ]; then
                    CANDIDATE="${CANDIDATE}.blend"
                fi
                if [ -f "$CANDIDATE" ]; then
                    SELECTED_BLEND="$CANDIDATE"
                else
                    echo "❌ No se encontró '$USER_INPUT'. Por favor intenta de nuevo."
                fi
            else
                echo "❌ Por favor introduce un número o nombre válido."
            fi
        done
    fi
fi

echo ""
echo "🎯 Archivo a renderizar: $SELECTED_BLEND"
echo ""

# 4. Parámetros opcionales (con valores por defecto en ENTER)
echo "Vistas disponibles: lateral, frontal, trasera, inferior, superior"
read -r -p "Vistas a renderizar [Enter para todas]: " VISTAS_INPUT
VISTAS_INPUT="$(echo "$VISTAS_INPUT" | xargs)"

read -r -p "Framerate (FPS) para el GIF [Enter para 24]: " FPS_INPUT
FPS_INPUT="$(echo "$FPS_INPUT" | xargs)"

read -r -p "Resolución en píxeles [Enter para 600]: " RES_INPUT
RES_INPUT="$(echo "$RES_INPUT" | xargs)"

EXTRA_ARGS=()
if [ -n "$VISTAS_INPUT" ]; then
    EXTRA_ARGS+=( "--vistas" "$VISTAS_INPUT" )
fi
if [ -n "$FPS_INPUT" ]; then
    EXTRA_ARGS+=( "--fps" "$FPS_INPUT" )
fi
if [ -n "$RES_INPUT" ]; then
    EXTRA_ARGS+=( "--res" "$RES_INPUT" )
fi

echo ""
echo "🚀 Ejecutando Blender en segundo plano..."
echo "----------------------------------------------------------"

# 5. Ejecutar render_views.py pasando el .blend seleccionado
blender -b "$SELECTED_BLEND" -P render_views.py -- "${EXTRA_ARGS[@]}"

echo "----------------------------------------------------------"
echo "🎉 ¡Todo listo!"
