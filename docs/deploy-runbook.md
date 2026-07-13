# Guía de deploy — Turbolog en GCP Docker Swarm (con deploy automático por botón)

> Guía didáctica, paso a paso, pensada para alguien que nunca manejó imágenes
> en GitHub ni GitHub Actions. Esta versión **arma la imagen automáticamente**
> cada vez que subís código, y **deploya a producción con un click** en GitHub
> Actions. No necesitás saber nada de CI/CD — los archivos del pipeline ya están
> escritos.

---

## Conceptos (leelo si es tu primera vez) 🧠

Si nunca te topaste con contenedores, GitHub Actions o permisos de GCP, este
bloque te salva. Cada concepto en pocas líneas, con una analogía.

### ¿Qué es un contenedor y una imagen Docker?

Un **contenedor** es una caja sellada que tiene adentro todo lo que la app
necesita para correr: el código, las dependencias, el sistema de archivos —
todo. Se ejecuta igual en tu notebook, en un servidor, o en la nube. La
**imagen** es el *molde* (la receta) que genera esa caja. Pensalo como un
molde de torta: la imagen es el molde, cada contenedor es una torta hecha con
ese molde. Cuando "actualizás la imagen", cambiás el molde — y los contenedores
nuevos salen de ahí.

### ¿Qué es GHCR (GitHub Container Registry)?

Es el **depósito de imágenes** de GitHub. Cuando GitHub arma tu imagen, la
guarda acá, en `ghcr.io/cperez-infoboy/turbolog`. Los servidores del swarm
descargan la imagen de ese depósito — igual que cuando bajás un paquete de npm
o pip, pero para contenedores. Mientras el paquete sea **público**, cualquier
servidor lo puede bajar sin contraseña.

### ¿Qué es GitHub Actions / un workflow / un job?

**GitHub Actions** es un robot que ejecuta tareas cuando le decís. Un
**workflow** es la *receta* de tareas, guardada en un archivo dentro de
`.github/workflows/`. Un **job** es un bloque de pasos dentro de esa receta.
Los workflows se pueden disparar **solos** (ej: al pushear a `main`) o **a
mano** con un botón ("Run workflow"). Turbolog tiene dos: `build-image`
(automático al pushear) y `deploy` (manual, un click).

### ¿Qué es un secret vs una variable en GitHub?

Ambos viven en **Settings → Secrets and variables → Actions** del repo. Un
**secret** guarda un valor *sensible* (passwords, keys): se carga, se
encripta, y **no se puede volver a leer** después — solo usarse. Una
**variable** guarda un valor *no sensible* (nombres de zona, proyecto,
dominio): es visible y se puede editar. Regla simple: si te daría miedo que
alguien lo vea → secret. Si es un nombre → variable.

### ¿Qué es una Service Account (SA) de GCP?

Es una **"cuenta robot"** de Google Cloud, no una persona. Tiene su propio
email (`algo@dockerswarm-491114.iam.gserviceaccount.com`) y permisos
específicos. GitHub Actions se hace pasar por ella usando su **key JSON**
para poder ejecutar comandos `gcloud` (deployar, SSHuear) sin que vos estés
logueado. Es como darle una llave de servicio a un empleado temporario: le
dás solo las llaves que necesita, nada más.

### ¿Qué es IAP (Identity-Aware Proxy)?

Los nodos del swarm **no tienen IP pública** — nadie de afuera puede
conectarse directo. **IAP** es el único *túnel legal* para llegar a ellos por
SSH desde afuera de Google. El comando `gcloud compute ssh
--tunnel-through-iap` enruta tu conexión SSH a través de IAP, que verifica
quién sos antes de dejarte entrar. Sin IAP, no hay forma de tocar el swarm
remotamente.

### ¿Qué es OS Login?

Es el sistema de GCP que dice **quién puede SSHuear a cada VM y con qué
clave**. Cuando GitHub deploya, genera una clave SSH fresca (distinta cada
vez) y la *registra* vía OS Login. Para que esto funcione, las VMs tienen que
tener `enable-oslogin=TRUE` en sus metadatos. Sin eso, la SA no puede
registrar su clave y el deploy falla.

---

## Cómo funciona ahora 🧭

