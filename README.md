# Rappi Operations Intelligence

> Sistema conversacional + reporting automático sobre métricas operacionales por zona, para equipos de SP&A y Operations.

Permite a usuarios no técnicos:
- **Hacer preguntas en lenguaje natural** sobre 14 métricas operacionales en 9 países y 1,092 zonas (chat).
- **Recibir insights accionables** automáticamente cada semana (reporte ejecutivo).

Todos los números que se presentan vienen de `pandas` sobre los CSVs reales. El LLM (Gemini 2.5 Flash-Lite) se encarga sólo de entender intención y redactar respuestas — nunca calcula ni estima valores.

---

## Demo rápido

![Screenshot pendiente]
*(Opcional: agrega una captura del UI aquí)*

Preguntas de ejemplo que el sistema responde correctamente:

- *"¿Cuáles son las 5 zonas con mayor Lead Penetration esta semana?"*
- *"Compara el Perfect Orders entre zonas Wealthy y Non Wealthy en México en las últimas 5 semanas."*
- *"Muéstrame la evolución de Gross Profit UE en Chapinero."*
- *"¿Qué zonas tienen alto Lead Penetration pero bajo Perfect Orders?"*
- *"¿Qué zonas crecen más en órdenes y qué podría explicarlo?"*

---

## Arquitectura

```
┌─────────────────────────────────────────────┐
│  Streamlit UI (chat tab + report tab)       │
└────────────────┬────────────────────────────┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
┌──────────────┐  ┌──────────────┐
│  ChatAgent   │  │  Insights    │
│  (Gemini +   │  │  Engine      │
│  tool calls) │  │  (pure Py)   │
└──────┬───────┘  └──────┬───────┘
       │                 │
       └────────┬────────┘
                ▼
┌─────────────────────────────────────────────┐
│  Analytical core (pure Python)              │
│    primitives.py   — 6 deterministic funcs  │
│    detectors.py    — 5 anomaly detectors    │
└────────────────┬────────────────────────────┘
                 ▼
┌─────────────────────────────────────────────┐
│  Data layer                                 │
│    data_loader.py       — normalize + val.  │
│    metric_dictionary.py — business semantic │
└─────────────────────────────────────────────┘
```

### Principios de diseño

1. **Números del código, palabras del LLM.** Toda operación numérica ocurre en pandas con funciones deterministas. El LLM sólo interpreta intención del usuario y genera prosa. Esto elimina alucinaciones numéricas por construcción.
2. **Tool calling con schemas estrictos.** El LLM no tiene acceso a la data cruda — sólo puede llamar a 7 herramientas con parámetros tipados (metrics, countries, etc. son enums). Imposible inventar nombres de zona o métrica.
3. **Semántica de negocio centralizada.** El `metric_dictionary.py` codifica dirección (higher/lower is better), unidad, estrategia de agregación y aliases para cada métrica. Es la única fuente de verdad sobre qué significa cada número.
4. **Separación online vs offline.** El chat es online (scope desconocido, requiere tool calling) y el reporte es offline (scope fijo, un sólo LLM call al final). Esto reduce costo del reporte en 10–20× vs si lo orquestara el LLM.

---

## Stack

| Capa | Tecnología | Por qué |
|---|---|---|
| LLM | Gemini 2.5 Flash-Lite | Tier gratuito genuino (1000 RPD), tool calling confiable, 10× más barato que GPT-4 o Claude Sonnet |
| Análisis | pandas + numpy | Determinismo numérico en cada operación |
| UI | Streamlit | Velocidad de desarrollo para demo; no requiere frontend separado |
| SDK | `google-genai` oficial | SDK directo — sin frameworks intermedios (ver "Trade-offs") |

**No usé LangChain / LlamaIndex / CrewAI** porque el problema no los necesita: no hay RAG, no hay multi-agent, la memoria conversacional es trivial. Una arquitectura en capas bien separadas me da portabilidad de LLM (cambiar a OpenAI o Claude sería ~40 líneas en `chat_agent.py`) sin los costos de abstracción de un framework. Ver sección "Trade-offs" abajo.

---

## Setup y ejecución

### Requisitos

