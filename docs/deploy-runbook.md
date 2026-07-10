# Runbook de despliegue — Turbolog en GCP Docker Swarm

Este runbook describe todo lo que necesita un administrador para desplegar
Turbolog en el cluster Docker Swarm de GCP mediante el pipeline de GitHub
Actions: configuración inicial de GCP y GitHub, primer despliegue, rotación de
secretos, rollback y la disciplina de migraciones aditivas.

> **Convenciones de este documento**
> - Proyecto GCP: `dockerswarm-491114`. Zona: `southamerica-west1-a`.
>   Región del Artifact Registry: `southamerica-west1`.
> - Los bloques de código, comandos, identificadores, nombres de secretos y
>   roles de IAM se mantienen en su forma original (inglés/ASCII).
> - `<valor-de-ejemplo>` indica un valor que el operador debe sustituir.
> - Todos los comandos `gcloud compute ssh/scp` hacia los nodos usan
>   `--tunnel-through-iap` (los nodos no tienen IP pública; ver el tutorial de
>   acceso en este mismo directorio).

---

## Tabla de contenidos

1. [Prerrequisitos de GCP (one-time)](#1-prerrequisitos-de-gcp-one-time)
   - [1.1 Workload Identity Federation](#11-workload-identity-federation)
   - [1.2 Service account de deploy (rol completo)](#12-service-account-de-deploy-rol-completo)
   - [1.3 OS Login y firewall IAP](#13-os-login-y-firewall-iap)
   - [1.4 Artifact Registry](#14-artifact-registry)
   - [1.5 Cloud SQL](#15-cloud-sql)
   - [1.6 Cloudflare Tunnel](#16-cloudflare-tunnel)
   - [1.7 Google OAuth Console](#17-google-oauth-console)
2. [Secrets y variables de GitHub](#2-secrets-y-variables-de-github)
3. [Bootstrap de secrets de Swarm](#3-bootstrap-de-secrets-de-swarm)
4. [Primer despliegue](#4-primer-despliegue)
5. [Rotación de secretos](#5-rotación-de-secretos)
6. [Rollback](#6-rollback)
7. [Disciplina de migraciones aditivas](#7-disciplina-de-migraciones-aditivas)
8. [Orden de merge de PRs](#8-orden-de-merge-de-prs)

---

## 1. Prerrequisitos de GCP (one-time)

Esta sección se ejecuta una única vez. Provisionar las VMs del swarm, el repo
de Artifact Registry, la instancia de Cloud SQL, el pool de WIF y el tunnel de
Cloudflare **es prerequisito** de este runbook (se asume que el swarm ya
existe). Lo que sigue son los pasos exactos para conectar el pipeline al swarm.

### 1.1 Workload Identity Federation

GitHub Actions se autentica en GCP sin claves de larga duración mediante
Workload Identity Federation (WIF). Se crea un pool, un provider OIDC apuntando
al issuer de GitHub, y un binding que permite impersonar la service account de
deploy únicamente desde `main` del repo.

```bash
# Variables (sustituir)
PROJECT_ID=dockerswarm-491114
GITHUB_OWNER=<org-o-usuario-de-github>     # ej. mi-organizacion
GITHUB_REPO=turbolog
POOL_ID=github-pool
PROVIDER_ID=github-provider
DEPLOY_SA=turbolog-deploy@${PROJECT_ID}.iam.gserviceaccount.com

# 1. Crear el pool
gcloud iam workload-identity-pools create ${POOL_ID} \
  --location=global \
  --description="Pool para GitHub Actions"

# 2. Crear el provider OIDC apuntando a GitHub, con attribute mapping y
#    condition que restringe al owner/repo y a la rama main.
gcloud iam workload-identity-pools providers create-oidc ${PROVIDER_ID} \
  --workload-identity-pool=${POOL_ID} \
  --location=global \
  --issuer="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner,attribute.ref=assertion.ref" \
  --attribute-condition="attribute.repository=='${GITHUB_OWNER}/${GITHUB_REPO}' && attribute.ref=='refs/heads/main'"
```

El binding que permite a GitHub impersonar la SA se crea en [1.2](#12-service-account-de-deploy-rol-completo)
junto con el rol `roles/iam.workloadIdentityUser`.

> **Canonical identifier del provider** (se guarda como GitHub secret
> `GCP_WIF_PROVIDER`):
> ```
> projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github-pool/providers/github-provider
> ```
> Para obtener el `<PROJECT_NUMBER>`:
> ```bash
> gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)'
> ```

### 1.2 Service account de deploy (rol completo)

Una única service account (`turbolog-deploy`) concentra todos los permisos que
necesitan el pipeline CI y el auth-proxy de Cloud SQL. Recibe el binding de WIF
(paso anterior), los roles operativos para build/deploy, y el rol de cliente de
Cloud SQL que consume el auth-proxy vía su clave JSON (ver [1.5](#15-cloud-sql)).

```bash
PROJECT_ID=dockerswarm-491114
DEPLOY_SA=turbolog-deploy@${PROJECT_ID}.iam.gserviceaccount.com
POOL_ID=github-pool
PROVIDER_ID=github-provider
GITHUB_OWNER=<org-o-usuario-de-github>
GITHUB_REPO=turbolog
WIF_PROVIDER="projects/$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"

# 1. Crear la service account
gcloud iam service-accounts create turbolog-deploy \
  --display-name="Turbolog deploy (CI + auth-proxy)"

# 2. Roles operativos del pipeline
gcloud projects add-iam-policy-binding ${PROJECT_ID} --member="serviceAccount:${DEPLOY_SA}" --role="roles/artifactregistry.writer"
gcloud projects add-iam-policy-binding ${PROJECT_ID} --member="serviceAccount:${DEPLOY_SA}" --role="roles/compute.osAdminLogin"
gcloud projects add-iam-policy-binding ${PROJECT_ID} --member="serviceAccount:${DEPLOY_SA}" --role="roles/iap.tunnelResourceAccessor"
gcloud projects add-iam-policy-binding ${PROJECT_ID} --member="serviceAccount:${DEPLOY_SA}" --role="roles/iam.serviceAccountUser"

# 3. Rol del auth-proxy de Cloud SQL (la clave JSON de esta misma SA es la que
#    monta el servicio auth-proxy; ver 1.5).
gcloud projects add-iam-policy-binding ${PROJECT_ID} --member="serviceAccount:${DEPLOY_SA}" --role="roles/cloudsql.client"

# 4. Binding de WIF: permite a GitHub impersonar esta SA solo desde main
gcloud iam service-accounts add-iam-policy-binding ${DEPLOY_SA} \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"
```

> **Set de roles completo de `turbolog-deploy`** (referencia):
> `roles/iam.workloadIdentityUser`, `roles/artifactregistry.writer`,
> `roles/compute.osAdminLogin`, `roles/iap.tunnelResourceAccessor`,
> `roles/iam.serviceAccountUser`, `roles/cloudsql.client`.
>
> El correo de esta SA se guarda como GitHub secret `GCP_SERVICE_ACCOUNT`.

### 1.3 OS Login y firewall IAP

Los nodos del swarm no tienen IP pública: el pipeline llega por un túnel IAP y
SSH no interactivo vía OS Login. Se requiere:

1. **OS Login habilitado** a nivel de proyecto (o instancia) con el metadata
   `enable-oslogin=TRUE`.
2. **Regla de firewall IAP** que permita el CIDR de IAP (`35.235.240.0/20`) al
   puerto 22 tcp en los nodos.

```bash
PROJECT_ID=dockerswarm-491114
NETWORK=<nombre-de-la-vpc-del-swarm>   # ej. default

# 1. Habilitar OS Login a nivel de proyecto
gcloud compute project-info add-metadata \
  --metadata=enable-oslogin=TRUE

# 2. Regla de firewall para IAP (tcp:22 desde el CIDR de IAP)
gcloud compute firewall-rules create allow-iap-ssh \
  --network=${NETWORK} \
  --action=ALLOW \
  --rules=tcp:22 \
  --source-ranges=35.235.240.0/20 \
  --description="Permitir SSH desde Identity-Aware Proxy a los nodos"

# 3. Verificar
gcloud compute firewall-rules describe allow-iap-ssh --format='table(name,sourceRanges.list():label=SRC_RANGE,allowed[].map().firewall_rule().list():label=ALLOW)'
```

> **Clave SSH no interactiva de CI**: el pipeline genera una clave efímera en
> cada run y la registra con `gcloud compute os-login ssh-keys add` (ver
> `.github/workflows/deploy.yml`, paso "Generate and register CI SSH key"). No
> hace falta pre-seedar una clave de larga durión; OS Login acepta la clave
> efímera mientras la SA tenga `roles/compute.osAdminLogin`. Verifica el perfil
> con:
> ```bash
> gcloud compute os-login describe-profile --format='name'
> ```

### 1.4 Artifact Registry

El pipeline construye la imagen y la pushea con tag SHA al Artifact Registry.
Los nodos del swarm necesitan poder hacer pull.

```bash
PROJECT_ID=dockerswarm-491114
GAR_REGION=southamerica-west1
GAR_REPO=turbolog

# 1. Crear el repositorio Docker
gcloud artifacts repositories create ${GAR_REPO} \
  --repository-format=docker \
  --location=${GAR_REGION} \
  --description="Imagenes de Turbolog"

# 2. Otorgar roles/artifactregistry.reader a la SA de los NODOS del swarm
#    (la SA que usan las VMs GCE, NO la SA de deploy). Los nodos la necesitan
#    para hacer docker pull de cada SHA nuevo sin login por deploy.
NODES_SA=<sa-de-los-nodos>@${PROJECT_ID}.iam.gserviceaccount.com
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${NODES_SA}" \
  --role="roles/artifactregistry.reader"
```

> **Access scope `cloud-platform` en los nodos (HARD blocker)**: el access scope
> se fija al CREAR la VM y no se puede cambiar en caliente. Si algún nodo no
> tiene `cloud-platform`, el pipeline falla en el job `precondition-check` con
> instrucciones de recrear la VM. Verifica antes del primer deploy:
> ```bash
> gcloud compute instances describe <nombre-del-nodo> \
>   --zone=southamerica-west1-a \
>   --format='table(name,serviceAccounts[0].email,scopes.list():label=SCOPES)'
> ```
> Si `cloud-platform` no aparece, **recrea la VM** con
> `--scopes=cloud-platform` (no hay otra vía).
>
> **Retención de imágenes**: configura una política de retención (o límite de
> cleanup) en el repositorio que conserve al menos las N imágenes anteriores
> necesarias para rollback. El pipeline hace rollback por SHA, no usa `:latest`.

### 1.5 Cloud SQL

Backend, scheduler y la migración one-shot se conectan a Cloud SQL a través de
un servicio `auth-proxy` compartido sobre el overlay (DNS `auth-proxy:5432`). El
auth-proxy usa la **clave JSON de la SA de deploy** (`roles/cloudsql.client`,
otorgado en [1.2](#12-service-account-de-deploy-rol-completo)).

```bash
PROJECT_ID=dockerswarm-491114
DB_INSTANCE=turbolog-db
DB_REGION=southamerica-west1
DB_VERSION=POSTGRES_16
DEPLOY_SA=turbolog-deploy@${PROJECT_ID}.iam.gserviceaccount.com

# 1. Crear la instancia Postgres (con backups automáticos + PITR)
gcloud sql instances create ${DB_INSTANCE} \
  --database-version=${DB_VERSION} \
  --region=${DB_REGION} \
  --availability-type=REGIONAL \
  --backup-start-time=03:00 \
  --enable-point-in-time-recovery

# 2. Crear la base de datos y el usuario
gcloud sql databases create turbolog --instance=${DB_INSTANCE}
gcloud sql users create turbolog \
  --instance=${DB_INSTANCE} \
  --password=<password-seguro>     # NO se commitea; va en el secret database_url

# 3. Connection name (se guarda como GitHub VARIABLE CLOUDSQL_CONNECTION)
CLOUDSQL_CONNECTION=$(gcloud sql instances describe ${DB_INSTANCE} --format='value(connectionName)')
echo "CLOUDSQL_CONNECTION=${CLOUDSQL_CONNECTION}"
# Formato esperado: dockerswarm-491114:southamerica-west1:turbolog-db

# 4. Crear la clave JSON de la SA de deploy -> se carga como Swarm secret
#    cloudsql_sa_key (la consume el servicio auth-proxy con --credentials-file)
gcloud iam service-accounts keys create cloudsql_sa_key.json \
  --iam-account=${DEPLOY_SA}
```

> **Backups + PITR son obligatorios**: el spec lo marca como precondition. Si la
> instancia ya existe, verifica:
> ```bash
> gcloud sql instances describe ${DB_INSTANCE} \
>   --format='table(name,settings.backupConfiguration.enabled,settings.backupConfiguration.pointInTimeRecoveryEnabled)'
> ```
>
> El archivo `cloudsql_sa_key.json` (generado en el paso 4) es el contenido del
> Swarm secret `cloudsql_sa_key_v1` (ver [sección 3](#3-bootstrap-de-secrets-de-swarm)).

### 1.6 Cloudflare Tunnel

El edge TLS corre como servicio `cloudflared` del stack, con un tunnel
remote-managed (dashboard). El token del tunnel es el Swarm secret
`cloudflare_token`; la regla de ingress apunta al backend por DNS del overlay.

Pasos en el dashboard de Cloudflare (Zero Trust → Networks → Tunnels):

1. Crear un tunnel remoto-managed y copiar su **token** (= contenido del Swarm
   secret `cloudflare_token_v1`).
2. Configurar la regla de ingress **canónica**:

   | Subdomain | Domain | Service |
   |---|---|---|
   | `<subdominio>` | `<dominio>` | `HTTP backend:8000` |

   Es decir, el hostname público mapea a `http://backend:8000` (DNS del
   overlay). Esta es la única regla de ingress que necesita el tunnel.

3. Configurar el **origin health check** del tunnel contra
   `/api/health/ready` (es el endpoint que hace la sanity query
   `SELECT 1 FROM alembic_version`).

> **`APP_URL` / `APP_DOMAIN`**: el dominio HTTPS público (ej.
> `https://turbolog.midominio.com`) se setea como `APP_URL` en el
> `docker-stack.yml.tmpl` (campo `environment`) y como GitHub VARIABLE
> `APP_DOMAIN`. Con `APP_URL=https://...`, las cookies de auth se emiten con el
> flag `Secure` automáticamente.
>
> **Imagen `cloudflared`**: el stack usa `cloudflare/cloudflared:latest` con un
> TODO para que el operador fije un tag con fecha (ej.
> `cloudflare/cloudflared:2026.7.1`) por reproducibilidad. Hacelo antes del
> primer deploy o apenas tengas uno estable.

### 1.7 Google OAuth Console

Antes del cutover de DNS, dar de alta el callback del dominio de Cloudflare como
URI de redirección autorizado en Google Cloud Console (APIs & Services →
Credentials → OAuth 2.0 Client ID):

```
https://<dominio-cloudflare>/api/auth/google/callback
```

Sin este URI autorizado, el login de Google fallará redirigiendo a `/no-access`
o mostrando `redirect_uri_mismatch` después del cutover.

---

## 2. Secrets y variables de GitHub

Configurar en **Settings → Secrets and variables → Actions** del repo.

### Secrets (sensibles, cifrados)

| Nombre | Descripción |
|---|---|
| `GCP_WIF_PROVIDER` | Identifier completo del provider de WIF (ver [1.1](#11-workload-identity-federation)). |
| `GCP_SERVICE_ACCOUNT` | Email de la SA de deploy `turbolog-deploy@dockerswarm-491114.iam.gserviceaccount.com`. |

### Variables (no sensibles, texto plano)

| Nombre | Valor de ejemplo | Descripción |
|---|---|---|
| `GCP_PROJECT_ID` | `dockerswarm-491114` | ID del proyecto GCP. |
| `GCP_ZONE` | `southamerica-west1-a` | Zona de los nodos del swarm. |
| `GAR_REGION` | `southamerica-west1` | Región del Artifact Registry. |
| `GAR_REPO` | `turbolog` | Nombre del repo Docker en GAR. |
| `SWARM_MANAGER_NODE` | `swarm-manager-1` | Nombre de la instancia GCE del manager. |
| `CLOUDSQL_CONNECTION` | `dockerswarm-491114:southamerica-west1:turbolog-db` | Connection name de Cloud SQL (ver [1.5](#15-cloud-sql)). |
| `APP_DOMAIN` | `turbolog.midominio.com` | Dominio público de Cloudflare (sin esquema); se usa en el smoke post-deploy. |

> **Por qué `GCP_WIF_PROVIDER` y `GCP_SERVICE_ACCOUNT` son secrets y el resto
> variables**: los dos primeros identifican la identidad que el pipeline
> impersona; el resto son configuración operativa no sensible (un project ID o
> un zone no son secretos).

---

## 3. Bootstrap de secrets de Swarm

Los 8 secrets genuinos viven como Docker Swarm secrets (archivos bajo
`/run/secrets`), NO como texto plano en la imagen ni en CI. Son `external: true`
en el stack, así que se crean a mano una única vez con sufijo `_v1`.

Desde un **manager del swarm** (conectado vía IAP):

```bash
# Copiar el script al manager y ejecutarlo (lee cada valor de forma segura)
gcloud compute scp scripts/create-secrets.sh <manager>:~/  --tunnel-through-iap --zone=southamerica-west1-a
gcloud compute ssh <manager> --tunnel-through-iap --zone=southamerica-west1-a -- "sh ~/create-secrets.sh"
```

El script crea los 8 secrets `*_v1`:

| Swarm secret | pydantic field (`target=`) | Origen del valor |
|---|---|---|
| `database_url_v1` | `database_url` | `postgresql+asyncpg://turbolog:<pass>@auth-proxy:5432/turbolog` |
| `google_client_secret_v1` | `google_client_secret` | Google OAuth client secret |
| `jwt_secret_v1` | `jwt_secret` | Random >= 32 chars (NO `dev-secret-change-me`) |
| `jira_api_token_v1` | `jira_api_token` | API token de JIRA Cloud |
| `llm_api_key_v1` | `llm_api_key` | API key del LLM (vacío es válido: feature deshabilitado) |
| `telegram_bot_token_v1` | `telegram_bot_token` | Token del bot de Telegram |
| `cloudsql_sa_key_v1` | `cloudsql_sa_key` | Contenido del `cloudsql_sa_key.json` generado en [1.5](#15-cloud-sql) |
| `cloudflare_token_v1` | `cloudflare_token` | Token del tunnel de Cloudflare |

Verificar:

```bash
gcloud compute ssh <manager> --tunnel-through-iap --zone=southamerica-west1-a \
  -- "docker secret ls | grep '_v1'"
```

> **`.env.production` es local-only**: si preparás los valores en un archivo
> `.env.production` para tu comodidad, ese archivo está gitignored (ver
> `.gitignore`) y **nunca** se commitea. El script `create-secrets.sh` lee los
> valores por prompt seguro; el `.env.production` es solo un helper del
> operador, no un input del pipeline.

---

## 4. Primer despliegue

El pipeline de `.github/workflows/deploy.yml` tiene UNA sola secuencia que
sirve para primer despliegue y para estado estable (no hay branch separado
"first-deploy"). Se dispara de dos formas:

- **Push a `main`**: dispara el pipeline completo (lint-test →
  additive-migration-gate → build-push → precondition-check → deploy).
- **`workflow_dispatch`** manual desde Actions → "deploy" → Run workflow (sin
  `image_tag` = build + deploy del HEAD de la rama).

### Secuencia unificada del job `deploy`

1. **WIF auth** + `setup-gcloud` + generación/registro de clave SSH efímera (OS
   Login).
2. **Render local del stack** con `envsubst` allow-listado (SOLO
   `${IMAGE_TAG}` y `${CLOUDSQL_CONNECTION}`):
   ```
   IMAGE_TAG=<sha> CLOUDSQL_CONNECTION=<conn> \
     envsubst '${IMAGE_TAG} ${CLOUDSQL_CONNECTION}' \
     < docker-stack.yml.tmpl > docker-stack.yml
   ```
   Nunca usar `envsubst` sin la allow-list posicional: sobre-sustituiría todo
   `${VAR}` y vaciaría los unset.
3. **`compute scp`** del `docker-stack.yml` al manager (vía IAP).
4. **`docker stack deploy -c ~/docker-stack.yml turbolog`** (idempotente):
   crea el overlay `turbolog-net` y levanta el servicio `auth-proxy`.
5. **Wait de readiness del auth-proxy** usando estado Swarm visible desde el
   host (`docker service ps turbolog_auth-proxy --filter desired-state=running`).
   El DNS del overlay (`auth-proxy`) y el puerto 9090 SOLO resuelven dentro de
   contenedores en `turbolog-net`; no uses `getent hosts auth-proxy` ni
   `curl auth-proxy:9090` desde el host del manager.
6. **Migración one-shot** como Swarm service `turbolog-migrate`
   (`-e RUN_MIGRATIONS=false --restart-condition=none
   --secret source=database_url_v1,target=database_url --network turbolog-net`
   + `uv run alembic upgrade head`). Se hace un pre-clean idempotente antes
   (`docker service rm turbolog-migrate || true`). El pipeline hace poll del
   task y **hard-gate** sobre exit code == 0.
7. **Roll de imagen**: `docker service update --image <sha> turbolog_backend`
   y `turbolog_scheduler`.
8. **Smoke post-deploy**: `GET /api/health/ready` espera 200;
   `GET /api/auth/me` espera **401 (no 5xx)** — un 5xx indica un problema de
   wiring de secret/DB que el fail-fast no atrapó.
9. **Cleanup incondicional** (`if: always()`): `docker service rm
   turbolog-migrate`, exit 0 o no, para que nunca quede un servicio stale que
   conflicte con el próximo deploy de recuperación.

### Ventana de flapping en el primer despliegue (esperado, auto-healing)

En el **primer** deploy, el backend arranca ANTES de que corra la migración
(paso 4 levanta el stack, paso 6 migra). El backend va a flapear
(restart loop) hasta que el esquema exista, porque `/api/health/ready` hace
`SELECT 1 FROM alembic_version` y esa tabla no existe hasta migrar.

Esto es **esperado y se auto-cura**:

- `RUN_MIGRATIONS=false` en el backend del stack → no compite con el one-shot.
- `_seed_admin_allowed_emails` tolera esquema ausente (no aborta el lifespan).
- En cuanto el one-shot corre (paso 6), el esquema aparece y el backend arranca
  sano en el siguiente restart (start_period de 30s + restart policy de Swarm).

Si pasados ~2-3 minutos del primer deploy el backend sigue flapeando después de
una migración exitosa, investigar logs del one-shot y del backend:
```bash
gcloud compute ssh <manager> --tunnel-through-iap --zone=southamerica-west1-a \
  -- "docker service logs turbolog_backend --tail 50"
```

---

## 5. Rotación de secretos

Los secrets de Swarm se rotan por **nombre versionado** (no se puede hacer
`docker secret rm` + `create` sobre uno en uso por un servicio). El alias
`target=<field>` es **obligatorio**: pydantic `secrets_dir` lee el archivo
nombrado por el FIELD (`/run/secrets/jwt_secret`), no por la versión
(`/run/secrets/jwt_secret_v2`). Sin `target=`, el archivo field-named desaparece
y pydantic cae al default inseguro (justo lo que `assert_prod_secrets` detecta).

Procedimiento (ejemplo rotando `jwt_secret`):

```bash
# 1. Crear la nueva versión del secret (en un manager)
gcloud compute ssh <manager> --tunnel-through-iap --zone=southamerica-west1-a \
  -- "printf '%s' '<nuevo-valor-seguro>' | docker secret create jwt_secret_v2 -"

# 2. Actualizar el servicio (aplicar a todos los servicios que lo montan).
#    El target= alias mantiene /run/secrets/jwt_secret apuntando al nuevo valor.
gcloud compute ssh <manager> --tunnel-through-iap --zone=southamerica-west1-a -- \
  "docker service update \
     --secret-rm jwt_secret_v1 \
     --secret-add source=jwt_secret_v2,target=jwt_secret \
     turbolog_backend"

# 3. Lo mismo para turbolog_scheduler (monta el mismo secret)
gcloud compute ssh <manager> --tunnel-through-iap --zone=southamerica-west1-a -- \
  "docker service update \
     --secret-rm jwt_secret_v1 \
     --secret-add source=jwt_secret_v2,target=jwt_secret \
     turbolog_scheduler"
```

> **No se necesita rebuild de imagen**. Swarm re-monta el secret y reinicia la
> tarea; pydantic lee el nuevo valor de `/run/secrets/<field>` al arranque.
>
> **Después de rotar, redeploy** (push a main o `workflow_dispatch`) para que el
> stack template siga apuntando a la versión vigente — o actualizá
> `docker-stack.yml.tmpl` para que la próxima corrida no revierta el
> `--secret-rm` (el template referencia `_v1`; si rotaste a `_v2`, actualizá el
> `source:` del secret correspondiente en el template a `_v2` antes del próximo
> deploy, sino el `docker stack deploy` re-montará `_v1`).

---

## 6. Rollback

### Rollback de imagen (automático, vía pipeline)

Desde Actions → "deploy" → Run workflow, setear `image_tag` al SHA anterior (los
7 chars del tag, ej. `f8552ca`). El pipeline saltea build-push y corre deploy
con ese tag (resuelve el tag desde `inputs.image_tag`). El job
`precondition-check` sí corre (un rollback también necesita pull y SSH).

```
image_tag: f8552ca
```

### Rollback de imagen (manual)

```bash
PREV_SHA=<sha-anterior>
IMAGE=southamerica-west1-docker.pkg.dev/dockerswarm-491114/turbolog/turbolog:${PREV_SHA}
gcloud compute ssh <manager> --tunnel-through-iap --zone=southamerica-west1-a -- \
  "docker service update --image ${IMAGE} turbolog_backend && \
   docker service update --image ${IMAGE} turbolog_scheduler"
```

> **`docker service update` no revierte secrets**: el rollback de imagen no toca
> los secrets Swarm. Si rotaste un secret y querés volver al valor anterior,
> repetí la rotación con las versiones invertidas (sección 5).
>
> **Alembic downgrade es MANUAL**: el pipeline NO ejecuta downgrade
> automáticamente. Si un deploy llevó una migración que hay que revertir,
> correr el downgrade a mano contra Cloud SQL (vía el auth-proxy o
> `gcloud sql connect`) con el comando alembic correspondiente. Por eso la
> disciplina de migraciones aditivas (sección 7) es dura: las migraciones
> aditivas son seguras bajo roll-forward/back sin downgrade.

---

## 7. Disciplina de migraciones aditivas

**Regla dura**: toda migración nueva (posterior al baseline `c1d2e3f4a5b6`,
que es el head actual del repo al momento del primer deploy) DEBE ser
**backward-compatible (aditiva)**. El pipeline tiene un job
`additive-migration-gate` con DOS checks que deben pasar:

1. **Static op-scan** (`scripts/check_migrations.py`, AUTHORITY para aditividad):
   escanea los cuerpos de `upgrade()` (SOLO upgrade, nunca downgrade) de las
   migraciones más nuevas que el baseline y rechaza:
   - `op.drop_table`, `op.drop_column`, `op.drop_index`
   - `op.alter_column(..., nullable=False)` (nullable → NOT NULL rompe filas
     existentes)
   - `op.create_primary_key`, `op.drop_constraint` de tipo primary/PK
   - `op.alter_column(..., type_=...)` (cambio de tipo de columna)
2. **Round-trip upgrade → downgrade → upgrade** sobre un contenedor Postgres 16
   sembrado con filas NULL (defense-in-depth: el op-scan vacío pasa con cero
   filas; el seed NULL expone un nullable → NOT NULL al re-upgradear).

El baseline `c1d2e3f4a5b6` **abuelo** todo lo existente (la cadena actual usa
`op.drop_*` en `upgrade()` y `downgrade()` — ej. `68c029c4286e` hace
`op.drop_table` en `upgrade()`). Sin grandfathering, un scan blanket
bloquearía todos los deploys.

### Escape hatch (type change explícito)

El op-scan no puede distinguir un narrow (`String(255)` → `String(50)`) de un
widen (`String(50)` → `String(255)`). Por eso rechaza TODO
`alter_column(type_=...)` salvo que el autor marque la línea:

```python
op.alter_column('tasks', 'title', type_=sa.String(500), nullable=False)  # additive: allow-type-change
```

Ese marker es una justificación visible para el reviewer. Los widen seguros lo
usan; los narrow quedan bloqueados por default.

### Cambios no aditivos = paso manual de ops

Si un cambio de esquema no puede ser aditivo (ej. realmente hay que borrar una
columna), NO se merguea con el resto del deploy. El procedimiento es:

1. Migrar PRIMERO (ops manual contra Cloud SQL) fuera del pipeline.
2. Luego mergear el código que asume el nuevo esquema.

El op-scan del pipeline te va a bloquear si intentás meter una migración
destructiva en un push normal — es intencional.

---

## 8. Orden de merge de PRs

Esta feature de deploy (`feat/deploy-gcp-docker-swarm`) se basa en
`feat/task-grouping-frontend`, que a su vez está ~31 commits por delante de
`main`. La estrategia es **Feature Branch Chain** (ver skill `chained-pr`): el
PR de deploy apunta al branch tracker (`feat/task-grouping-frontend`), no a
`main` directamente.

```text
main
 └── feat/task-grouping-frontend        ← tracker (telegram + sidebar + audit)
      └── feat/deploy-gcp-docker-swarm  ← esta feature (deploy a GCP Swarm)
           ↑ PR apunta a feat/task-grouping-frontend (NO a main)
```

### Orden de merge

1. **Merge del tracker PR primero**: `feat/task-grouping-frontend` → `main`
   (telegram, sidebar, audit). Esto aterriza la base sobre la que se construye
   el deploy.
2. **Rebase + retarget del PR de deploy**: después del paso 1, rebasar
   `feat/deploy-gcp-docker-swarm` sobre `main` (que ahora incluye el tracker) y
   retargetear el PR a `main`. El diff que ve el reviewer debe ser SOLO el
   trabajo de deploy (sin el contenido del tracker, que ya está en main).
3. **Merge del PR de deploy** → `main`.

> **Diff hygiene**: si después del rebase GitHub sigue mostrando commits del
   tracker en el diff del PR de deploy, es un bug de branching — volvé a
   retargetear/rebasear hasta que el diff muestre únicamente el trabajo de
   deploy. Un diff contaminado es responsabilidad del autor del PR, no del
   reviewer (skill `chained-pr`).
>
> **Chain Context**: cada PR del chain lleva una tabla con posición, base,
> dependencias y budget de review (≤400 líneas cambiadas por PR). Los 4 slices
> de deploy (backend code, swarm stack, CI/CD, este runbook) son PRs encadenados
> individuales sobre `feat/deploy-gcp-docker-swarm` antes del merge final a
> main.