```
  [tu notebook]              [GitHub]                    [GCP Docker Swarm]
       │                        │                              │
  git push main ────────▶ build de la imagen                    │
                       (workflow build-image)                   │
                       publica en GHCR ──┐                      │
                                          │                      │
   [vos, en GitHub Actions]               │                      │
   click "Run workflow" ──────────▶ workflow deploy             │
                                   (se hace pasar por la SA)     │
                                   SSH por IAP ──────────────▶ roll de imagen
                                                                 backend + scheduler
                                                                 reinician solos
```

**Lo importante — dónde está el límite entre automático y manual:**

- **Build = automático.** Cada vez que subís código a `main`, GitHub compila
  la imagen y la publica en GHCR. Vos no hacés nada.
- **Deploy = manual, un click.** Vos decidís *cuándo* esa imagen nueva llega
  a producción, entrando a la pestaña **Actions** y cliqueando **Run
  workflow**. El deploy **no** se dispara solo al pushear — eso es a
  propósito, para que tengas el control de cuándo llega a prod.

En el swarm corren **4 servicios**: `auth-proxy` (puente a la base Cloud SQL),
`backend` (la app FastAPI + frontend), `scheduler` (recordatorios 17:30) y
`cloudflared` (tu HTTPS público vía túnel de Cloudflare).

> ¿Y `deploy.sh`? Queda como **fallback manual** — por si GitHub Actions no
> está disponible o querés deployar desde tu terminal. Lo documentamos al
> final de la guía.

---

## Antes de empezar ✅

- `gcloud` instalado y logueado (`gcloud auth login`).
- Acceso de administrador al proyecto **`dockerswarm-491114`**.
- El swarm ya corriendo (con al menos un nodo *manager*).

Configurá el proyecto y la zona de una vez para no repetirlos en cada comando:
```bash
gcloud config set project dockerswarm-491114          # tu proyecto de GCP
gcloud config set compute/zone southamerica-west1-a   # zona donde están las VMs
```

---

## Setup — una sola vez 🏗️

Son **9 pasos** para dejar la infra parada + **una sección extra** (pasos
10–16) para habilitar el deploy por botón. Los pasos 1–3 crean tres cosas
nuevas en GCP / Cloudflare / Google. El resto es cargar valores y desplegar.

### Paso 1 — Crear la base de datos (Cloud SQL) 🗄️

Crear una instancia Postgres gestionada (Google la mantiene y la backupuea
sola). Una sola vez.

```bash
# 1a. Crear la instancia (tarda un par de minutos). Elegí una password fuerte.
gcloud sql instances create turbolog \
  --database-version=POSTGRES_16 --region=southamerica-west1 \
  --root-password=UNA_PASSWORD_FUERTE
```

```bash
# 1b. Crear la base "turbolog" y un usuario "turbolog" con su password
gcloud sql databases create turbolog --instance=turbolog
gcloud sql users create turbolog --instance=turbolog --password=OTRA_PASSWORD_FUERTE
```

```bash
# 1c. Encender backups automáticos (recomendado — cada noche a las 03:00)
gcloud sql instances patch turbolog --backup-start-time=03:00
```

**Anotá esto** (lo usás en el Paso 7):
- 🔑 **Connection name** → `gcloud sql instances describe turbolog --format='value(connectionName)'`
  (algo como `dockerswarm-491114:southamerica-west1:turbolog`)
- 🔑 **Usuario/password de la base** → `turbolog` / la password del paso 1b.

Ahora creá una **service account** que permita a la app conectarse a esa base
(el contenedor `auth-proxy` del swarm la usa):
```bash
# 1d. Crear la SA "turbolog-cloudsql" y darle permiso de cliente de Cloud SQL
gcloud iam service-accounts create turbolog-cloudsql
gcloud projects add-iam-policy-binding dockerswarm-491114 \
  --member=serviceAccount:turbolog-cloudsql@dockerswarm-491114.iam.gserviceaccount.com \
  --role=roles/cloudsql.client
```