- Python 3.10+
- API key de Gemini (tier gratuito funciona): [obtener aquí](https://aistudio.google.com/apikey)

### Instalación

```bash
git clone <repo-url>
cd rappi-insights

python -m venv .venv
.venv\Scripts\Activate.ps1    # Windows
source .venv/bin/activate      # macOS/Linux

pip install -r requirements.txt
```

### Configuración

Crea `.env` en la raíz del proyecto:

```
GEMINI_API_KEY=tu_api_key_aqui
```

Coloca los CSVs en `data/`:

```
data/
  metrics.csv
  orders.csv
```

### Ejecución

**UI web (demo principal):**
```bash
streamlit run ui/app.py
```
Abre http://localhost:8501

**CLI del chat (debugging):**
```bash
python -m scripts.chat_cli
```

**Generar reporte ejecutivo sin UI:**
```bash
python -m scripts.generate_report
# → reports/executive_report_<timestamp>.md
```

**Correr tests:**
```bash
pytest analytics/tests/ -v
```

---

## Estructura del proyecto

```
rappi-insights/
├── core/
│   ├── data_loader.py          # CSV → long format + validación semántica
│   └── metric_dictionary.py    # Diccionario de las 14 métricas: dirección, unidad, aliases
├── analytics/
│   ├── primitives.py           # 6 funciones deterministas (top_n, trend, compare, etc.)
│   ├── detectors.py            # 5 detectores automáticos de anomalías, tendencias, etc.
│   └── tests/                  # 14 unit tests
├── agent/
│   ├── tools.py                # Schemas tool-calling que Gemini consume
│   ├── system_prompt.py        # Constitución del agente en español
│   └── chat_agent.py           # Loop conversacional con memoria
├── insights/
│   ├── engine.py               # Ranking de findings por severidad de negocio
│   └── report_generator.py     # Generación del reporte markdown
├── ui/
│   └── app.py                  # Streamlit — dos tabs (Chat + Report)
├── scripts/                    # CLI tools
│   ├── chat_cli.py
│   ├── generate_report.py
│   ├── preview_detectors.py
│   └── test_gemini_connection.py
├── reports/                    # Reportes generados (gitignored)
├── data/                       # CSVs (no commiteados)
├── KNOWN_ISSUES.md
├── requirements.txt
└── README.md
```

---

## Costo estimado

**Desarrollo + demo de este proyecto: ~$0 USD** usando el tier gratuito de Gemini.

Escalando a producción (tier pago):

| Operación | Costo por ejecución | Comentario |
|---|---|---|
| 1 pregunta del chat | ~$0.0002 USD | Gemini Flash-Lite, 2 API calls por pregunta |
| 1 reporte ejecutivo semanal | ~$0.001 USD | 1 API call único con findings pre-curados |
| 10 preguntas por sesión | ~$0.002 USD | |
| Uso interno SP&A (50 personas × 20 preguntas/día × 22 días) | ~$4 USD/mes | Todo el equipo completo |
| Reporte semanal automatizado (1 por semana × 52) | ~$0.05 USD/año | Negligible |

**Elección del modelo:** Gemini Flash-Lite sobre Claude Sonnet / GPT-4 porque la calidad de tool calling era suficiente para este caso de uso (validado con ~20 preguntas en el golden set), a 10–30× menor costo. Para casos que requieran razonamiento complejo (ej: análisis estratégico narrativo profundo), migraría a Sonnet solo en la capa de report narrative.

---

## Trade-offs y decisiones

### Por qué tool calling con primitivas, no text-to-pandas

Consideré 3 alternativas:

1. **Text-to-pandas:** LLM genera código, lo ejecutamos en sandbox. Máxima flexibilidad, pero alucina nombres de columnas, requiere sandbox seguro, impredecible. Para 14 métricas con schema fijo, la flexibilidad no agrega valor.
2. **Toda la data en contexto del LLM:** 500k+ tokens por query. Lento, caro, sigue alucinando números. No escala.
3. **Tool calling con primitivas tipadas (escogido):** Determinismo numérico + flexibilidad lingüística. El LLM elige qué herramienta usar; las herramientas hacen el cómputo.

### Por qué NO LangChain

- No hay RAG (no corpus no estructurado) → LlamaIndex innecesario.
- No hay multi-agent (una sola interacción bien definida) → CrewAI innecesario.
- Memoria conversacional = lista en session state de Streamlit. 10 líneas.
- Schemas de herramientas = diccionario Python. El SDK de Gemini los consume directo.
- En un demo en vivo de 30 minutos, una stack trace dentro de `langchain_core/...` es inaceptable.
- Cambiar de Gemini a OpenAI/Claude serían ~40 líneas en `chat_agent.py`. El aislamiento lo da la arquitectura en capas, no el framework.

### Por qué Streamlit

Velocidad de desarrollo. FastAPI + React sería 10× más código sin agregar valor al demo. Si el producto llegara a producción, migraría el frontend a React y mantendría el backend Python.

### Por qué un diccionario de métricas dedicado

La única alternativa era que el LLM infiriera la semántica de cada métrica (dirección, unidad, agregación) a partir de su nombre. Esto fallaría en casos como `Restaurants Markdowns / GMV`, donde un valor alto es malo — el LLM tendería a tratarlo como "mayor es mejor" por default, produciendo respuestas confidentes pero incorrectas en preguntas tipo "top zonas problemáticas por markdowns." El diccionario elimina esta clase de bug.

---

## Calidad de datos: hallazgos durante desarrollo

El loader detectó y filtró valores fuera del rango semántico válido:

- **Lead Penetration** (definida como ratio ∈ [0,1]): 253 filas con valores hasta 393.9, principalmente en Ecuador y menores en BR, PE, CO, MX.
- **Hipótesis:** Artefacto del proceso de aleatorización documentado en la nota final del PDF ("datos anonimizados y randomizados").
- **Manejo:** El `metric_dictionary` declara `min_value`/`max_value` por métrica; el loader filtra y loguea violaciones con detalle.

Ver `KNOWN_ISSUES.md` para más detalles.

---

## Limitaciones conocidas

1. **Rate limits del tier gratuito.** 1,000 RPD. Suficiente para desarrollo y demo; en producción migraría a Tier 1 o Vertex AI.
2. **Memoria conversacional simple.** Mantengo toda la historia por sesión. Sesiones muy largas (50+ turnos) consumirían el context window. Próximo paso: sliding window con compresión semántica.
3. **Sin persistencia.** Las conversaciones se pierden al reiniciar. En producción agregaría SQLite o Postgres para session state.
4. **Chart generation no implementado.** Cuando el usuario pide "gráfica," el bot responde en texto. Próximo paso: agregar herramienta `create_chart` con Plotly.
5. **Sin evals formales.** Validé manualmente ~20 preguntas. En producción necesitaría: golden set de 100+ preguntas, métricas de tool-selection accuracy, regression tests en CI.
6. **Tier gratuito envía prompts a Google para training.** Para data real de Rappi, migrar a tier pago o Vertex AI es obligatorio por privacidad.

---

## Próximos pasos (si tuviera más tiempo)

### Corto plazo (1–2 días)
- **Clickable findings en el reporte** → auto-populan preguntas en el chat. Reduce fricción de investigación.
- **Plotly charts en chat** cuando la pregunta lo amerite (trends → line, comparaciones → bar).
- **Exportación a CSV/PDF** para findings y respuestas.
- **Envío automático del reporte semanal por email** (SMTP o SendGrid).

### Mediano plazo (1–2 semanas)
- **Golden question set + evals automáticos.** 100 preguntas con respuestas esperadas, accuracy trackeada en CI.
- **Sliding window + compression** para conversaciones largas.
- **Persistencia en Postgres** de sesiones y reportes históricos.
- **Deployment** a Streamlit Cloud o contenedor en GCP.

### Largo plazo (1+ mes)
- **Fine-tuning de Gemini o Claude** en preguntas específicas del dominio Rappi para mejorar tool-selection accuracy.
- **Sistema de RAG ligero** sobre documentos internos (playbooks, procedimientos operacionales) para enriquecer recomendaciones.
- **Dashboard ejecutivo en tiempo real** (no sólo reporte semanal): KPIs live, drill-down, alertas.
- **Multi-agent:** un agente investigador (chat), un agente narrador (reportes), un agente de alertas (Slack/email cuando aparezcan anomalías críticas).

---
