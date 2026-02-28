"""
Ejemplo: Pipeline completo para carta a aportantes FIP Cordada.

Este script muestra cómo correr agentes individuales o el pipeline
completo para un caso real.

Uso:
    python examples/carta_aportantes.py
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.agent_runner import run_agent
from orchestrator.pipeline import run_pipeline


def ejemplo_agente_individual():
    """Correr solo COMPILE con input directo."""
    print("\n=== Ejemplo 1: Agente individual (COMPILE) ===\n")

    input_text = """
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
    """

    response = run_agent(
        agent_name="compile",
        user_input=input_text,
    )

    print(response[:500] + "...\n")


def ejemplo_pipeline_parcial():
    """Correr pipeline desde DISCOVER hasta COMPILE."""
    print("\n=== Ejemplo 2: Pipeline parcial (DISCOVER → COMPILE) ===\n")

    run_pipeline(
        topic=(
            "Estándares de gobernanza para asset managers de deuda privada "
            "en LatAm que necesitan pasar due diligence institucional. "
            "Contexto: Cordada administra fondos rescatables de deuda, "
            "los aportantes del FIP son familias chilenas que controlan "
            "el 85% de la sociedad administradora."
        ),
        from_agent="discover",
        to_agent="compile",
    )


def ejemplo_pipeline_completo_interactivo():
    """Pipeline completo con modo interactivo en AUDIT y REFLECT."""
    print("\n=== Ejemplo 3: Pipeline completo interactivo ===\n")

    run_pipeline(
        topic=(
            "Análisis de opciones para resolver la gobernanza de Cordada. "
            "El directorio actual no pasa filtro de due diligence institucional. "
            "Necesito un documento que presente las opciones al grupo de aportantes."
        ),
        from_agent="discover",
        to_agent="reflect",
        interactive_at={"audit", "reflect"},
    )


if __name__ == "__main__":
    print("cordada-ceo-agents — Ejemplos de uso")
    print("=" * 40)
    print()
    print("1. Agente individual (COMPILE)")
    print("2. Pipeline parcial (DISCOVER → COMPILE)")
    print("3. Pipeline completo interactivo")
    print()

    choice = input("¿Cuál quieres correr? (1/2/3): ").strip()

    if choice == "1":
        ejemplo_agente_individual()
    elif choice == "2":
        ejemplo_pipeline_parcial()
    elif choice == "3":
        ejemplo_pipeline_completo_interactivo()
    else:
        print("Opción no válida")
