"""
Ejemplo: Pipeline completo para carta a aportantes FIP Cordada.

Muestra tres formas de usar la API programática — sin tocar archivos .md.

Uso:
    python examples/carta_aportantes.py
"""

import sys
from pathlib import Path

# Add parent to path so orchestrator is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator import agent, investigate, decide, DEFAULT_GATES


def ejemplo_agente_individual():
    """Correr solo COMPILE con input directo — 1 línea."""
    print("\n=== Ejemplo 1: Agente individual (COMPILE) ===\n")

    output = agent("compile", """
    Tipo de documento: Carta a aportantes del FIP Cordada

    Destinatarios: Aportantes del FIP (familias chilenas de alto patrimonio,
    controlan 85% de Cordada SpA). No todos sofisticados en asset management.

    Objetivo estratégico: Que resuelvan la gobernanza en 15 días o el CEO
    avanza con reorganización (Opción 2).

    Tesis central: La gobernanza de Cordada no es un tema interno entre
    socios — es parte del producto. Mientras no se resuelva, el producto
    se degrada y el activo pierde valor.

    Tono: Determinación y deber fiduciario. No amenaza. No sumisión.

    Restricciones: No revelar precio de compra — eso va en la reunión.

    Estructura: Confirmo el arco propuesto (Credibilidad → Urgencia →
    Diagnóstico → Opciones → Plazos → Pedido + Cierre).
    """)

    print(output[:500] + "...\n")


def ejemplo_pipeline_con_gates():
    """Pipeline con gates — pausa en Layer 2 para review del CEO."""
    print("\n=== Ejemplo 2: Pipeline con gates (DISCOVER → REFLECT) ===\n")
    print("Layer 1 (DISCOVER → COMPILE) corre automático.")
    print("Layer 2 (AUDIT, REFLECT) pausa para tu review.\n")

    results = investigate(
        topic=(
            "Estándares de gobernanza para asset managers de deuda privada "
            "en LatAm que necesitan pasar due diligence institucional. "
            "Contexto: Cordada administra fondos rescatables de deuda, "
            "los aportantes del FIP son familias chilenas que controlan "
            "el 85% de la sociedad administradora."
        ),
        gates={"audit", "reflect"},
    )

    print(f"\nAgents ejecutados: {list(results.keys())}")


def ejemplo_pipeline_con_github():
    """Pipeline con GitHub + gates — trazabilidad total."""
    print("\n=== Ejemplo 3: Pipeline GitHub + gates ===\n")
    print("Crea repo en GitHub, corre Layer 1, pausa en gates.")
    print("Si haces 'stop', guarda estado para resume después.\n")

    results = investigate(
        "carta-aportantes-q1-2026",
        topic=(
            "Análisis de opciones para resolver la gobernanza de Cordada. "
            "El directorio actual no pasa filtro de due diligence institucional."
        ),
        description="Carta Q1 2026 — gobernanza y opciones para aportantes",
        gates=DEFAULT_GATES,
    )

    print(f"\nOutputs: {list(results.keys())}")


def ejemplo_resume():
    """Resume un pipeline detenido en un gate."""
    print("\n=== Ejemplo 4: Resume pipeline ===\n")
    print("Retoma desde donde se detuvo, con input adicional del CEO.\n")

    results = investigate(
        "carta-aportantes-q1-2026",
        resume=True,
        gate_input=(
            "Proceder con panel de expertos: "
            "abogado corporativo Ley 20.712 + "
            "experto en persuasión Cialdini + "
            "lógica Minto."
        ),
    )

    print(f"\nOutputs: {list(results.keys())}")


def ejemplo_decide():
    """Usar DECIDE para presentar opciones."""
    print("\n=== Ejemplo 5: DECIDE (opciones con trade-offs) ===\n")

    options = decide("""
    La decisión: Resolver la gobernanza de Cordada antes del due diligence.

    Contexto: El directorio actual tiene 3 miembros, todos vinculados al FIP.
    Los institucionales exigen al menos 2 independientes.

    Stakeholders:
    - Aportantes FIP (85% ownership): quieren mantener control
    - CEO: necesita cerrar deal en 60 días
    - Institucional entrante: exige governance upgrade

    Restricciones: No más de 90 días, presupuesto limitado para directores.

    Criterios (en orden): velocidad > legitimidad > control > costo
    """)

    print(options[:500] + "...\n")


if __name__ == "__main__":
    print("cordada-ceo-agents — Ejemplos de uso programático")
    print("=" * 50)
    print()
    print("1. Agente individual (COMPILE) — 1 línea")
    print("2. Pipeline con gates — pausa en Layer 2")
    print("3. Pipeline GitHub + gates — trazabilidad total")
    print("4. Resume pipeline detenido")
    print("5. DECIDE — opciones con trade-offs")
    print()

    choice = input("¿Cuál quieres correr? (1/2/3/4/5): ").strip()

    examples = {
        "1": ejemplo_agente_individual,
        "2": ejemplo_pipeline_con_gates,
        "3": ejemplo_pipeline_con_github,
        "4": ejemplo_resume,
        "5": ejemplo_decide,
    }

    fn = examples.get(choice)
    if fn:
        fn()
    else:
        print("Opción no válida")