```bash
# 1e. Bajar la key en JSON — este archivo es un SECRETO, no lo subas a git
gcloud iam service-accounts keys create cloudsql-sa-key.json \
  --iam-account=turbolog-cloudsql@dockerswarm-491114.iam.gserviceaccount.com
```
**Anotá esto:** te quedó un archivo **`cloudsql-sa-key.json`** en tu notebook.
Guardalo — es uno de los 8 secretos del swarm.

---

### Paso 2 — El túnel de Cloudflare (tu HTTPS) ☁️

Esto expone tu app a internet con HTTPS, sin abrir puertos en el swarm. El
contenedor `cloudflared` del swarm se conecta a Cloudflare por un túnel
saliente.

1. Entrá a **Cloudflare → Zero Trust → Networks → Tunnels → Create a tunnel**.
2. Elegí **Cloudflared**, dale un nombre (ej: `turbolog`), y copiá el **token**
   que te muestra.
   **Anotá esto:** 🔑 el **token del túnel**.
3. En el paso de **Public Hostnames**, agregá:
   - un subdominio (ej: `turbolog.tuempresa.cl`),
   - que apunte al servicio `http://backend:8000`.
   **Anotá esto:** 🔑 tu **dominio** (`https://turbolog.tuempresa.cl`).
   (Cloudflare configura el DNS solo.)

---

### Paso 3 — Google OAuth para producción 🔐

Para que el login con Google ande en producción, agregá tu dominio nuevo como
destino válido de redirect.

1. **Google Cloud Console → APIs & Services → Credentials → tu OAuth Client ID**.
2. En **Authorized redirect URIs**, agregá:
   `https://turbolog.tuempresa.cl/api/auth/google/callback`
   (con TU dominio del Paso 2).
3. **Anotá** el **Client ID** y el **Client Secret** (si no los tenés a mano).

---

### Paso 4 — Completar `docker-stack.yml` ✏️

Abrí `docker-stack.yml` y reemplazá todos los valores marcados `TODO operador`:

| Campo | Qué poner |
|---|---|
| `auth-proxy` → connection name | tu **Connection name** del Paso 1 (`dockerswarm-491114:southamerica-west1:turbolog`) |
| `APP_URL` (backend y scheduler) | tu dominio con https: `https://turbolog.tuempresa.cl` |
| `CORS_ORIGINS` | lo mismo que `APP_URL` |
| `GOOGLE_CLIENT_ID` | tu Client ID del Paso 3 |
| `JIRA_EMAIL` / `JIRA_DOMAIN` | los de tu JIRA (los mismos de hoy) |
| `ADMIN_EMAILS` | tu email de super-admin |

Los demás (`REMINDER_TIME`, `AUDIT_TIMEZONE`, `LLM_*`, etc.) dejalos como están —
son la config de siempre.

---

### Paso 5 — Completar `deploy.sh` ✏️

Abrí `deploy.sh` y poné el nombre de tu nodo manager (el que va a recibir los
deploys manuales de fallback):
```bash
MANAGER="NOMBRE_DEL_MANAGER"   # ← tu nodo (sacalo con: gcloud compute instances list)
```
También vas a necesitar este nombre para la variable `SWARM_MANAGER_NODE` de
GitHub (Paso 16).

---

### Paso 6 — Subir el código (GitHub arma la imagen) 🚀

```bash
git add -A && git commit -m "deploy config"   # si cambiaste algo en los pasos 4-5
git push
```
Al pushear a `main`, el workflow `build-image` compila y publica la imagen en
`ghcr.io/cperez-infoboy/turbolog`. No configurás ningún secreto — `GITHUB_TOKEN`
es automático.

**Una vez terminado el primer build**, hacé la imagen **pública** (para que los
nodos del swarm la descarguen sin autenticarse):
> GitHub → tu perfil → **Packages** → `turbolog` → **Package settings** →
> *Change visibility* → **Public**.

---

### Paso 7 — Cargar los 8 secretos en el swarm 🔑

Los secretos son los valores sensibles (passwords, tokens, keys). Se cargan
**una vez** en el swarm y después no se tocan.

Primero subí al manager el script de creación **y** la key de Cloud SQL:
```bash
MANAGER="NOMBRE_DEL_MANAGER"
gcloud compute scp scripts/create-secrets.sh $MANAGER:~/
gcloud compute scp cloudsql-sa-key.json       $MANAGER:~/
```
Después entrá al manager por túnel IAP y corré el script (te pregunta los 8
valores, uno por uno):
```bash
gcloud compute ssh $MANAGER --tunnel-through-iap
# ya adentro del manager:
bash ~/create-secrets.sh
```
Te va a pedir:

