# 📊 Rappi Operations Intelligence

> **Análisis conversacional de datos + reportes ejecutivos automáticos para los equipos de SP&A y Operations de Rappi.**
> Construido como caso técnico. ~30 horas de trabajo enfocado, en solitario.

## 🔗 Puedes ver el funcionamiento aquí -> [Demo en vivo](https://rappi-insights-agent-t2ynoxnchn5vevvxtykaea.streamlit.app/)



---

## 🎯 El problema

Rappi opera en 9 países con más de 1,000 zonas. Los equipos de Strategy, Planning & Analytics (SP&A) y Operations necesitan acceso constante a los datos para tomar decisiones, pero:

- **Acceder a insights requiere SQL/Python** — los usuarios no técnicos quedan bloqueados.
- **El análisis manual semanal consume horas** — alguien tiene que cazar anomalías, tendencias y zonas con bajo desempeño.

Este sistema resuelve ambos problemas. Usuarios no técnicos hacen preguntas en español o inglés y reciben respuestas confiables. Un reporte ejecutivo semanal se genera automáticamente con hallazgos rankeados y accionables.

---

## ⚡ Pruébalo en 30 segundos

1. Abre [el demo en vivo](https://TU-APP.streamlit.app)
2. Haz clic en cualquier pregunta de ejemplo en la barra lateral — o escribe la tuya
3. Cambia a la pestaña **Reporte Ejecutivo** → haz clic en **Generate report**

O prueba estas:

```
¿Cuáles son las 5 zonas problemáticas por Gross Profit UE en México?
Compara el Perfect Orders entre zonas Wealthy y Non Wealthy en las últimas 4 semanas.
¿Qué zonas crecen más en órdenes y qué podría explicarlo?
```

---

## 🧠 La apuesta arquitectónica central

Los LLMs son excelentes con el lenguaje pero poco confiables con números. Entonces:

> **Los números vienen de pandas. Las palabras vienen del LLM. Nunca al revés.**

El LLM nunca calcula valores. Elige una herramienta, pasa argumentos, recibe un resultado determinista de pandas, y escribe prosa fundamentada en ese resultado. Esto elimina la alucinación numérica por construcción.

```
┌──────────────────┐
│ Usuario: "top 5  │
│ zonas por X"     │
└────────┬─────────┘
         ▼
┌──────────────────┐      ┌──────────────────┐
│ Gemini elige una │◀────▶│ Schemas de tools │
│ herramienta      │      │ estrictos (enums)│
└────────┬─────────┘      └──────────────────┘
         ▼
┌──────────────────┐
│ pandas computa   │  ← determinista, testeable
│ la respuesta     │    14 unit tests, 0 flaky
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Gemini compone   │  ← solo traduce a prosa
│ respuesta en ESP │    no puede alucinar números
└──────────────────┘
```

---

## 🏗️ Arquitectura

### Stack de cuatro capas, con dependencias estrictas en una sola dirección

| Capa | Responsabilidad | Tecnología |
|---|---|---|
| **UI** | Pestañas de chat + reporte, transparencia de tool calls | Streamlit |
| **Orquestación** | Tool calling del LLM (chat) • ranking de findings (reporte) | SDK `google-genai` |
| **Núcleo analítico** | 6 primitivas + 5 detectores, todo Python puro | pandas, numpy |
| **Datos** | CSV → formato largo normalizado + validación semántica | pandas |

### Dos flujos, un mismo cerebro analítico

```
               ┌──────────────────┐
               │  Núcleo          │
               │  Analítico       │
               │  (compartido)    │
               └────────┬─────────┘
                        │
            ┌───────────┴───────────┐
            ▼                       ▼
     ┌──────────────┐       ┌──────────────┐
     │  Chat Agent  │       │   Reporte    │
     │   (online)   │       │   (offline)  │
     │ 2 LLM calls  │       │ 1 LLM call   │
     │  por turno   │       │  por reporte │
     └──────────────┘       └──────────────┘
```

**¿Por qué dos patrones?** El chat es *online* — scope desconocido, requiere tool-calling. El reporte es *offline* — scope fijo, pre-computo todo y luego le pido al LLM que narre. Reduce el costo del reporte 10–20× vs orquestarlo como un chat multi-turno.

### Diccionario de métricas — la capa de semántica de negocio

Un diccionario Python que codifica, para cada una de las 14 métricas:
- **Dirección** — ¿mayor es mejor, o menor?
- **Unidad** — ratio, moneda, conteo (determina el formato)
- **Agregación** — mean, sum, o weighted mean por órdenes (zonas pequeñas no deben distorsionar promedios a nivel país)
- **Rango válido** — usado para validación de calidad de datos al cargar
- **Aliases** — formas comunes en que los usuarios se refieren a la métrica

Sin esto, preguntar *"top 5 zonas problemáticas por markdowns"* retornaría las *mejores* zonas en lugar de las *peores*, porque `Restaurants Markdowns / GMV` es lower-is-better. El diccionario hace que las consultas conscientes de la dirección sean triviales.

---

## 📁 Qué hay en el repo

```
rappi-insights/
├── core/               # data loader + semántica de métricas
├── analytics/          # 6 primitivas + 5 detectores + 14 tests
├── agent/              # chat agent + schemas de tools + system prompt
├── insights/           # motor de ranking + generador de reporte
├── ui/                 # Streamlit app (dos tabs)
├── scripts/            # entry points CLI para cada subsistema
├── data/               # CSVs anonimizados (del brief del caso)
└── README.md
```

Archivos clave para leer primero:
- `core/metric_dictionary.py` — semántica de negocio
- `analytics/primitives.py` — las 6 funciones deterministas
- `agent/chat_agent.py` — el loop de tool-calling
- `insights/report_generator.py` — generador offline de narrativa

---

## 🚀 Ejecutar localmente

```bash
git clone https://github.com/TU_USER/rappi-insights
cd rappi-insights

python -m venv .venv
.venv\Scripts\Activate.ps1    # Windows PowerShell
# o: source .venv/bin/activate   (macOS/Linux)

pip install -r requirements.txt

# Obtén una API key gratuita de Gemini en https://aistudio.google.com/apikey
echo "GEMINI_API_KEY=tu_key" > .env

streamlit run ui/app.py
```

**Alternativas CLI:**
```bash
python -m scripts.chat_cli          # chat en terminal
python -m scripts.generate_report   # generación standalone del reporte
pytest analytics/tests/ -v          # correr los 14 unit tests
```

---

## 💰 Costo

**Desarrollo + demo: $0 USD.** Tier gratuito de Gemini Flash-Lite (1,000 RPD).

**Proyección en producción (pricing Tier 1):**

| Operación | Costo | Notas |
|---|---|---|
| 1 pregunta del chat | ~$0.0002 | 2 API calls por turno |
| 1 reporte semanal | ~$0.001 | 1 API call total |
| 50 personas × 20 consultas/día × 22 días | ~$4/mes | Todo el equipo de SP&A |

Elección del modelo: **Gemini Flash-Lite** sobre Claude Sonnet / GPT-4 porque la precisión de tool-calling era suficiente a 10–30× menor costo. Si la narrativa compleja se vuelve un requisito, el generador de reportes sería fácil de intercambiar a Sonnet manteniendo el chat en Flash-Lite.

---

## 🎛️ Decisiones de diseño (las interesantes)

### Tool-calling con primitivas, no text-to-pandas

Consideré tres opciones:
- **Text-to-pandas:** flexible pero alucina nombres de columnas; requiere sandbox seguro; impredecible.
- **Toda la data en contexto del LLM:** 500k+ tokens por consulta; lento, caro, *sigue alucinando números*.
- **Tool calling con primitivas tipadas** ← elegido. Determinismo numérico + flexibilidad lingüística.

### Sin LangChain / LlamaIndex / CrewAI

- No hay RAG → LlamaIndex innecesario.
- No hay multi-agent → CrewAI innecesario.
- La memoria es una lista en session state → 10 líneas, no un framework.
- Durante un demo en vivo de 30 minutos, un stack trace dentro de `langchain_core/` es inaceptable.

La separación en capas da portabilidad (cambiar de provider LLM son ~40 líneas en `chat_agent.py`) sin el overhead del framework.

### Streamlit sobre FastAPI + React

Velocidad de desarrollo. Si esto fuera a producción, mantendría el backend Python y migraría el frontend a React — pero para un build de 2 días, Streamlit cambia 10× menos código por un resultado suficientemente pulido.

---

## 🧪 Hallazgos de calidad de datos durante desarrollo

El loader detectó 253 filas con valores fuera de rango para `Lead Penetration` — un ratio definido en [0, 1], pero observado hasta 393.9 en zonas de EC/BR/PE/CO/MX. Probablemente un artefacto del proceso de anonimización mencionado en el brief. El `metric_dictionary` declara rangos válidos por métrica; el loader filtra y loguea violaciones.

En un deployment real, esto dispararía una alerta al equipo de Data Engineering. Ver [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md).

---

## ⚠️ Limitaciones conocidas

1. **Rate limits del tier gratuito** (1,000 RPD). Suficiente para demo; en producción migraría a Tier 1 o Vertex AI.
2. **Conversaciones en memoria.** Sin persistencia entre sesiones — necesitaría SQLite/Postgres.
3. **Sin evals formales aún.** Validé manualmente contra ~20 preguntas. Producción necesitaría un golden set de 100+ con accuracy trackeada en CI.
4. **Retención de datos del tier gratuito.** Google puede usar prompts para entrenamiento. Data real de Rappi requeriría tier pagado o Vertex AI.

---

## 🔮 Próximos pasos (con más tiempo)

**Quick wins (~1 día):**
- Findings clickables en el reporte que auto-pueblen preguntas en el chat.
- Gráficos Plotly cuando la pregunta lo amerite (tendencias → line, comparaciones → bar).
- Exportación a CSV/PDF.

**Mediano plazo (~1 semana):**
- Golden question set + evaluación automatizada con métricas de tool-selection accuracy.
- Sliding-window para conversaciones largas.
- Reporte semanal programado con delivery por email.

**Largo plazo:**
- Alertas en tiempo real a Slack para findings críticos.
- Fine-tuning o optimización de prompts para terminología específica de Rappi.
- Split multi-agent: roles separados de investigador, narrador y alertas.

---


*Construido para el caso técnico de AI Engineer en Rappi. Feliz de caminar cualquier decisión de diseño o trade-off en detalle.*
