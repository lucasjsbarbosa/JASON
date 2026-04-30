# JASON — Product Context

> *YouTube outlier intelligence pra @babygiulybaby (canal PT-BR de reviews/análises de filmes de terror)*

## Register

**product** (com trajetória pra brand). Hoje é dashboard interno; design SERVE o produto. Mas a criadora declarou intenção de **eventualmente apresentar pra outras criadoras BR de terror** (eventualmente SaaS minimal). Implicação: cada decisão de design deve ser justificável em 2 anos quando ela mostrar pra alguém — não pode ser "feio é OK porque é só pra mim".

## Users

**A criadora do canal @babygiulybaby**, ~3.5k subs, faz reviews e análises de filmes de terror em PT-BR. Não-técnica: não programa, não entende ML, não quer ler "pairwise intra-bucket accuracy" ou "SHAP contributions".

**Modo de uso é misto**:
- Notebook + mobile (responsive real, não desktop-only)
- Diurno e noturno
- Sessões curtas (5-15 min, mobile rápido) E sessões longas de exploração (notebook em produção)

A creator **NÃO está com pressa**. Ela quer **entender o nicho** via JASON, não só pegar uma resposta. UI deve explicar antes de propor, e surfacear padrões que ela ainda não viu.

**Anti-persona**: data scientist olhando métrica de modelo. JASON não é jupyter notebook. Mas também não é "tap a button" minimal app — ela quer profundidade.

## Product Purpose

Tirar o achismo de 3 decisões: **título do vídeo · thumbnail · momento de publicar**. Cada uma alimentada por dados de 41 canais BR de terror ingeridos diariamente.

Decisões secundárias (futuro): tema do próximo vídeo, evolução do canal próprio, feedback loop A/B.

## Tom (palpável, não abstrato)

- **Não é animado**. Sem "🎉 Welcome!", sem encorajamento. Tom direto e meio sombrio, condizente com o nicho.
- **Tem personalidade do nicho**. Pode usar referências de terror (Jason Voorhees, slasher, found footage) onde encaixa. NÃO faz piada com a creepi-mood — respeita.
- **Não explica óbvio**. Cabe à criadora ler o número e decidir. UI mostra dimensões, não dita ação ("publique terça às 19h" é cringe).
- **Sem jargão técnico EXCETO pra inputs avançados** (escondidos em "opções avançadas"). Zero "SHAP", "embedding", "pairwise". Sim a "duração", "tamanho do canal", "% em CAPS".

## Brand / Visual Identity

- **Logo**: `{JASON}` em estilo brutalist com máscara de hockey do Jason no "O", glitch sangrento à direita evocando dado JSON corrompido. Bone/cream + blood red.
- **Paleta provisória** (atual no Next.js):
  - bg `#0E0E0E` (near-black, NÃO `#000`)
  - text `#E8E5DE` (bone)
  - accent `#B11C19` (blood-red, ~5-10% das pixels só)
  - gold `#D4AF37` (mid-tier indicators, raríssimo)
  - muted `#888880`
- **Fontes**: `Special Elite` (typewriter, headings) + `Inter` (body) + `JetBrains Mono` (números/código). **Não Inter pra everything** — Inter é a primeira reflex de IA, evitar dominância.

## Anti-references explícitas

A criadora **rejeita** ativamente esses padrões. Match-and-refuse:

1. **Streamlit aesthetic**. Ela disse literalmente "Streamlit é muito feio. Quero algo moderno". Sair completamente.
2. **AI synthwave / cyberpunk neon**. Roxo gradiente, glow cards, blue-on-black trendy. "Nada parecido feito por IA" foi explícito.
3. **SaaS dashboard genérico**. Big number + small label hero + supporting stats + 4 cards iguais com ícone+heading+texto.
4. **Glassmorphism gratuito**. Blur por blur. Cards translúcidos sem razão.
5. **Gradiente decorativo**. Texto com gradient-text, fundos roxo-pra-rosa, animation hover com hue shift.
6. **Rounded everything**. Border-radius default em tudo. Cantos vivos cabem mais no projeto.
7. **Encorajamento vazio**. "Great job!", "🎉", "Welcome back!" — nada disso.

## Strategic Principles

1. **Confiança + descoberta, não velocidade**. UI explica antes de propor. Surfaces padrões que ela ainda não viu. NÃO otimiza pra "decidir em 30s". Cada tela ensina algo do nicho enquanto entrega o resultado.
2. **Mostrar dimensões, não decidir por ela**. Modelo dá score + contribuições por feature; humano sintetiza. Nunca "publish at 7pm" como recommendation única.
3. **Honesto sobre incerteza**. Modelo em bootstrap (sample tier_1 pequeno) → UI diz isso. Contribuições <±0.05 são filtradas como ruído. Sem fingir confiança que não há.
4. **Tradução obrigatória**. Toda string técnica do modelo passa por `humanize.py` antes de UI. "subs_bucket=1" → "pequeno (1k–10k)". "published_hour=15" → "12h" (UTC→BRT). "theme_id=4_terror_pesadelo_assustador_um" → "Terror · Pesadelo · Assustador".
5. **Coexistência de duas perspectivas**: o que o **modelo** previu pra o canal dela vs estatística do **nicho** geral. Quando divergem, é sinal real (sub-segmento), não bug.
6. **Responsive real desde o começo**. Mobile não é afterthought. Ela checa do celular tanto quanto do notebook. Cada componente passa em viewport 375px sem virar lixo.
7. **Apresentável em 2 anos**. Cada decisão visual deve aguentar ela mostrar pra colega criadora sem encolher. Sem atalhos de "feio mas funciona porque é interno".

## Surface map (rotas atuais)

| Rota | Pergunta da criadora | Estado |
|---|---|---|
| `/` | "como tá meu canal?" | métricas + top vídeos próprios |
| `/outliers` | "o que tá bombando no nicho?" | filtro por canal, tier, percentil |
| `/avaliar` | "esse título é bom?" | score + por-quê-humanizado |
| `/sugerir` | "que título usar pro próximo vídeo?" | RAG + Claude + ranqueamento + "publiquei essa" |
| `/thumbs` | "que frame virar capa?" | upload vídeo, top frames, paleta, overlay advisor |

## What Success Looks Like

- A criadora abre `/sugerir`, cola transcrição, escolhe um título dos 10 candidatos em ≤2min sem precisar perguntar nada.
- Quando ela escolhe rank #5 dos 10, o sistema captura isso como sinal "modelo errou aqui" pro retrain — sem ela pensar em ML.
- A interface não parece feita por IA quando ela mostra pra outras criadoras BR.