| Te pide | Qué responder |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://turbolog:PASSWORD@auth-proxy:5432/turbolog` (la password del Paso 1b) |
| `GOOGLE_CLIENT_SECRET` | tu Client Secret del Paso 3 |
| `JWT_SECRET` | generá uno: salí, corré `openssl rand -hex 32`, copialo |
| `JIRA_API_TOKEN` | el token de JIRA (el de hoy) |
| `LLM_API_KEY` | tu key de DeepSeek (o vacío si no usás /improve) |
| `TELEGRAM_BOT_TOKEN` | el token de @BotFather (el de hoy) |
| `CLOUDSQL_SA_KEY` | la **ruta al archivo**: `~/cloudsql-sa-key.json` |
| `CLOUDFLARE_TOKEN` | el token del túnel del Paso 2 |

Verificá: `docker secret ls | grep _v1` → deben aparecer los 8.

---

### Paso 8 — Desplegar el stack (una sola vez) 🏗️

Subí el stack al manager y desplegá — el swarm levanta los 4 servicios y
descarga la imagen de GitHub:
```bash
# desde tu notebook
gcloud compute scp docker-stack.yml $MANAGER:~/
gcloud compute ssh $MANAGER --tunnel-through-iap -- docker stack deploy -c ~/docker-stack.yml turbolog
```

---

### Paso 9 — Verificar que anda ✅

```bash
# los 4 servicios deben estar "replicas 1/1"
gcloud compute ssh $MANAGER -- docker service ls

# la app responde por tu dominio
curl https://turbolog.tuempresa.cl/api/health      # → {"status":"ok"}
```
Después abrí `https://turbolog.tuempresa.cl` en el navegador y probá loguearte
con Google.

🎉 **Turbolog en producción.** Desde acá podés deployar a mano con `deploy.sh`,
o habilitar el botón — que es lo que sigue.

---

## Habilitar el deploy por botón (recomendado) 🔘

Hasta acá deployás con `./deploy.sh` desde tu terminal. Esta sección te deja
deployar **con un click en GitHub Actions** — sin abrir la terminal. Se hace
una sola vez. Son 7 pasos chiquitos.

La idea: crear una **service account** `turbolog-deployer` que GitHub
"interpreta" para poder SSHuear al swarm por IAP y rodar la imagen nueva.

### Paso 10 — Crear la Service Account `turbolog-deployer` 🔑

```bash
# Crear la SA "turbolog-deployer" — la cuenta robot que GitHub usa para deployar
gcloud iam service-accounts create turbolog-deployer
```

Darle **solo dos roles** (mínimo privilegio — GHCR es público, así que no
necesita permisos de descarga de imágenes; Cloud SQL es otra SA):

```bash
# Rol 1: puede usar el túnel IAP para llegar a los nodos del swarm
gcloud projects add-iam-policy-binding dockerswarm-491114 \
  --member=serviceAccount:turbolog-deployer@dockerswarm-491114.iam.gserviceaccount.com \
  --role=roles/iap.tunnelResourceAccessor
```

```bash
# Rol 2: puede SSHuear a las VMs como admin y registrar claves vía OS Login
gcloud projects add-iam-policy-binding dockerswarm-491114 \
  --member=serviceAccount:turbolog-deployer@dockerswarm-491114.iam.gserviceaccount.com \
  --role=roles/compute.osAdminLogin
```

**Qué hace cada rol:**
- `iap.tunnelResourceAccessor` → le permite **usar el túnel IAP** (el único
  camino legal para llegar por SSH a los nodos sin IP pública).
- `compute.osAdminLogin` → le permite **SSHuear a las VMs como admin** y
  registrar claves SSH a través de OS Login.

---

### Paso 11 — Habilitar OS Login en las VMs del swarm ⚙️

