# WORKLOG — diário de bordo entre máquinas

> Arquivo curto. Cada sessão de trabalho (desktop OU notebook) **lê** isso
> no início e **acrescenta** uma entrada no fim. Mantém o estado mental
> entre máquinas e entre agentes.
>
> Regras pra atualizar:
> - **No início:** lê esta página inteira + `git log --oneline -20` pra ver
>   commits depois da última entrada. Não pergunta ao usuário "o que foi
>   feito?" — descobre sozinho.
> - **No fim:** acrescenta UMA entrada nova no topo da lista (mais novo
>   primeiro). Mantém só as 6 entradas mais recentes — apaga as antigas.
> - **Formato:** data, máquina, resumo (3-5 linhas), bloco "pendente" se
>   houver, bloco "atenção" se algo precisa cuidado.
> - Antes de encerrar a sessão, sempre `git add WORKLOG.md && git commit
>   && git push`. Sem isso, a outra máquina não vê.

---

## 2026-05-01 · desktop · setup multi-máquina

Configurado o repositório pra rodar em qualquer máquina via `git clone`:
- Git LFS rastreia `data/warehouse.duckdb` (390MB) + `src/jason/models/artifacts/`
  (modelos `.lgb` e `.pkl`). Total LFS: ~430MB, dentro dos 5GB free.
- `scripts/bootstrap-laptop.sh` faz clone+lfs+uv+npm+thumbs num comando.
- `WORKLOG.md` (este arquivo) criado pra os agentes manterem contexto
  entre máquinas.
- README ganhou seção "Rodar num segundo computador".

Antes nessa mesma sessão (já commitado):
- 4 páginas novas: `/palavras`, `/comparar`, `/temas`, `/sugerir` reformulada,
  `/avaliar` reformulada com seletor de horário.
- Conserto estrutural do `feature_context.py`: agora filtra distribuição por
  `subs_bucket` (tier). Antes mostrava "outliers usam 71% CAPS" porque pool
  global é dominado por canais 1M+; tier_1 (1k-10k) real é 23%.
- Booleans agora mostram lift do multiplier ("raro 7% mas quem usa vira
  outlier 3.6× maior") em vez de só rate, eliminando contradições com SHAP.
- Endpoints `/api/own/packaging-gap` e `/api/own/themes` voltaram a ser
  consumidos na home (eram órfãos), filtrados por tier.

### Pendente (priorizado, vem do `/impeccable critique`)

1. **Form de A/B feedback** (item 1.3 do critique). `title_tests` schema
   existe, UI sumiu na migração Streamlit→Next. Loop de feedback morto.
2. **CTR/AVD na home** (1.4). `youtube_analytics_metrics` populado quando
   user roda `jason analytics pull`, nenhum endpoint lê.
3. **Calendário visual de horror_releases** (1.5). Tabela alimenta
   `theme_suggester` mas nunca é renderizada como timeline.
4. **Histórico de sugestões + override rate** (1.6). `suggestions.chosen_at`
   é populado mas nunca lido. "Modelo está acertando comigo?" sem resposta.
5. **Snapshot freshness banner** (1.8). Pipeline depende de cron diário;
   se quebrar, criadora não sabe.
6. **Cortar `/avaliar`** (2.1). 95% sobreposição com `/sugerir`. Vira
   colapsável dentro de `/sugerir`.
7. **VLM thumb annotation full run**. Pipeline pronto, pilot validado com
   8 thumbs. Custa ~$12 pra rodar nas 17k. `jason features thumb-vlm`.
8. **OAuth analytics auth via UI**. Hoje só CLI; criadora não consegue
   conectar o canal dela sozinha.

### Atenção

- **Não rode `jason snapshot run` em duas máquinas simultaneamente** — vai
  duplicar uso de quota da YouTube Data API. Desktop é dono da ingestão
  (Task Scheduler diário). Notebook fica em modo leitura.
- **Não edite `main.py` enquanto `/sugerir` ou `/score` estiverem
  processando** — uvicorn `--reload` vai derrubar a request silenciosamente.
- DB tem single-writer lock: se `/api/...` retorna 500 e o log diz "lock
  conflict", outro processo está escrevendo (geralmente snapshot run).
