# RAG Enterprise Compet-e Legal

Sistema RAG (Retrieval-Augmented Generation) **multi-tenant** per la gestione e l'interrogazione in linguaggio naturale di documenti aziendali/legali (contratti, pareri, normative, bilanci). Espone un backend **FastAPI**, una pipeline di ingestione documentale asincrona (**Celery**), un motore di retrieval ibrido su **Qdrant**, generazione risposte via **LLM** (Ollama/OpenAI/Google) e un'interfaccia utente **Chainlit** in stile chat.

> Questo documento descrive il comportamento **effettivo** del codice così come si trova oggi nel repository, comprese le incongruenze, i moduli non collegati e il codice morto individuati durante l'analisi — segnalati esplicitamente dove rilevanti, per evitare di documentare funzionalità che sembrano esistere ma non sono raggiungibili a runtime.

---

## Indice

1. [Panoramica architetturale](#1-panoramica-architetturale)
2. [Stack tecnologico](#2-stack-tecnologico)
3. [Multi-tenancy](#3-multi-tenancy)
4. [Autenticazione e autorizzazione](#4-autenticazione-e-autorizzazione)
5. [Pipeline di ingestione documenti](#5-pipeline-di-ingestione-documenti)
6. [Pipeline di retrieval](#6-pipeline-di-retrieval)
7. [Generazione della risposta (RAG chain)](#7-generazione-della-risposta-rag-chain)
8. [Il grafo LangGraph (implementato ma non collegato)](#8-il-grafo-langgraph-implementato-ma-non-collegato)
9. [Memoria conversazionale](#9-memoria-conversazionale)
10. [API di riferimento](#10-api-di-riferimento)
11. [Worker Celery e task in background](#11-worker-celery-e-task-in-background)
12. [Interfaccia utente Chainlit](#12-interfaccia-utente-chainlit)
13. [Configurazione](#13-configurazione)
14. [Come avviare il progetto](#14-come-avviare-il-progetto)
15. [Script di utilità](#15-script-di-utilità)
16. [Test](#16-test)
17. [Problemi noti e codice legacy](#17-problemi-noti-e-codice-legacy)

---

## 1. Panoramica architetturale

```
                                   ┌──────────────────┐
                                   │   Chainlit UI    │  (porta 8080, chat web)
                                   │  chainlit_app/    │
                                   └────────┬─────────┘
                                            │ HTTP/SSE (Bearer JWT)
                                            ▼
                                   ┌──────────────────┐
                                   │     FastAPI       │  (porta 8000)
                                   │   app/api/*        │
                                   └───┬─────┬─────┬───┘
                     ┌─────────────────┘     │     └─────────────────┐
                     ▼                       ▼                       ▼
            ┌─────────────────┐   ┌───────────────────┐   ┌──────────────────┐
            │   SQL Server     │   │       Redis        │   │      Qdrant       │
            │ (schema/tenant)  │   │ (sessioni, cache,   │   │ (vector store,     │
            │                  │   │  rate limit, broker)│   │  collection/tenant)│
            └─────────────────┘   └─────────┬──────────┘   └──────────────────┘
                                            │ broker/backend
                                            ▼
                                ┌────────────────────────┐
                                │   Worker Celery          │
                                │  (ingestion, cleanup,     │
                                │   task periodici/beat)    │
                                └────────────────────────┘
```

Componenti principali:

- **`app/`** — backend FastAPI (API, business logic, pipeline RAG, accesso dati).
- **`chainlit_app/`** — interfaccia chat web, client HTTP leggero verso il backend (nessuna logica RAG al suo interno).
- **`config/`** — file YAML di configurazione applicativa (config generale, logging, metadati documenti, prompt).
- **`docker/`** — Dockerfile dei servizi e script di init database.
- **`scripts/`** — utility CLI (provisioning tenant, seed dati demo, benchmark retrieval).
- **`docker-compose.yml`** + **`docker-compose.override.yml`** — orchestrazione servizi (produzione-like + sviluppo con hot-reload).

L'LLM (Ollama di default) **non è incluso** nel `docker-compose.yml`: va eseguito separatamente (host o altro container) e reso raggiungibile all'URL configurato (`http://ollama:11434` di default).

---

## 2. Stack tecnologico

| Livello | Tecnologia |
|---|---|
| API | FastAPI + Uvicorn (uvloop/httptools) |
| Orchestrazione RAG | LangChain, LangGraph (parzialmente collegato, vedi §8) |
| LLM | Ollama (default, `llama3.1`), OpenAI, Google Gemini — selezionabili via config |
| Embedding | FastEmbed, modello `BAAI/BGE-M3` (dense) + `prithivida/Splade_PP_en_v1` (sparse/SPLADE) |
| Reranking | `sentence-transformers` CrossEncoder, modello `BAAI/bge-reranker-base` |
| Vector store | Qdrant (vettori named "dense" + "sparse" nella stessa collection, una collection per tenant) |
| Parsing documenti | Docling (default) con fallback su `unstructured`; Excel via `openpyxl` |
| Database relazionale | SQL Server 2022 (schema dedicato per tenant) |
| Cache / code / sessioni | Redis (DB 0 sessioni/rate-limit/broker Celery, DB 1 cache risposte) |
| Task asincroni | Celery + Redis broker, scheduling con `celery-redbeat` |
| UI chat | Chainlit |
| Auth | JWT (HS256) + API Key (hash SHA-256), bcrypt per le password |
| Observability | Loguru, LangSmith (opzionale), OpenTelemetry (opzionale) |
| Ricerca web (opzionale) | Tavily / DuckDuckGo (`ddgs`) — **non raggiungibile in produzione**, vedi §8 |

---

## 3. Multi-tenancy

Il sistema isola i dati di ogni cliente (**tenant**) su tre livelli indipendenti:

### 3.1 SQL Server — schema per tenant
- Un solo database `RAGChat`, con:
  - schema **`shared`**: tabelle globali cross-tenant — `tenants`, `audit_log`, `usage_stats`, `api_keys`.
  - uno schema **`tenant_<slug>`** dedicato per ogni tenant (es. `tenant_acme_corp`), creato dinamicamente dalla stored procedure `shared.sp_provision_tenant` (T-SQL, `sp_executesql`), contenente: `users`, `collections`, `documents`, `ingestion_jobs`, `conversations`, `messages`, `message_feedback`, `conversation_summaries`, `user_facts`.
- Per ogni tenant viene creato anche un **utente SQL Server dedicato** (`usr_tenant_<slug>`, WITHOUT LOGIN) con permessi limitati al proprio schema. A runtime, prima di ogni query viene eseguito `EXECUTE AS USER = 'usr_tenant_<slug>'` (impersonation) e poi `REVERT` — un secondo livello di isolamento indipendente dalla logica applicativa.
- **Non esiste un vero ORM a runtime**: le classi SQLAlchemy in `app/db/models/shared.py` sono definite ma non usate; tutto l'accesso ai dati (shared e per-tenant) passa da SQL raw tramite `text()` nei repository (`app/db/repositories/*`).
- Le query applicative quasi non filtrano mai esplicitamente per `tenant_id`: l'isolamento è garantito dallo schema/utente DB selezionato dinamicamente in base al tenant risolto dal token.

### 3.2 Qdrant — una collection per tenant
- `get_collection_name(tenant_slug)` → `tenant_<slug>_documents` (slug con `-` sostituiti da `_`).
- Ogni collection contiene **due vettori named** per punto: `"dense"` (BGE-M3) e `"sparse"` (SPLADE) — non sono collection separate.
- Esiste anche una collection dedicata alla memoria conversazionale (`tenant_<slug>_memory`), predisposta ma non risulta collegata al flusso attivo.
- Isolamento quindi **fisico** (collection separata) più un filtro logico ridondante (`tenant_id` nel payload) come difesa aggiuntiva.

### 3.3 Redis — namespacing per chiave
- Tutte le chiavi usate da `TenantRedis` sono prefissate `tenant:<tenant_id>:...` (sessioni, cache query, rate limit, stato job).

---

## 4. Autenticazione e autorizzazione

### 4.1 Metodi supportati
- **JWT Bearer** (`Authorization: Bearer <token>`): claim `sub` (user_id), `role`, `tenant_id`, `tenant_slug`, `exp`/`iat`. Algoritmo e scadenza configurabili (`jwt_algorithm`, default HS256; `jwt_expire_minutes`, default 60). Il tenant è quindi **incorporato nel token** stesso.
- **API Key** (header `X-API-Key`): chiave in formato `rag_<token_urlsafe>`, verificata via hash SHA-256 confrontato in tempo costante (`secrets.compare_digest`) contro `shared.api_keys` (con controllo scadenza/attivazione).

### 4.2 Dove viene applicata
- `app/api/deps.py::get_current_tenant` è la **vera dependency di autenticazione**: prova prima Bearer, poi API Key; se nessuna produce un contesto valido → **401**. Da questa dipendono `get_db` (sessione SQL tenant-scoped), `get_tenant_redis`, `require_admin`.
- `TenantMiddleware` (globale, in `main.py`) esegue lo **stesso parsing JWT** ma in modo *non bloccante*: si limita a popolare `request.state` per il logging; se il token manca/non è valido non blocca la richiesta. È quindi puramente informativo, non un gate di sicurezza.

### 4.3 Ruoli
`admin`, `user`, `viewer`, `api` (per le richieste via API Key) sono gestiti tramite `TenantContext.is_admin`/`is_viewer` e la dependency `AdminOnly`. Esiste inoltre un ruolo `superadmin`, usato solo nelle route di gestione tenant (`app/api/routes/tenants.py`) con un controllo locale ad-hoc, non tramite la dependency riutilizzabile.

**Nota**: l'applicazione del ruolo è **incoerente tra le route**: `collections.py`/`users.py` usano `AdminOnly`; `tenants.py` usa un controllo `superadmin` locale; `documents.py`/`jobs.py`/`chat.py` non impongono alcun controllo di ruolo oltre l'autenticazione di base (qualsiasi utente del tenant può, ad esempio, cancellare i job di ingestion altrui).

---

## 5. Pipeline di ingestione documenti

Avviata da `DocumentService.upload_and_queue` (chiamato da `POST /api/v1/documents/upload`), eseguita in background da Celery (`app/workers/ingestion_tasks.py::ingest_document`), orchestrata da `app/rag/ingestion/pipeline.py::run_ingestion_pipeline`.

### 5.1 Flusso end-to-end
1. **Upload**: il file (multipart) viene validato per estensione (`.pdf .docx .xlsx .pptx .txt .md`), l'hash SHA-256 del contenuto viene calcolato per deduplicare (rifiuta upload di file identici già presenti), il file viene salvato su `/app/uploads/<tenant_slug>/<uuid><ext>`. Viene creata la riga `documents` (status `pending`) e `ingestion_jobs` (status `queued`), poi si accoda `ingest_document.apply_async(..., countdown=3)` sulla coda Celery `default`.
2. **Parsing** (`app/rag/ingestion/parser.py`): instradamento per estensione.
   - PDF/DOCX/PPTX → **Docling** (default, `settings.ingestion_prefer_docling=True`), con fallback automatico su **Unstructured** (`strategy="fast"`) in caso di eccezione. OCR disattivato (`do_ocr=False`).
   - XLSX/XLS → parsing diretto via `openpyxl` (ogni foglio → sezione markdown).
   - TXT/MD → lettura diretta UTF-8.
   - Docling esporta il testo in **Markdown** e, se `ingestion_extract_tables=True` (default), estrae le tabelle separatamente in markdown con numero di pagina.
3. **Pulizia testo** (`app/rag/ingestion/cleaner.py::clean_text`): rimozione caratteri di controllo, normalizzazione a-capo, rimozione righe che sono solo numeri di pagina, **rimozione automatica di header/footer ripetuti** (righe che compaiono più di 5 volte nel documento), collasso di spazi/newline multipli.
4. **Chunking** (`app/rag/ingestion/chunker.py::chunk_document`): strategia configurabile (`ingestion_chunk_strategy`, default **`markdown`** → `MarkdownTextSplitter`; altrimenti `RecursiveCharacterTextSplitter` con separatori `["\n\n","\n",". "," ",""]`). Dimensione chunk **1000 caratteri**, overlap **200 caratteri** (20%). I chunk sotto i 50 caratteri vengono scartati. Ogni chunk riceve un `chunk_index` progressivo e un tentativo euristico di `page_number` (matching testuale contro le pagine originali, best-effort).
5. **Metadati** (`app/rag/ingestion/metadata.py`): oltre ai campi base (`tenant_id`, `collection_id`, `document_id`, `filename`, `file_type`, `chunk_index`, `page_number`, `ingested_at`), viene calcolato **`doc_type`** tramite classificazione automatica per keyword su un campione del testo + filename, secondo la tassonomia definita in `config/metadata.yaml`:
   - `contract` (contratto, accordo, convenzione…)
   - `legal_opinion` (parere, nota legale…)
   - `regulation` (decreto, legge, regolamento…)
   - `financial` (bilancio, stato patrimoniale…)
   - `generic` (fallback)
   - *Nota*: lo YAML dichiara campi ricchi aggiuntivi per tipo (es. `parties`, `contract_date`, `jurisdiction` per i contratti) ma il codice attuale **non li estrae** — sono solo schema dichiarato, non implementazione.
6. **Embedding** (`app/core/embeddings.py`): vettore denso con **FastEmbed BGE-M3** (batch da 64, cache modello in memoria di processo), vettore sparso con **SPLADE** (`prithivida/Splade_PP_en_v1`) se `qdrant_use_sparse=True` (default).
7. **Scrittura su Qdrant**: `ensure_collection` crea la collection del tenant se non esiste (vettori named `dense`/`sparse`, `on_disk=True`, payload index su `tenant_id`/`document_id`/`doc_type`); upsert in batch da 100 punti, ogni punto con `id=uuid4()` casuale (**non deterministico**: re-ingerire lo stesso file produce duplicati, non un upsert idempotente) e payload contenente anche il testo del chunk (necessario per restituirlo in fase di generazione senza fetch aggiuntivo).
8. **Aggiornamento stato**: `ingestion_jobs.status='done'`, `documents.status='ready'` con `chunk_count`/`page_count`; **invalidazione della cache query Redis** del tenant. In caso di errore: retry automatico con backoff esponenziale (fino a 3 tentativi), poi `status='failed'`.

### 5.2 Formati e limiti
- Estensioni supportate: `pdf, docx, xlsx, pptx, txt, md`.
- Dimensione massima file: `ingestion_max_file_mb` (default 100 MB).

---

## 6. Pipeline di retrieval

Punto di ingresso unico: `app/rag/retrieval/retriever.py::retrieve(query, tenant_slug, tenant_id, collection_id=None, top_k=None, filters=None)`.

1. **Embedding query**: stesso modello BGE-M3 usato in ingestione (coerenza dello spazio vettoriale).
2. **Filtri**: sempre `tenant_id == tenant_id` (ridondante rispetto alla collection dedicata, difesa aggiuntiva); opzionale `collection_id`; eventuali filtri custom come match esatti.
3. **Ricerca ibrida**:
   - Dense: ricerca coseno sul vettore `"dense"`, soglia minima `score_threshold=0.3`, limit = `retriever_top_k` (default **20**).
   - Sparse (se abilitata): ricerca SPLADE sul vettore `"sparse"`; se fallisce, **degrada silenziosamente** continuando solo con i risultati dense (nessun blocco della richiesta).
4. **Fusione RRF** (Reciprocal Rank Fusion, costante 60): combina i due ranking, sommando i contributi per i punti presenti in entrambe le liste.
5. **MMR** (se `retriever_strategy=mmr`, default): diversificazione dei risultati. *Nota*: non è una vera MMR su similarità semantica — usa un'euristica basata su `document_id`/distanza tra `chunk_index` per penalizzare chunk vicini dello stesso documento.
6. **Reranking cross-encoder** (se `reranker_enabled=True`, default): modello `BAAI/bge-reranker-base`, tronca il risultato finale a `reranker_top_k` (default **5**) — è questo lo step che determina il numero di chunk realmente passati alla generazione.

```
query → embed dense → search dense (soglia 0.3, limit 20)
                    → [se sparse] embed SPLADE → search sparse (limit 20)
      → fusione RRF (k=60) → tronca a top_k=20
      → [se mmr] diversificazione euristica per document_id/chunk_index
      → [se reranker] cross-encoder rerank → tronca a 5
      → output: chunk con testo, score, filename, pagina, doc_type
```

---

## 7. Generazione della risposta (RAG chain)

> **Importante**: il percorso realmente servito dalle API è `app/services/chat_service.py` (chain lineare procedurale), **non** il grafo LangGraph (vedi §8). Questa sezione descrive il flusso effettivamente eseguito da `/api/v1/chat/query` e `/api/v1/chat/stream`.

1. **Cache**: hash MD5 di `conversation_id:domanda_normalizzata` → se presente in Redis, ritorna subito la risposta cachata senza chiamare l'LLM.
2. **Storico**: recupero degli ultimi turni di conversazione da Redis (memoria a breve termine, vedi §9).
3. **Retrieval**: come descritto al §6.
4. **Generazione** (`app/rag/generation/chain.py`):
   - Se non ci sono chunk rilevanti → risposta di fallback immediata ("nessun contesto trovato"), **senza invocare l'LLM**.
   - Altrimenti: costruzione del contesto (`context_builder.build_rag_context`, troncato a 12.000 caratteri, per chunk interi), composizione del prompt (system + user, da `config/prompts.yaml`, sezione `rag.main`, con placeholder `{context}`, `{history}`, `{question}`) e invocazione dell'LLM (`llm.ainvoke` non-streaming, `llm.astream` per lo streaming token-by-token).
   - Il prompt istruisce l'LLM a citare le fonti nel formato `[Fonte: nome_file, p.X]` e a dichiarare esplicitamente quando l'informazione non è nei documenti.
5. **Validazione risposta** (`app/rag/generation/answer_validator.py`): sostituisce risposte vuote/pattern "non lo so" con un messaggio fisso; tronca risposte troppo lunghe (>8000 char) a fine frase; rimuove artefatti tipici degli LLM (prefissi tipo "RISPOSTA:", fence markdown superflui, chiusure tipo "Spero sia stato utile").
6. **Controllo allucinazioni** (`app/rag/generation/hallucination.py::check_faithfulness`): un secondo giro all'LLM (stesso modello, nessun modello dedicato più economico) valuta quanto la risposta sia supportata dal contesto (score 0–1, soglia di default 0.5). **Il punteggio viene solo loggato e salvato su DB — non blocca né rigenera la risposta** (comportamento "fail-open": se il parsing dello score fallisce, si assume 1.0 di default).
7. **Persistenza**: risposta e metadati (fonti, token in/out, latenza, hallucination score) salvati su SQL Server (`messages`); storico aggiornato su Redis; risposta cachata; contatori di utilizzo giornalieri incrementati (poi aggregati dal task Celery `rollup_usage`).

**Nota sulle citazioni**: esiste un modulo `app/rag/generation/citations.py` per il parsing strutturato delle citazioni nel testo, ma **non viene mai invocato**: le "fonti" restituite al client sono semplicemente l'elenco dei chunk recuperati (non un parsing di quali citazioni l'LLM ha effettivamente usato nel testo).

---

## 8. Il grafo LangGraph (implementato ma non collegato)

Il repository contiene un'implementazione completa e ben strutturata di un flusso RAG **agentico** basato su LangGraph (`app/rag/graph/`), con:

- **`state.py`**: `RAGState` (TypedDict) — domanda, tenant, route, chunk recuperati, storico sessione, risultati web, risposta, fonti, token, latenza, hallucination score.
- **`nodes.py`**: 8 nodi asincroni — `node_route` (classificazione intento), `node_load_session`, `node_retrieve`, `node_web_search`, `node_generate`, `node_generate_web`, `node_check_hallucination`, `node_save_to_memory`.
- **`edges.py`**: routing condizionale — se `route == "web"` → ricerca web, altrimenti → retrieval RAG.
- **`graph.py`**: compila la topologia `load_session → route → (retrieve|web_search) → generate → check_hallucination → save_to_memory → END`.
- **`app/rag/agents/router_agent.py`**: classifica la domanda in 4 categorie (`rag`, `web`, `sql`, `general`) tramite LLM, **ma è disattivato di default** (`web_search_enabled=False` → ritorna sempre `"rag"` senza chiamare l'LLM).
- **`app/rag/agents/web_agent.py`**: ricerca web via Tavily (default) o DuckDuckGo (`ddgs`), con generazione della risposta dai risultati.

**Questo intero sottosistema non è mai invocato da nessuna route API o servizio attivo** (verificato: `run_rag_graph`/`get_rag_graph` non hanno chiamanti nel resto del codebase). Di conseguenza:
- Il routing multi-agente (RAG / Web / SQL / generico) **non avviene mai in produzione**: ogni domanda passa sempre dal retrieval RAG diretto in `chat_service.py`.
- La ricerca web, pur implementata e configurabile, **non è raggiungibile** dall'applicazione reale.
- Gli agenti SQL e i tool (`app/rag/agents/tools/OLD*`) menzionati nel prompt di routing non esistono più come implementazione (file vuoti, vedi §17).

Se in futuro si vuole attivare il routing multi-agente, il grafo è pronto: va collegato da `chat_service.py` (o da una nuova route) al posto della chain lineare attuale.

---

## 9. Memoria conversazionale

- **Memoria a breve termine** (attiva, in uso): implementata direttamente in `chat_service.py` tramite `TenantRedis` — lista Redis (`RPUSH`/`LTRIM`) con gli ultimi `memory_short_term_turns` (default **10**) turni, TTL configurabile. Esiste anche una classe wrapper `app/rag/memory/short_term.py::ShortTermMemory` con la stessa logica, ma **non è usata** dal percorso attivo (duplicazione, non un bug bloccante).
- **Memoria a lungo termine** (`app/rag/memory/long_term.py::LongTermMemory`): riassunti di conversazione + estrazione di "fatti utente" persistenti (preferenze, competenze, istruzioni) via LLM, salvati su SQL Server (`conversation_summaries`, `user_facts`). Disabilitata di default (`memory_long_term_enabled=False`) e **non istanziata da nessuna parte del codice attivo** — anche abilitandola, il `context_builder` non ha un placeholder nel prompt per iniettare questi fatti, quindi il collegamento end-to-end non è completo.
- **`context_builder.py`**: assembla il testo del contesto RAG (chunk + storico) rispettando un limite di caratteri (12.000 default, troncamento per chunk intero) e produce l'elenco `sources` formattato per la risposta API.

---

## 10. API di riferimento

Tutte le route (tranne `/health`, `/ready`, `/docs`, `/redoc`, `/openapi.json`) richiedono autenticazione (Bearer JWT o `X-API-Key`). Prefisso comune: `/api/v1`.

### Autenticazione (`/api/v1/auth`)
| Metodo | Path | Auth | Descrizione |
|---|---|---|---|
| POST | `/auth/login` | pubblico | `{email, password, tenant_slug}` → JWT |
| POST | `/auth/refresh` | Bearer/API Key | riemette un nuovo JWT con gli stessi claim |
| GET | `/auth/me` | Bearer/API Key | profilo utente corrente |
| POST | `/auth/logout` | Bearer/API Key | invalida le sessioni di conversazione Redis (**non** revoca il JWT, che resta valido fino a scadenza) |

### Chat (`/api/v1/chat`)
| Metodo | Path | Descrizione |
|---|---|---|
| POST | `/chat/query` | domanda → risposta RAG completa (one-shot), body `{question, conversation_id?, collection_id?}` |
| POST | `/chat/stream` | come sopra ma risposta in streaming SSE (token incrementali + pacchetto finale con fonti/metadati) |
| POST | `/chat/feedback` | invia rating (-1/0/1) + commento su un messaggio |

### Documenti e collezioni (`/api/v1`)
| Metodo | Path | Auth | Descrizione |
|---|---|---|---|
| POST | `/documents/upload` | utente autenticato | upload file (`multipart/form-data`, campi `file`, `collection_id?`) → 202, accoda ingestion |
| GET | `/documents` | utente autenticato | lista paginata, filtri `collection_id`/`status` |
| GET | `/documents/{id}/status` | utente autenticato | stato job di ingestion |
| DELETE | `/documents/{id}` | utente autenticato | cancella vettori Qdrant + soft-delete DB |
| POST | `/collections` | utente autenticato | crea una collezione documentale logica |
| GET | `/collections` | utente autenticato | lista collezioni attive |
| DELETE | `/collections/{id}` | **solo admin** | soft-delete collezione |

### Job di ingestion (`/api/v1/jobs`)
| Metodo | Path | Descrizione |
|---|---|---|
| GET | `/jobs` | lista paginata job (filtro `status`) |
| GET | `/jobs/{id}` | dettaglio job |
| POST | `/jobs/{id}/cancel` | annulla un job `queued`/`running` (revoca il task Celery) |

### Utenti e tenant (solo admin/superadmin)
| Metodo | Path | Auth | Descrizione |
|---|---|---|---|
| POST | `/users` | admin | crea utente nel tenant corrente |
| GET | `/users` | admin | lista utenti del tenant |
| DELETE | `/users/{id}` | admin | soft-delete utente |
| POST | `/tenants` | superadmin | provisioning nuovo tenant (schema DB + collection Qdrant + utente admin) |
| GET | `/tenants` | superadmin | lista di tutti i tenant |
| PATCH | `/tenants/{slug}/disable` | superadmin | disattiva un tenant |

### Health (pubblici, senza prefisso)
| Metodo | Path | Descrizione |
|---|---|---|
| GET | `/health` | liveness check semplice |
| GET | `/ready` | readiness check: verifica Redis, SQL Server, Qdrant (503 se uno è down) |

Documentazione interattiva OpenAPI disponibile su `/docs` (Swagger) e `/redoc`, **solo se `app_debug=True`**.

---

## 11. Worker Celery e task in background

App Celery `rag_worker`, broker/backend su Redis, 4 code: `high`, `default`, `low`, `shared_cleanup`. Scheduling periodico via **Celery Beat + RedBeat** (scheduler distribuito su Redis, adatto a più worker/container).

| Task | Coda | Descrizione |
|---|---|---|
| `ingest_document` | `default` | pipeline di ingestione completa (parsing → chunking → embedding → upsert Qdrant), retry con backoff esponenziale (max 3) |
| `reprocess_document` | `low` | cancella i vettori esistenti di un documento e rilancia l'ingestione |
| `purge_tenant` | `shared_cleanup` | cancellazione completa di un tenant (collection Qdrant, chiavi Redis, schema SQL Server) |
| `expire_sessions` | `shared_cleanup` | corregge le chiavi Redis di sessione senza TTL (manutenzione) |
| `rollup_usage` | `shared_cleanup` | aggrega giornalmente i contatori di utilizzo (token, query) per tenant in `shared.usage_stats` |

Scheduling: `rollup_usage` a mezzanotte, `expire_sessions` ogni ora.

Servizi Docker dedicati: `celery-worker-high` (code `high,shared_cleanup`, concorrenza 4), `celery-worker-default` (code `default,low`, concorrenza 2), `celery-beat` (scheduler), `flower` (UI monitoraggio su porta 5555, basic auth da `.env`).

---

## 12. Interfaccia utente Chainlit

`chainlit_app/app.py` è un **client HTTP leggero** verso il backend FastAPI (nessuna logica RAG propria).

- **Login**: form Chainlit nativo (utente/password). Se lo username è nel formato `email|tenant_slug` (es. `mario@acme.com|acme-corp`), viene usato quel tenant; altrimenti il tenant di default (`CHAINLIT_DEFAULT_TENANT`, default `demo-corp`). Il login fa `POST /api/v1/auth/login` e salva il JWT ricevuto nella sessione Chainlit.
- **Chat**: ogni messaggio apre uno stream SSE verso `POST /api/v1/chat/stream`; i token vengono mostrati incrementalmente; alla fine viene mostrato un messaggio separato con le **fonti utilizzate** (filename, pagina, score) e, per ogni fonte con snippet, un pannello laterale cliccabile col testo del chunk citato.
- **Continuità conversazionale**: il `conversation_id` restituito dal backend viene mantenuto in sessione per i turni successivi.
- Tema scuro, nessun playground prompt, nessun HTML/LaTeX non sicuro abilitati (vedi `.chainlit/config.toml`).

Non espone comandi/impostazioni aggiuntive: è puro front-end di chat.

---

## 13. Configurazione

La configurazione è a due livelli, uniti da `app/core/settings.py` (Pydantic Settings):

1. **`config/config.yaml`** — impostazioni strutturali/non sensibili (provider LLM/embedding, parametri retriever/reranker, ingestion, memoria, cache, rate limit, logging, osservabilità). I placeholder `${VAR}` (es. `${OLLAMA_API_KEY}`) vengono risolti da variabili d'ambiente.
2. **`.env`** (da creare in root, referenziato da `docker-compose.yml` in tutti i servizi) — segreti e override ambiente-specifici: `SQLSERVER_PASSWORD`, `REDIS_PASSWORD`, `FLOWER_USER`/`FLOWER_PASSWORD`, `QDRANT_API_KEY`, `OLLAMA_API_KEY`/`OPENAI_API_KEY`/`GOOGLE_API_KEY`, `TAVILY_API_KEY`, `JWT_SECRET_KEY` (**da impostare obbligatoriamente in produzione**, minimo 32 caratteri — il default è rifiutato solo se diverso dal placeholder ma troppo corto).

Altri file di configurazione:
- **`config/logging.yaml`**: formato log (console colorato o JSON), livello, rotazione file (disabilitata di default), campi di contesto propagati (`tenant_id`, `request_id`, `user_id`, `route`).
- **`config/metadata.yaml`**: schema dei metadati documento e tassonomia di classificazione automatica (`contract`, `legal_opinion`, `regulation`, `financial`, `generic`) con relative keyword di rilevamento.
- **`config/prompts.yaml`**: tutti i prompt di sistema (in italiano, dominio legale) — prompt RAG principale, fallback "nessun contesto", riscrittura/espansione query, hallucination check, generazione titolo conversazione, prompt per agenti SQL/web (predisposti, non attivi — vedi §8), classificazione del router.

Parametri di default rilevanti: chunk size 1000/overlap 200, `retriever_top_k=20`, `reranker_top_k=5`, ricerca ibrida (dense+sparse) con MMR, reranker abilitato, cache query 1h, sessione Redis 24h, JWT 60 minuti, rate limit 60 richieste/minuto.

---

## 14. Come avviare il progetto

### Prerequisiti
- Docker e Docker Compose.
- Un'istanza **Ollama** raggiungibile (o credenziali OpenAI/Google se si cambia provider), non inclusa nel compose.
- File `.env` in root con almeno: `SQLSERVER_PASSWORD`, `REDIS_PASSWORD`, `FLOWER_USER`, `FLOWER_PASSWORD`, `JWT_SECRET_KEY` (≥32 caratteri).

### Avvio in modalità sviluppo (hot-reload)
```bash
docker compose up --build
```
Docker Compose applica automaticamente sia `docker-compose.yml` sia `docker-compose.override.yml` (se presenti nella stessa directory): quest'ultimo monta il codice sorgente come bind mount, abilita `--reload` su FastAPI e Chainlit, riduce la concorrenza dei worker, disabilita password/persistenza Redis per semplicità di debug, ed espone la porta `5678` per un debugger remoto.

### Avvio "produzione-like" (solo file base)
```bash
docker compose -f docker-compose.yml up -d --build
```

### Servizi e porte esposte
| Servizio | Porta | Descrizione |
|---|---|---|
| `fastapi` | 8000 | API backend (`/docs` se `app_debug=true`) |
| `chainlit` | 8080 | interfaccia chat |
| `qdrant` | 6333 (HTTP) / 6334 (gRPC) | vector store |
| `redis` | 6379 | cache/sessioni/broker |
| `sqlserver` | 1433 | database relazionale |
| `flower` | 5555 | monitoraggio Celery (basic auth) |

### Primo utilizzo
1. Creare un tenant: `python scripts/create_tenant.py --slug acme-corp --name "Acme Corp" --plan pro --admin-email admin@acme.com --admin-password Xxxxxxxx`
2. (Opzionale) Popolare dati demo: `python scripts/seed_demo_data.py` (crea tenant `demo-corp`, utente `demo@demo-corp.com` / `Demo123456!`, e due documenti di esempio già ingeriti).
3. Login su Chainlit (`http://localhost:8080`) con `email|tenant_slug` come username, oppure chiamare direttamente `POST /api/v1/auth/login`.
4. Caricare documenti via `POST /api/v1/documents/upload` e attendere lo stato `ready` (`GET /api/v1/documents/{id}/status`).
5. Interrogare via chat (`/api/v1/chat/query` o `/chat/stream`, oppure direttamente dall'UI Chainlit).

---

## 15. Script di utilità

Tutti eseguibili da root con `python scripts/<nome>.py`.

- **`create_tenant.py`**: provisioning di un nuovo tenant (schema DB, collection Qdrant, utente admin opzionale). Argomenti: `--slug`, `--name`, `--plan` (`starter`/`pro`/`enterprise`), `--admin-email`, `--admin-password`.
- **`seed_demo_data.py`**: crea il tenant `demo-corp` con utente demo e due documenti di esempio (un contratto di fornitura e un'informativa privacy GDPR), già ingeriti tramite la pipeline reale — utile per provare rapidamente il sistema.
- **`benchmark_retrieval.py`**: esegue un piccolo dataset di domande di verifica (pensate per i documenti demo) e calcola per ciascuna un punteggio di copertura keyword, un punteggio di fedeltà (`check_faithfulness`) e uno score combinato; salva i risultati in JSON. Argomenti: `--tenant`, `--top-k`, `--output`. Va eseguito dopo `seed_demo_data.py`.

---

## 16. Test

- **`tests/conftest.py`**: fixture condivise — app FastAPI in-process (`httpx.AsyncClient` + `ASGITransport`, nessun server reale), contesto tenant fittizio, chunk di esempio.
- **`tests/integration/test_health.py`**: verifica `/health` (200, pubblico) e `/ready` (200/503, con dettaglio connettività Redis/SQL Server/Qdrant).
- **`tests/unit/test_chunker.py`**: pulizia testo (rimozione null byte, numeri di pagina, collasso newline) e chunking (dimensione, overlap, indici progressivi, ereditarietà metadati); costruzione contesto RAG.
- **`tests/unit/test_security.py`**: hashing password (bcrypt, salt randomico), creazione/validazione JWT (inclusa scadenza), generazione/verifica API key.

Esecuzione: `pytest` (marker disponibili: `unit`, `integration`, `e2e`, `slow`).

---

## 17. Problemi noti e codice legacy

### 17.1 File `OLD*` — codice morto, completamente vuoti (0 byte)
Tutti i file con prefisso `OLD` nel repository sono **file vuoti** senza alcun riferimento/import nel resto del codebase (verificato con grep esaustivo). Sono relitti di refactoring, sicuri da rimuovere:

```
app/api/middleware/OLDauth.py
app/schemas/OLDauth.py
app/schemas/OLDtenant.py
app/db/models/OLDtenant.py
app/db/repositories/OLDtenant_repo.py
app/rag/ingestion/OLDembedder.py
app/rag/retrieval/OLDdense.py
app/rag/retrieval/OLDsparse.py
app/rag/retrieval/OLDhybrid.py
app/rag/retrieval/OLDmmr.py
app/rag/retrieval/OLDreranker.py
app/rag/retrieval/OLDfilters.py
app/rag/generation/OLDstreaming.py
app/rag/agents/OLDrag_agent.py
app/rag/agents/OLDsql_agent.py
app/rag/agents/tools/OLDcalculator_tool.py
app/rag/agents/tools/OLDdate_tool.py
app/rag/agents/tools/OLDsearch_tool.py
docker/OLDqdrant.yaml
docker/OLDredis.yaml
docker/OLDsqlserver.yaml
```
I tre file `docker/OLD*.yaml` in particolare andrebbero rimossi con priorità: contengono configurazioni insicure (es. password SQL Server in chiaro, Redis senza password) che potrebbero essere avviate per errore.

### 17.2 Funzionalità implementate ma non raggiungibili a runtime
- **Grafo LangGraph** (`app/rag/graph/`), **router multi-agente** (`router_agent.py`) e **ricerca web** (`web_agent.py`): codice completo e funzionante ma mai invocato da alcuna route/servizio attivo (vedi §8).
- **Citazioni strutturate** (`app/rag/generation/citations.py`): mai chiamato, le fonti restituite sono solo i chunk recuperati.
- **Memoria a lungo termine** (`app/rag/memory/long_term.py`): mai istanziata, disabilitata di default, e comunque non collegata al prompt finale anche se abilitata.

### 17.3 Bug noto — rate limiting inefficace
In `main.py`, l'ordine di registrazione dei middleware (`Logging → Tenant → RateLimit`) combinato con la semantica LIFO di Starlette fa sì che `RateLimitMiddleware` venga eseguito **prima** di `TenantMiddleware`. Di conseguenza legge sempre `request.state.tenant_id`/`user_id` non ancora valorizzati (`None`) e il rate limiting a livello di middleware **non viene mai applicato**. Correzione: invertire l'ordine di `add_middleware` (registrare `RateLimitMiddleware` prima di `TenantMiddleware` nel codice) oppure far leggere al middleware l'header `Authorization` direttamente.

### 17.4 Altre incongruenze minori
- Duplicazione del modello SPLADE (caricato sia in `app/core/embeddings.py` sia in `app/rag/retrieval/retriever.py`, due istanze indipendenti in memoria).
- ID dei punti Qdrant generati con `uuid4()` casuale: re-ingerire lo stesso documento crea duplicati invece di sovrascrivere.
- `collection_id` non ha un payload index dedicato in Qdrant (a differenza di `tenant_id`/`document_id`/`doc_type`).
- Versione di Chainlit disallineata tra `chainlit_app/requirements.txt` (`<2.0.0`) e `requirements-dev.txt` (`2.11.1`).
- Doppio parsing del JWT per ogni richiesta (una volta nel middleware, una volta nella dependency `get_current_tenant`).
- Autorizzazione per ruolo incoerente tra route (vedi §4.3).