Sin esto, la SA no puede registrar su clave SSH y el deploy falla.
```bash
# Habilitar OS Login a nivel de proyecto (afecta a todas las VMs del swarm)
gcloud compute project-info add-metadata --metadata=enable-oslogin=TRUE
```
> Si querés habilitarlo solo en un nodo específico, agregá el mismo metadato
> a esa instancia:
> `gcloud compute instances add-metadata <NODO> --metadata=enable-oslogin=TRUE`.

---

### Paso 12 — Regla de firewall para IAP 🧱

IAP necesita una regla que le permita llegar al puerto 22 (SSH) de las VMs.
Verificá si ya existe; si no, creala:
```bash
# Si "allow-iap-ssh" ya existe, no hace nada; si no existe, la crea
gcloud compute firewall-rules describe allow-iap-ssh 2>/dev/null || \
gcloud compute firewall-rules create allow-iap-ssh \
  --direction=INGRESS --action=ALLOW --rules=tcp:22 \
  --source-ranges=35.235.240.0/20
```
El rango `35.235.240.0/20` es **el rango de IPs de IAP de Google** — solo
desde ahí puede venir una conexión por el túnel IAP.

---

### Paso 13 — Bajar la key JSON de la SA ⬇️

```bash
# Generar la key JSON de la SA deployer — es un SECRETO, no la subas a git
gcloud iam service-accounts keys create turbolog-deployer-key.json \
  --iam-account=turbolog-deployer@dockerswarm-491114.iam.gserviceaccount.com
```
⚠️ Este archivo es un **secreto crítico**: quien lo tenga puede deployar (y
SSHuear) como la SA. No lo subas a git. No lo compartas.

---

### Paso 14 — Verificar el perfil OS Login de la SA 🔍

Para confirmar que OS Login quedó bien y la SA puede usarse, autenticate como
ella y mirá su perfil:
```bash
# Autenticarse como la SA (con la key recién bajada)
gcloud auth activate-service-account --key-file=turbolog-deployer-key.json
```
```bash
# Ver el perfil OS Login — debe mostrar un usuario POSIX (nombre, uid, gid)
gcloud compute os-login describe-profile
```
Si responde con un perfil POSIX, está todo bien. Si da error, OS Login no
quedó habilitado — revisá el Paso 11.

> Cuando termines, podés volver a tu cuenta personal con
> `gcloud auth login` (no afecta a GitHub, que usa la key directamente).

---

### Paso 15 — Cargar el secret `GCP_SA_KEY` en GitHub 📥

En el repo de GitHub:
1. **Settings → Secrets and variables → Actions → New repository secret**.
2. Name: `GCP_SA_KEY`.
3. Value: pegá **todo el contenido** del archivo `turbolog-deployer-key.json`
   (abril, copiá todo, pegalo).

GitHub lo encripta — después de cargarlo **no podés volver a leerlo**, solo
usarlo. Si necesitás cambiarlo, lo sobrescribís cargando uno nuevo con el
mismo nombre.

---

### Paso 16 — Cargar 4 variables en GitHub 📋

En el mismo lugar (**Settings → Secrets and variables → Actions**) pero en la
pestaña **Variables** (no Secrets — estos valores no son sensibles):

| Nombre | Valor | Por qué |
|---|---|---|
| `GCP_PROJECT_ID` | `dockerswarm-491114` | el proyecto donde vive el swarm |
| `GCP_ZONE` | `southamerica-west1-a` | la zona del nodo manager |
| `SWARM_MANAGER_NODE` | (tu nombre de manager, igual que en `deploy.sh`) | a qué nodo SSHuear |
| `APP_DOMAIN` | `turbolog.tuempresa.cl` (**sin** `https://`) | para el smoke post-deploy |

Sacá el nombre del manager con:
```bash
gcloud compute instances list   # buscá la VM que hace de manager en el swarm
```

---

## Deploy — lo que repetís siempre 🚀

Una vez hecho el setup de arriba, deployar es esto:

1. **Subí el código** (si cambiaste algo):
   ```bash
   git push
   ```
   GitHub arranca el build de la imagen nueva. **Esperá a que termine** — si
   deployás antes, el swarm se baja la imagen vieja y no ves tu cambio. Lo ves
   en la pestaña **Actions** del repo (workflow `build-image`, bolita verde ✓).

2. Andá a la pestaña **Actions** del repo y seleccioná el workflow **"deploy"**
   en la columna de la izquierda.

