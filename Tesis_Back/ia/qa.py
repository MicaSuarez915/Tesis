SYS = (
    "Sos un asistente experto en derecho laboral argentino. Analizás jurisprudencia y normativa con precisión profesional."
    "Responde en español claro y preciso. "
    "Usa **citas** con los IDs entre [] exactamente como aparecen en el contexto. "
    "No inventes jurisprudencia ni citas. Si falta contexto, dilo."
)

def build_prompt(user_query: str, hits: list, causa_context: str = "", max_chars_ctx: int = 12000) -> list:
    """
    Construye el prompt optimizado para el asistente jurídico experto.
    Maneja jurisprudencia local, búsqueda web y contexto de causa específica.
    """
    ctx_parts = []
    used = 0
    
    # Si hay contexto de causa, agregarlo primero
    if causa_context:
        ctx_parts.append("=== CONTEXTO DE LA CAUSA EN ANÁLISIS ===")
        ctx_parts.append(causa_context)
        ctx_parts.append("")
        used += len(causa_context)
    
    # Clasificar y contar fuentes
    local_hits = []
    web_hits = []
    causa_docs = []
    
    for h in hits:
        doc_id = h.get('doc_id', '')
        if 'causa_doc::' in doc_id:
            causa_docs.append(h)
        elif h.get('source') == 'tavily' or 'tavily' in doc_id.lower():
            web_hits.append(h)
        else:
            local_hits.append(h)
    
    # Documentos de la causa (máxima prioridad después del contexto)
    if causa_docs:
        ctx_parts.append("=== DOCUMENTOS DE LA CAUSA ===")
        for idx, h in enumerate(causa_docs, 1):
            header = f"\n[Doc Causa {idx}] {h['titulo']}"
            if h.get('fecha'):
                header += f" — {h['fecha']}"
            block = f"{header}\n{h['text'].strip()}\n"
            if used + len(block) > max_chars_ctx:
                continue
            ctx_parts.append(block)
            used += len(block)
        ctx_parts.append("")
    
    # Construir contexto con fuentes locales
    base_idx = len(causa_docs)
    if local_hits:
        ctx_parts.append("=== JURISPRUDENCIA Y DOCTRINA ARGENTINA ===")
        for idx, h in enumerate(local_hits, base_idx + 1):
            tribunal = h.get('tribunal', '')
            fecha = h.get('fecha', 's/f')
            header = f"\n[Fuente {idx}] {h['titulo']}"
            if tribunal:
                header += f" — {tribunal}"
            if fecha != 's/f':
                header += f" — {fecha}"
            
            block = f"{header}\n{h['text'].strip()}\n"
            if used + len(block) > max_chars_ctx:
                continue
            ctx_parts.append(block)
            used += len(block)
    
    # Agregar fuentes web si existen
    base_idx = base_idx + len(local_hits)
    if web_hits:
        ctx_parts.append("\n=== FUENTES COMPLEMENTARIAS ===")
        for idx, h in enumerate(web_hits, base_idx + 1):
            header = f"\n[Fuente {idx}] {h.get('titulo', 'Fuente web')}"
            block = f"{header}\n{h['text'].strip()}\n"
            if used + len(block) > max_chars_ctx:
                continue
            ctx_parts.append(block)
            used += len(block)
    
    context = "\n".join(ctx_parts) if ctx_parts else ""
    
    # Metadata sobre las fuentes
    total_docs = len(causa_docs)
    total_juris = len(local_hits)
    total_web = len(web_hits)
    
    metadata = "\n[Análisis:"
    if causa_context:
        metadata += " Contexto de causa disponible"
    if total_docs:
        metadata += f" | {total_docs} documento(s) de la causa"
    if total_juris:
        metadata += f" | {total_juris} fuente(s) jurídicas"
    if total_web:
        metadata += f" | {total_web} fuente(s) web"
    metadata += "]"
    
    # Sistema de nivel experto (mismo que antes)
    system_prompt = """Sos un abogado laboralista senior especializado en la Provincia de Buenos Aires, con 15+ años de experiencia en litigio y análisis jurisprudencial.

TU ROL:
Asistís a abogados junior proporcionando análisis jurídico fundamentado, identificando precedentes relevantes y sugiriendo estrategias argumentativas basadas en jurisprudencia consolidada.

CUANDO HAY CONTEXTO DE CAUSA:
- Priorizá la información específica de la causa en tu análisis
- Conectá los precedentes jurisprudenciales con los hechos de la causa
- Identifica similitudes y diferencias entre la causa y los precedentes
- Propone estrategias argumentativas específicas para esta causa
- Señalá fortalezas y debilidades del caso basándote en jurisprudencia

METODOLOGÍA DE ANÁLISIS:

1. IDENTIFICACIÓN DE RATIO DECIDENDI
   - Extraé el principio jurídico subyacente de cada fallo
   - Distinguí entre ratio decidendi (vinculante) y obiter dicta (orientador)
   - Identificá si hay líneas jurisprudenciales consolidadas o contradictorias

2. TÉCNICAS DE INTERPRETACIÓN
   - Analogía: aplica precedentes de casos similares
   - A contrario: distingue casos cuando los hechos son sustancialmente diferentes
   - A fortiori: si se aplica en caso menor, con mayor razón en caso mayor
   - Interpretación teleológica: considera el propósito de la norma/precedente

3. JERARQUÍA DE FUENTES
   - Prioridad: CSJN > SCBA > Cámaras Nacionales > Cámaras Provinciales > Primera Instancia
   - Plenarios: tienen mayor peso que fallos aislados
   - Doctrina: complementa pero no sustituye jurisprudencia
   - Documentos de la causa: máxima prioridad para análisis específico
   - Fuentes web: solo como contexto adicional, nunca como autoridad primaria

4. CONTEXTUALIZACIÓN TEMPORAL
   - Considerá la vigencia de la normativa al momento del fallo
   - Advertí si la jurisprudencia es anterior a reformas legales relevantes
   - Priorizá precedentes recientes cuando hay evolución jurisprudencial

REGLAS ESTRICTAS:

 SIEMPRE:
- Cita las fuentes como [Fuente X] o [Doc Causa X] integradas naturalmente
- Fundamentá cada afirmación en las fuentes proporcionadas
- Cuando hay contexto de causa, relacioná la jurisprudencia con los hechos específicos
- Sé transparente sobre limitaciones
- Identifica patrones cuando hay múltiples fallos en la misma línea
- Proporciona valor incluso con fuentes tangenciales o limitadas

 NUNCA:
- Incluyas URLs, links o direcciones web en tu respuesta
- Uses listas numeradas, bullet points o encabezados tipo "1)", "2)"
- Incluyas secciones "TL;DR", "Citas", "Referencias", "Fuentes"
- Inventes precedentes o normativa no mencionada en las fuentes
- Declares "no hay contexto suficiente" si tenés al menos 1-2 fuentes relevantes

CALIBRACIÓN DE CONFIANZA:

ALTA (cuando hay):
- Múltiples fallos concordantes
- Plenarios o fallos de CSJN
- Doctrina mayoritaria clara
→ Usá: "La jurisprudencia consolidada establece...", "Es criterio uniforme..."

MEDIA (cuando hay):
- Algunos fallos pero no línea consolidada
- Jurisprudencia de instancias inferiores
- Doctrina dividida
→ Usá: "La jurisprudencia disponible sugiere...", "Algunos tribunales han sostenido..."

BAJA (cuando hay):
- Solo fuentes tangenciales
- Un único precedente
- Información solo de fuentes web
→ Usá: "Desde una perspectiva similar, se ha resuelto...", "Por analogía, podría argumentarse..."

MANEJO DE CONSULTAS EXPLORATORIAS:

Cuando te pregunten "necesito jurisprudencia sobre X" o "qué hay sobre Y":
1. Resume brevemente qué fuentes encontraste y su relevancia
2. Identificá los ejes temáticos principales
3. Destacá precedentes clave o líneas jurisprudenciales
4. Si hay contexto de causa, conectá los precedentes con el caso específico
5. Sugiere ángulos de análisis o argumentos potenciales
6. Señala vacíos o áreas que requerirían búsqueda adicional"""

    # Prompt del usuario optimizado (ajustado para incluir causa)
    user_prompt = f"""CONSULTA:
{user_query}

MATERIAL DISPONIBLE:
{context}{metadata}

PROCESO DE ANÁLISIS:

PASO 1 - COMPRENSIÓN
Identificá si la consulta es:
a) Específica sobre esta causa (si hay contexto de causa)
b) Búsqueda de precedentes aplicables a esta causa
c) Exploratoria general sobre un tema
d) Estratégica (busca argumentos para sostener posición)

PASO 2 - EVALUACIÓN DE FUENTES
- ¿Hay contexto de causa? Si sí, priorizá conectar jurisprudencia con los hechos específicos
- ¿Cuántas fuentes son directamente relevantes vs tangenciales?
- ¿Qué jerarquía tienen? (CSJN, Cámaras, primera instancia)
- ¿Son recientes o hay que contextualizar temporalmente?
- ¿Hay línea jurisprudencial clara o precedentes contradictorios?

PASO 3 - CONSTRUCCIÓN DE RESPUESTA
Estructura tu análisis en **párrafos fluidos** (NO listas) siguiendo este esquema mental:

- APERTURA: Respuesta directa y sintética a la consulta
- CONTEXTO DE CAUSA (si aplica): Breve síntesis de elementos relevantes del caso
- DESARROLLO: Análisis de precedentes citando [Fuente X], identificando ratio decidendi y patrones
- APLICACIÓN (si hay causa): Cómo se aplican estos precedentes al caso específico
- CONSIDERACIONES: Evolución jurisprudencial, distinciones importantes, fortalezas/debilidades
- CIERRE: Síntesis práctica, argumentos clave o recomendaciones

PASO 4 - CONTROL DE CALIDAD
Antes de responder, verificá:
☑ ¿Cada afirmación está respaldada por al menos una fuente?
☑ ¿Las citas [Fuente X] o [Doc Causa X] están integradas naturalmente?
☑ ¿Si hay contexto de causa, conecté la jurisprudencia con los hechos?
☑ ¿NO incluí ninguna URL en el texto?
☑ ¿El tono es profesional pero accesible?
☑ ¿Aportás valor real aunque las fuentes sean limitadas?

EJEMPLOS DE BUENA REDACCIÓN:

 EXCELENTE (con contexto de causa):
"Considerando que la causa involucra un despido durante licencia médica, resulta aplicable el criterio de la Cámara Nacional del Trabajo, Sala VII, que ha establecido que el despido durante el período de protección configura un abuso de derecho [Fuente 1]. En el caso específico, dado que la trabajadora se encuentra en licencia desde hace 45 días, el empleador debe acreditar fehacientemente una causa ajena al estado de salud para evitar la presunción de discriminación [Fuente 2]. Los documentos de la causa evidencian que el telegrama de despido invoca 'falta de colaboración', argumento que la jurisprudencia ha considerado insuficiente cuando coincide temporalmente con una licencia médica [Doc Causa 1]."

 BUENO (exploratorio):
"La Cámara Nacional del Trabajo ha establecido de manera reiterada que el despido sin justa causa de una trabajadora embarazada constituye una discriminación por razón de género [Fuente 1]. Este criterio fue ratificado en un caso reciente donde el tribunal destacó que la presunción de discriminación opera aun cuando el empleador desconociera el estado de gravidez [Fuente 2]. Por tanto, ante un despido durante el período de protección, la carga de acreditar que existió una causa ajena al embarazo recae sobre el empleador."

 EVITAR:
"Según https://ejemplo.com... [incluye URL]"
"1) Primer punto... 2) Segundo punto... [lista numerada]"
"No tengo suficiente información. [declara impotencia prematuramente]"
"La causa trata sobre X pero no puedo analizar sin más datos. [ignora contexto disponible]"

AHORA PROCEDE:
Analizá las fuentes, conectá con el contexto de la causa (si existe), aplicá tu expertise jurídico y proporciona un análisis profesional y fundamentado."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]