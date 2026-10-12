# Conversor Escalável de Vídeo, Áudio e Imagem

Sistema distribuído de conversão de mídia com **processamento assíncrono**. O usuário envia um arquivo por uma interface web, escolhe o formato de destino e recebe na hora um `jobId`. A conversão acontece em segundo plano, por workers independentes que consomem uma fila no RabbitMQ, e o link do arquivo convertido chega por e-mail.

Projeto da disciplina [nome da disciplina] — [seu nome] ([curso], [instituição]).

## Sumário

- [Arquitetura](#arquitetura)
- [Tecnologias](#tecnologias)
- [Estrutura do repositório](#estrutura-do-repositório)
- [Como executar](#como-executar)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Buckets do object storage](#buckets-do-object-storage)
- [Como escalar os workers](#como-escalar-os-workers)
- [API](#api)
- [Contrato das mensagens](#contrato-das-mensagens)
- [Garantias de entrega e resiliência](#garantias-de-entrega-e-resiliência)
- [Como testar](#como-testar)
- [Evidência de escalabilidade](#evidência-de-escalabilidade)
- [Decisão: SeaweedFS no lugar do MinIO](#decisão-seaweedfs-no-lugar-do-minio)
- [Limitações conhecidas](#limitações-conhecidas)
- [Solução de problemas](#solução-de-problemas)

## Arquitetura

```
┌──────────┐  HTTP   ┌───────────────┐  (1) PUT origem   ┌──────────────┐
│ Frontend │ ──────► │ API (producer)│ ────────────────► │ SeaweedFS    │
│          │ ◄─jobId─│               │                   │ (S3)         │
└──────────┘         └───────┬───────┘                   │ uploads/     │
                             │ (2) publica               │ converted/   │
                             ▼                           └──────▲───────┘
                     ┌───────────────┐                          │
                     │   RabbitMQ    │   (3) consome            │ (4) baixa origem
                     │ fila conversao│ ──────────┐              │ (5) grava resultado
                     └───────────────┘           ▼              │ (6) remove origem
                             ▲            ┌─────────────────────┴──┐
                             │            │ Worker 1 .. Worker N   │
                             │            │ FFmpeg / Pillow        │
                             │            └─────────┬──────────────┘
                             │                      │ (7) evento de conclusão
                             │                      ▼
                             │            ┌───────────────┐   SMTP   ┌─────────┐
                             └────────────│ Notifier      │ ───────► │ Mailpit │
                                 fila     │ (e-mail)      │          └─────────┘
                              notificacoes└───────────────┘
```

O estado dos jobs fica no **Redis**. O binário do arquivo **nunca** trafega pela fila: a mensagem leva só metadados e a referência ao objeto no storage.

| Componente | Responsabilidade |
|---|---|
| `frontend` | Formulário de upload, escolha do formato, e-mail e acompanhamento do status (consulta `/jobs/{id}` a cada 2 s). |
| `api` | Valida o tipo de origem, grava o arquivo em `uploads`, registra o job como `PENDENTE`, publica a mensagem e responde com o `jobId`. Não converte nada. |
| `rabbitmq` | Armazena e distribui os pedidos entre os workers (competing consumers). |
| `worker` | Baixa a origem, converte (FFmpeg para vídeo/áudio, Pillow para imagem), grava o resultado em `converted`, gera o link, remove a origem, atualiza o status e publica o evento de conclusão. Pode rodar em N instâncias. |
| `notifier` | Segundo consumidor: escuta o evento de conclusão e envia o e-mail. Mantém a conversão desacoplada do envio. |
| `seaweedfs` | Object storage compatível com S3. |
| `redis` | Estado dos jobs (`PENDENTE`, `PROCESSANDO`, `CONCLUIDO`, `ERRO`). |
| `mailpit` | Servidor SMTP de desenvolvimento, com interface web para ver os e-mails. |

API e workers não se conhecem: a única interface entre eles é o contrato da mensagem.

## Tecnologias

- Python 3.12, FastAPI, Uvicorn
- RabbitMQ (cliente `pika`)
- SeaweedFS com API S3 (cliente `boto3`)
- Redis (cliente `redis-py`)
- FFmpeg (vídeo e áudio) e Pillow (imagem)
- Mailpit (SMTP), Nginx (frontend estático)
- Docker e Docker Compose

## Estrutura do repositório

```
.
├── docker-compose.yml
├── .env
├── common/                 # código compartilhado por api, worker e notifier
│   ├── job_store.py        # estado dos jobs no Redis
│   ├── object_store.py     # acesso ao storage S3 (boto3) e URLs pré-assinadas
│   └── queue_client.py     # conexão e topologia do RabbitMQ (filas, DLX, DLQ)
├── api/                    # producer (FastAPI)
├── worker/                 # consumer de conversão
│   └── app/converters/     # video.py, audio.py, image.py
├── notifier/               # consumer de notificação (e-mail)
├── frontend/               # HTML + JS estático
└── teste_carga.py          # script de teste de escalabilidade
```

`api`, `worker` e `notifier` são construídos a partir da **raiz** do projeto (`context: .` no Compose), para que cada imagem possa copiar a pasta `common/`.

## Como executar

**Pré-requisitos:** Docker Desktop (ou Docker Engine com o plugin Compose) em execução. Não é preciso instalar Python nem FFmpeg na máquina.

```bash
git clone <url-do-repositorio>
cd <pasta-do-projeto>
docker compose up --build
```

Esse único comando sobe todo o ambiente: broker, storage, Redis, servidor de e-mail, API, worker, notifier e frontend. Os buckets são criados automaticamente na inicialização.

| Serviço | Endereço |
|---|---|
| Frontend | http://localhost:8080 |
| API (documentação interativa) | http://localhost:8000/docs |
| RabbitMQ (painel) | http://localhost:15672 (usuário `guest`, senha `guest`) |
| Mailpit (e-mails enviados) | http://localhost:8025 |
| SeaweedFS (endpoint S3) | http://localhost:8333 |

Para parar tudo: `docker compose down`. Para parar e apagar os dados do storage: `docker compose down -v`.

## Variáveis de ambiente

Definidas no arquivo `.env` na raiz e lidas por `api`, `worker` e `notifier`.

| Variável | Valor padrão | Descrição |
|---|---|---|
| `RABBITMQ_HOST` | `rabbitmq` | Host do broker (nome do serviço no Compose). |
| `RABBITMQ_USER` / `RABBITMQ_PASS` | `guest` / `guest` | Credenciais do RabbitMQ. |
| `S3_ENDPOINT` | `http://seaweedfs:8333` | Endereço do storage **dentro** da rede do Docker (usado por api e worker). |
| `S3_PUBLIC_ENDPOINT` | `http://localhost:8333` | Endereço do storage visto pelo **navegador**. É nele que a URL pré-assinada do e-mail é gerada. |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | `dummy` / `dummy` | Credenciais exigidas pelo `boto3`. O SeaweedFS está em acesso aberto, então não são validadas. |
| `BUCKET_UPLOADS` | `uploads` | Bucket dos arquivos de origem (temporários). |
| `BUCKET_CONVERTED` | `converted` | Bucket dos resultados. |
| `PRESIGNED_URL_EXPIRES` | `86400` | Validade do link do arquivo convertido, em segundos (24 h). |
| `REDIS_HOST` | `redis` | Host do Redis. |
| `SMTP_HOST` / `SMTP_PORT` | `mailpit` / `1025` | Servidor SMTP. |
| `SMTP_FROM` | `conversor@exemplo.com` | Remetente dos e-mails. |
| `MAX_ATTEMPTS` | `3` | Número máximo de tentativas de conversão antes de enviar à DLQ. |

## Buckets do object storage

Não há passo manual. `common/object_store.py` expõe `ensure_buckets()`, chamada na inicialização da API e do worker, que cria `uploads` e `converted` se ainda não existirem (e tenta de novo caso o storage ainda esteja subindo).

- `uploads`: arquivos de origem. Cada objeto é removido após a conversão bem-sucedida e preservado se a conversão falhar de vez.
- `converted`: arquivos resultantes. O acesso é feito por **URL pré-assinada** com validade definida em `PRESIGNED_URL_EXPIRES`.

Para listar o conteúdo de um bucket, sem instalar nada além do Docker:

```bash
docker compose exec worker python -c "from common.object_store import client; print([o['Key'] for o in client.list_objects_v2(Bucket='uploads').get('Contents', [])])"
docker compose exec worker python -c "from common.object_store import client; print([o['Key'] for o in client.list_objects_v2(Bucket='converted').get('Contents', [])])"
```

## Como escalar os workers

O número de workers é escolhido na hora de subir, sem alterar código:

```bash
# 3 workers
docker compose up -d --scale worker=3 --no-recreate

# voltar para 1
docker compose up -d --scale worker=1
```

Cada worker consome uma mensagem por vez (`prefetch_count=1`). A distribuição do trabalho é feita pelo RabbitMQ, que entrega cada mensagem a um único consumidor. Por isso o serviço `worker` não publica portas no Compose (várias réplicas não podem disputar a mesma porta).

No serviço `worker` do `docker-compose.yml`, `cpus: 1` limita cada instância a um núcleo, para que o ganho de throughput com mais workers seja visível mesmo com o FFmpeg usando várias threads.

## API

### `POST /jobs`

Recebe `multipart/form-data` com os campos:

| Campo | Descrição |
|---|---|
| `file` | Arquivo de origem. Extensões aceitas: `mp4`, `avi`, `mov` (vídeo); `mp3`, `wav` (áudio); `png`, `jpg`, `jpeg` (imagem). |
| `target_format` | Formato de destino (ex.: `mp4`, `avi`, `mp3`, `jpg`). |
| `email` | E-mail que receberá a notificação. |

Resposta imediata, sem esperar a conversão:

```json
{ "jobId": "9f2c1a84-3b77-4e5a-9d21-6c0a8f4b1e30" }
```

Extensão de origem não suportada retorna `400`.

### `GET /jobs/{jobId}`

Retorna o registro do job. O campo `status` assume `PENDENTE`, `PROCESSANDO`, `CONCLUIDO` ou `ERRO`. Quando concluído, inclui `resultUrl` (link pré-assinado do arquivo convertido); em caso de falha definitiva, inclui `error`. Job inexistente retorna `404`.

## Contrato das mensagens

### Fila `conversao` (API → workers)

Só metadados e a referência ao arquivo de origem:

```json
{
  "jobId": "9f2c1a84-3b77-4e5a-9d21-6c0a8f4b1e30",
  "sourceObject": "9f2c1a84-3b77-4e5a-9d21-6c0a8f4b1e30.mov",
  "sourceType": "video",
  "sourceFormat": "mov",
  "targetFormat": "mp4",
  "notifyEmail": "aluno@exemplo.com",
  "requestedAt": "2026-10-12T18:22:05+00:00",
  "attempt": 1
}
```

`sourceObject` é o nome do objeto no bucket `uploads` (o nome do bucket vem da configuração, não da mensagem). O binário **nunca** vai na fila: isso mantém a mensagem pequena e evita o limite de tamanho de mensagens do broker, além de não duplicar arquivos grandes entre API, broker e workers.

### Fila `notificacoes` (worker → notifier)

Evento de conclusão:

```json
{
  "jobId": "9f2c1a84-3b77-4e5a-9d21-6c0a8f4b1e30",
  "status": "CONCLUIDO",
  "resultUrl": "http://localhost:8333/converted/9f2c1a84-....mp4?X-Amz-...",
  "notifyEmail": "aluno@exemplo.com"
}
```

Em caso de falha definitiva, `status` é `ERRO` e o evento traz `error` no lugar de `resultUrl`.

## Garantias de entrega e resiliência

**Por que RabbitMQ.** O problema é distribuir tarefas independentes entre um número variável de workers. O RabbitMQ resolve isso nativamente com uma fila e consumidores competindo por ela, com confirmação por mensagem. Kafka resolveria com partições e consumer groups, mas o paralelismo ficaria limitado ao número de partições e traria mais complexidade operacional sem ganho para este caso, que não precisa de reprocessamento histórico nem de log de eventos.

**Confirmação manual (ack).** O worker só confirma a mensagem depois de concluir todo o trabalho: conversão, gravação do resultado, remoção da origem, atualização do status e publicação do evento. Se um worker morrer no meio, a conexão dele cai, o broker recoloca a mensagem não confirmada na fila e outro worker a reprocessa do início. Nenhuma mensagem é perdida.

**Retentativas e Dead Letter Queue.** Se a conversão lança erro, o worker republica a mensagem com `attempt + 1`. Ao atingir `MAX_ATTEMPTS`, o job é marcado como `ERRO`, um evento de falha é publicado e a mensagem é rejeitada sem reenfileirar (`nack`, `requeue=False`), indo para a fila `conversao.dlq` por meio do exchange `conversao.dlx`. O arquivo de origem é preservado em `uploads` para diagnóstico.

**Idempotência pelo `jobId`.** O RabbitMQ garante entrega *pelo menos uma vez*, então a mesma mensagem pode chegar duas vezes. Antes de processar, o worker consulta o status do job: se já estiver `CONCLUIDO`, apenas confirma a mensagem e ignora. Assim, uma reentrega não gera arquivo duplicado nem segundo e-mail.

**Ordem da limpeza.** O arquivo de origem só é removido depois de o resultado ter sido gravado com sucesso, nunca antes.

**Desacoplamento do e-mail.** O worker publica o evento e segue; quem envia o e-mail é o `notifier`. Uma falha no SMTP não afeta a conversão.

## Como testar

Com o ambiente de pé (`docker compose up --build`):

| Teste | Como fazer | Resultado esperado |
|---|---|---|
| Conversão dos 3 tipos | Enviar `png → jpg`, `wav → mp3` e `mp4 → avi` em http://localhost:8080 | Status chega a `CONCLUIDO`; e-mail no Mailpit com link que abre o arquivo |
| Ciclo de vida dos arquivos | Listar `uploads` e `converted` (comando na seção de buckets) antes e depois | `uploads` vazio e `converted` com `<jobId>.<formato>` |
| Mensagem na fila | `docker compose stop worker`, enviar um arquivo, ver a fila `conversao` no RabbitMQ (*Get messages* com *Nack, requeue true*), depois `docker compose start worker` | Mensagem visível com o JSON do contrato; ao subir o worker, ela é consumida |
| Escalabilidade | Rodar `python teste_carga.py` com 1 worker e depois com 3 | Tempo total menor com 3 workers; vários jobs em `PROCESSANDO` ao mesmo tempo |
| Falha de worker | Com 2 ou mais workers, enviar um vídeo grande e rodar `docker kill <container-do-worker>` durante a conversão | Outro worker processa o mesmo `jobId`; o job conclui e só um e-mail é enviado |
| Idempotência | No painel do RabbitMQ, publicar de novo na fila `conversao` o JSON de um job já concluído | Nada é reprocessado e nenhum novo e-mail chega |
| Dead Letter Queue | Enviar um arquivo inválido com extensão aceita (ex.: texto renomeado para `.png`) | Após 3 tentativas, job em `ERRO`, mensagem em `conversao.dlq` e origem preservada em `uploads` |

Os logs dos workers mostram o ciclo de cada job, com o `jobId` e o nome da instância:

```bash
docker compose logs -f worker
```

`teste_carga.py` precisa de `pip install requests` na máquina e do caminho do vídeo ajustado em `FILE_PATH`. Ele envia `N` arquivos de uma vez e cronometra até todos os jobs terminarem.

## Evidência de escalabilidade

Mesmo arquivo e mesmo lote de jobs nas duas rodadas, cada worker limitado a 1 CPU.

| Workers | Jobs | Tempo total até todos concluírem | Ganho |
|---|---|---|---|
| 1 | [N] | [__ s] | 1,0x |
| 3 | [N] | [__ s] | [__x] |

Observações: [comente aqui o resultado, por exemplo se o ganho ficou abaixo do ideal por causa da CPU compartilhada entre os containers, do disco e do FFmpeg multi-thread].

## Decisão: SeaweedFS no lugar do MinIO

A proposta cita o MinIO como object storage compatível com S3. Em 2026 a MinIO Inc. retirou as imagens oficiais da edição community do Docker Hub (e o `quay.io` passou a exigir autenticação), o que impede subir o ambiente com um único `docker compose up` de forma gratuita. O projeto usa o **SeaweedFS**, que expõe a API S3, e o acesso é feito com `boto3` (SDK padrão da AWS), sem nenhum código específico de fornecedor. Trocar de storage, inclusive voltar ao MinIO, exige alterar apenas o serviço no `docker-compose.yml` e as variáveis `S3_*` do `.env`.

O link público do arquivo convertido é uma **URL pré-assinada** (uma das duas opções previstas no RF04), o que evita depender de como cada storage implementa políticas de bucket público.

## Limitações conhecidas

O que eu faria diferente em produção:

- **Storage sem autenticação.** O SeaweedFS roda em acesso aberto. Em produção: credenciais reais, rede restrita e HTTPS.
- **Worker síncrono.** A conversão roda dentro da função do consumidor, e o `pika` (`BlockingConnection`) não responde ao heartbeat do broker nesse intervalo. Por isso o heartbeat está alto (`600`), e conversões acima desse tempo derrubariam a conexão. A solução é converter em outra thread e confirmar a mensagem com `add_callback_threadsafe`.
- **Idempotência parcial.** A checagem protege contra duplicatas que chegam *depois* da conclusão. Duas cópias processadas ao mesmo tempo (job ainda em `PROCESSANDO`) não são impedidas. Melhoria: lock por `jobId` no Redis antes de converter.
- **Retentativa imediata.** A republicação com `attempt + 1` não tem espera entre tentativas. Em produção: backoff exponencial, por exemplo com filas de retry com TTL.
- **Estado em memória.** O Redis não usa volume nem persistência, então o histórico dos jobs se perde se ele reiniciar. Em produção: banco relacional ou Redis com persistência.
- **Upload carregado em memória.** A API lê o arquivo inteiro antes de gravar no storage. Para arquivos muito grandes, o ideal é fazer streaming ou upload multipart direto ao storage.
- **Validação do formato de destino.** A API valida a extensão de origem, mas não verifica se o formato de destino é compatível com o tipo (por exemplo, `png → mp3` só falha no worker).
- **Objetos convertidos sem expiração.** Os arquivos em `converted` permanecem até serem removidos manualmente, mesmo depois de o link expirar.
- **Frontend com polling.** O status é consultado a cada 2 s; não há barra de progresso em tempo real (WebSocket/SSE).
- **Sem testes automatizados** do publisher e do consumer.

## Solução de problemas

- **`failed to connect to the docker API`:** o Docker Desktop não está aberto. Inicie-o e espere o status "running".
- **Erro de build com `non-printable ASCII characters`:** o caminho da pasta do projeto tem acentos (bug conhecido do BuildKit no Windows). Mova o projeto para um caminho sem acentos.
- **O link do e-mail não abre:** confira se `S3_PUBLIC_ENDPOINT` aponta para um endereço acessível pelo navegador (`http://localhost:8333`) e recrie os serviços depois de alterar o `.env`.
- **O frontend não mostra o `jobId`:** abra o console do navegador (F12). Se aparecer erro de CORS, confirme que a API libera a origem `http://localhost:8080`.
- **Job parado em `PENDENTE`:** nenhum worker está consumindo. Veja `docker compose ps` e `docker compose logs worker`.

## Autor(es)

[Seu nome] — [e-mail ou usuário do GitHub]
