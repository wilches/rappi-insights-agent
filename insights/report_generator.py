"""
Report generator: turn curated findings into a narrative markdown report.

The LLM here is NOT computing anything — it's translating structured findings
into readable Spanish prose with business context and recommendations. All
numbers in the final report come from the findings dict verbatim.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types as gtypes

load_dotenv()

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash-lite"


NARRATIVE_SYSTEM_PROMPT = """Eres un analista senior de operaciones de Rappi. Te dan una lista estructurada de hallazgos (findings) ya jerarquizados por severidad de negocio, y tu trabajo es redactar un reporte ejecutivo en español claro y accionable.

# Reglas

1. **No inventes números.** Todos los valores deben venir de los findings. Si un finding no trae un número, no lo menciones.

2. **No inventes zonas, ciudades, países ni métricas.** Usa exactamente los nombres que vienen en los findings.

3. **Añade contexto de negocio donde aporte valor.** Ejemplos: 'Gross Profit UE negativo significa que la zona pierde dinero por orden — puede deberse a subsidios agresivos, pagos de surge a repartidores, o expansión temprana'. 'Una caída de 3 semanas consecutivas en Perfect Orders sugiere un problema operacional estructural, no ruido'.

4. **Para cada finding importante, da una recomendación accionable.** No escribas "se debería investigar" — escribe "Operations debería investigar la zona X dado que...". Cada recomendación debe tener un owner implícito (Pricing, Operations, Strategy) y una acción concreta.

5. **Prioriza brevedad.** El PDF del caso dice 'prioriza relevancia sobre complejidad. 5 insights bien fundamentados valen más que 20 insights superficiales'. Respétalo.

6. **Usa markdown limpio.** Headers `##`, subheaders `###`, bullets cuando aplique. No uses tablas a menos que mejoren claridad.

7. **Formato numérico.** Usa los `value_formatted` cuando vengan (ya tienen % o $). No re-formatees números.
"""


def _summarize_findings_for_llm(selected: dict[str, list[dict]]) -> str:
    """
    Produce a compact JSON representation of the findings for the LLM.
    We drop noisy keys and keep only what's useful for narrative.
    """
    compact = {}
    for category, findings in selected.items():
        compact[category] = []
        for f in findings:
            trimmed = {k: v for k, v in f.items() if k not in ("severity", "business_severity")}
            compact[category].append(trimmed)
    return json.dumps(compact, indent=2, ensure_ascii=False, default=str)


def _build_report_prompt(selected: dict[str, list[dict]]) -> str:
    """Assemble the user message for the LLM with the findings + instructions."""
    findings_json = _summarize_findings_for_llm(selected)
    today_iso = datetime.now().strftime("%Y-%m-%d")

    return f"""A continuación tienes los hallazgos curados de la última semana operacional de Rappi, jerarquizados por severidad de negocio.


FECHA DE HOY: {today_iso}

Usa esta fecha exacta en el header del reporte — no la inventes.
Redacta un REPORTE EJECUTIVO en markdown con la siguiente estructura exacta:

# Reporte Ejecutivo de Operaciones — [fecha de hoy]

## Resumen ejecutivo
(3-5 hallazgos críticos en bullets, cada uno con una frase de impacto. Usa los findings de mayor severidad cruzando categorías — los más importantes del negocio.)

## Hallazgos por categoría

### Anomalías (cambios semana a semana >10%)
(Top 3-5 de la categoría 'anomalies'. Para cada uno: qué pasó, impacto de negocio, recomendación accionable.)

### Tendencias preocupantes (3+ semanas de deterioro)
(Top 3-5 de 'deteriorating_trends'. Mismo formato.)

### Benchmarking (zonas divergentes de sus pares)
(Top 3-5 de 'peer_divergence'. Mismo formato.)

### Correlaciones notables
(Top 2-3 de 'correlations'. Interpretación de negocio, no solo 'r=0.85'.)

### Oportunidades
(Top 3-5 de 'opportunities'. Zonas que son candidatas para expansión, best-practice extraction, o case studies.)

## Recomendaciones priorizadas
(3-5 acciones concretas para la próxima semana, cada una con owner sugerido: Pricing, Operations, Strategy, o Expansion.)

---

FINDINGS CURADOS (JSON):
```json
{findings_json}
```

Recuerda: todos los números deben venir de los findings. No inventes zonas, métricas ni valores. Usa los `value_formatted` cuando vengan.
"""


def generate_markdown_report(
    selected_findings: dict[str, list[dict]],
    client: genai.Client | None = None,
) -> str:
    """
    Main entry point. Takes curated findings, asks the LLM to write the
    report, returns a markdown string.
    """
    if client is None:
        api_key = None
        try:
            import streamlit as st
            api_key = st.secrets.get("GEMINI_API_KEY, None")
        except (ImportError, FileNotFoundError, Exception):
            pass
        if not api_key:
            api_key = os.environ.get("GEMINI_API_KEY")

    prompt = _build_report_prompt(selected_findings)

    logger.info("Generating report narrative via LLM...")
    response = client.models.generate_content(
        model=MODEL,
        contents=[gtypes.Content(role="user", parts=[gtypes.Part(text=prompt)])],
        config=gtypes.GenerateContentConfig(
            system_instruction=NARRATIVE_SYSTEM_PROMPT,
            temperature=0.3,
        ),
    )

    if not response.candidates:
        raise RuntimeError("LLM returned no candidates for report generation.")

    text_parts = [
        p.text for p in (response.candidates[0].content.parts or []) if p.text
    ]
    report_md = "\n".join(text_parts).strip()

    if not report_md:
        raise RuntimeError("LLM returned an empty report.")

    return report_md


def save_report(
    report_md: str,
    output_dir: str = "reports",
) -> str:
    """Save the report to disk with a timestamped filename. Returns the path."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"executive_report_{timestamp}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report_md)
    logger.info(f"Report saved to: {path}")
    return path
