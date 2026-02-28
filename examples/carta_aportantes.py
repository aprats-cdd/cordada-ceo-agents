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

from orchestrator import agent, investigate, decide


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


def ejemplo_pipeline_local():
    """Pipeline local sin GitHub — todo en memoria."""
    print("\n=== Ejemplo 2: Pipeline local (DISCOVER → COMPILE) ===\n")

    results = investigate(
        topic=(
            "Estándares de gobernanza para asset managers de deuda privada "
            "en LatAm que necesitan pasar due diligence institucional. "
            "Contexto: Cordada administra fondos rescatables de deuda, "
            "los aportantes del FIP son familias chilenas que controlan "
            "el 85% de la sociedad administradora."
        ),
        to_agent="compile",
    )

    # Acceder outputs programáticamente
    print(f"Agents ejecutados: {list(results.keys())}")
    print(f"DISCOVER: {len(results['discover'])} chars")
    print(f"COMPILE: {len(results['compile'])} chars")


def ejemplo_pipeline_con_github():
    """Pipeline completo con repo en GitHub — trazabilidad total."""
    print("\n=== Ejemplo 3: Pipeline con GitHub (full traceability) ===\n")

    results = investigate(
        "carta-aportantes-q1-2026",
        topic=(
            "Análisis de opciones para resolver la gobernanza de Cordada. "
            "El directorio actual no pasa filtro de due diligence institucional. "
            "Necesito un documento que presente las opciones al grupo de aportantes."
        ),
        description="Carta trimestral Q1 2026 — gobernanza y opciones para aportantes",
    )

    # Todo queda en GitHub con audit trail
    print(f"\nOutputs: {list(results.keys())}")


def ejemplo_decide():
    """Usar DECIDE para presentar opciones."""
    print("\n=== Ejemplo 4: DECIDE (opciones con trade-offs) ===\n")

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
    print("2. Pipeline local (DISCOVER → COMPILE) — sin GitHub")
    print("3. Pipeline con GitHub — trazabilidad total")
    print("4. DECIDE — opciones con trade-offs")
    print()

    choice = input("¿Cuál quieres correr? (1/2/3/4): ").strip()

    examples = {
        "1": ejemplo_agente_individual,
        "2": ejemplo_pipeline_local,
        "3": ejemplo_pipeline_con_github,
        "4": ejemplo_decide,
    }

    fn = examples.get(choice)
    if fn:
        fn()
    else:
        print("Opción no válida")