3. Click **"Run workflow"** → se abre un menú desplegable → dejá `image_tag`
   como `latest` (es el default) → click en el botón verde **"Run workflow"**.

4. Mirá el job: bolita amarilla (corriendo) → ✓ verde (listo) o ✗ rojo (falló).
   Hacé click en el run para ver el log paso por paso.

5. Listo — el swarm bajó la imagen nueva y reinició `backend` + `scheduler`.

El workflow `deploy` hace esto por vos, sin que toques nada:
1. Se autentica como la SA `turbolog-deployer` (con el secret `GCP_SA_KEY`).
2. Genera una clave SSH fresca (distinta cada vez) y la registra vía OS Login.
3. Entra al manager por túnel IAP.
4. Le dice al swarm que actualice `backend` y `scheduler` a la imagen nueva.
5. Hace un **smoke**: pega a `/api/health` (debe dar 200) y `/api/auth/me`
   (debe dar 401, no 5xx). Si algo da 5xx, el job falla y te avisa.

> **Alternativa manual (fallback):** si GitHub Actions no está disponible, o
> querés deployar desde tu terminal:
> ```bash
> ./deploy.sh              # instala :latest
> ./deploy.sh <sha>        # instala un tag específico (rollback)
> ```

---

## Rollback (volver a la versión anterior) ⏪

Mismo botón **Run workflow**, pero en `image_tag` poné el **SHA** del commit
anterior (los 7 caracteres que ves en GitHub → *Commits*, o en *Packages →
turbolog → versions*).

```
image_tag: 50094a8     ← el sha corto del commit al que querés volver
```

El swarm baja esa imagen específica (`ghcr.io/.../turbolog:50094a8`) en lugar
de `:latest`, y reinicia. En menos de un minuto estás en la versión anterior.

> También podés rollback por terminal: `./deploy.sh 50094a8`.

---

## Si algo falla 🔧

**El job "deploy" falla en "Generate and register CI SSH key"**
→ OS Login no está habilitado (Paso 11), o la SA no tiene `compute.osAdminLogin`
(Paso 10). Revisá ambos.

**Falla en "Roll image" con error de IAP/tunnel**
→ la SA no tiene `iap.tunnelResourceAccessor` (Paso 10), o la regla de firewall
`allow-iap-ssh` no existe (Paso 12).

**`gcloud compute ssh` pide contraseña o se cuelga**
→ la key del secret `GCP_SA_KEY` no es válida o expiró. Regenerala (Paso 13) y
volvé a cargar el secret (Paso 15).

**El smoke falla (health no 200, o /api/auth/me da 5xx)**
→ la imagen arrancó pero algo rompe adentro (secreto mal cargado, migración
que falla). Mirá los logs del backend:
```bash
gcloud compute ssh $MANAGER --tunnel-through-iap -- docker service logs turbolog_backend --tail 50
```

**La imagen no descarga en el swarm**
→ ¿hiciste el paquete de GHCR **público** (Paso 6)? Sin eso, los nodos no
pueden bajar la imagen sin autenticarse.

**Deployar a mano como fallback** (si GitHub Actions no anda):
```bash
./deploy.sh              # latest
./deploy.sh <sha>        # tag específico
```

**Ver el estado del swarm** (siempre útil):
```bash
gcloud compute ssh $MANAGER -- docker service ls                              # estado de los 4 servicios
gcloud compute ssh $MANAGER -- docker service logs turbolog_backend --tail 50 # logs del backend
gcloud compute ssh $MANAGER -- docker stack ps turbolog --no-trunc           # qué contenedor falla
```

---

## Después: cómo actualizar a una nueva versión ♻️

El loop de siempre, ahora con botón:

```bash
git push          # GitHub arma la imagen nueva (tarda unos minutos)
```

1. **Esperá a que termine el build** en la pestaña *Actions* (workflow
   `build-image`, bolita verde ✓). Si deployás antes de que termine, el swarm
   se baja la imagen `:latest` vieja y no ves tu cambio.
2. **Click "Run workflow"** en el workflow `deploy` → dejá `latest`.
3. Mirá el smoke — si da ✓ verde, ya estás en producción.
