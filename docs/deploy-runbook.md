# Guía de deploy — Turbolog en GCP Docker Swarm (versión simple)

> Guía didáctica, paso a paso. Es la **versión simple**: GitHub arma la imagen
> del contenedor solo, y vos la instalás en el swarm con un comando (`./deploy.sh`).
> No necesitás saber GitHub Actions — el archivo del pipeline ya está escrito.

---

## Cómo funciona (leelo en 1 minuto) 🧭

```
  [tu notebook]                [GitHub]                 [GCP Docker Swarm]
       │                          │                            │
  git push main ──────────────▶ builda la imagen              │
                              y la publica en GHCR ─────────▶ ./deploy.sh
                                   (ghcr.io/.../turbolog)     la descarga e instala
```

- **GitHub cocina** la imagen cada vez que subís código a `main` (automático).
- **Vos servís** esa imagen en el swarm con `./deploy.sh` (un comando, desde tu notebook).
- En el swarm corren **4 servicios**: `auth-proxy` (puente a la base), `backend` (la app), `scheduler` (recordatorios 17:30) y `cloudflared` (tu HTTPS público).

> **Dónde está el límite entre "automático" y "manual"**:
> - **Automático** (lo hace GitHub solo al pushear a `main`): compilar y publicar la imagen en GHCR.
> - **Manual** (lo hacés vos): correr `./deploy.sh` para instalar esa imagen en el swarm. El deploy **no** se dispara solo al pushear.
> - **Manual, una sola vez**: dejar el paquete de GHCR como **público** (Paso 6), para que los nodos del swarm puedan bajar la imagen sin autenticarse.

Vas a hacer **9 pasos**. Los pasos 1–3 son crear 3 cosas nuevas en GCP/Cloudflare (una sola vez). El resto es cargar valores y desplegar.

---

## Antes de empezar ✅

- `gcloud` instalado y logueado (`gcloud auth login`) — ya lo usás.
- Acceso de administrador al proyecto **`dockerswarm-491114`**.
- El swarm ya corriendo (lo tenés).

Configurá el proyecto y la zona de una vez:
```bash
gcloud config set project dockerswarm-491114
gcloud config set compute/zone southamerica-west1-a
```

---

## Paso 1 — Crear la base de datos (Cloud SQL) 🗄️

Crear una instancia Postgres gestionada (una sola vez).

```bash
# 1a. Crear la instancia (tarda un par de minutos). Elegí una password fuerte.
gcloud sql instances create turbolog \
  --database-version=POSTGRES_16 --region=southamerica-west1 \
  --root-password=UNA_PASSWORD_FUERTE

# 1b. Crear la base "turbolog" y un usuario "turbolog" con su password
gcloud sql databases create turbolog --instance=turbolog
gcloud sql users create turbolog --instance=turbolog --password=OTRA_PASSWORD_FUERTE

# 1c. Ver la política de backups (recomendado: encender backups automáticos)
gcloud sql instances patch turbolog --backup-start-time=03:00
```

**Anotá esto** (lo usás después):
- 🔑 **Connection name** → `gcloud sql instances describe turbolog --format='value(connectionName)'`
  (algo como `dockerswarm-491114:southamerica-west1:turbolog`)
- 🔑 **Usuario/password de la base** → `turbolog` / la password del paso 1b.

Ahora creá una **service account** que permita a la app conectarse a esa base:
```bash
# 1d. Crear la service account y darle permiso de Cloud SQL
gcloud iam service-accounts create turbolog-cloudsql
gcloud projects add-iam-policy-binding dockerswarm-491114 \
  --member=serviceAccount:turbolog-cloudsql@dockerswarm-491114.iam.gserviceaccount.com \
  --role=roles/cloudsql.client

# 1e. Bajar la key en JSON (¡este archivo es un secreto!)
gcloud iam service-accounts keys create cloudsql-sa-key.json \
  --iam-account=turbolog-cloudsql@dockerswarm-491114.iam.gserviceaccount.com
```
**Anotá esto:** te quedó un archivo **`cloudsql-sa-key.json`** en tu notebook. Guardalo — es uno de los secretos.

---

## Paso 2 — El túnel de Cloudflare (tu HTTPS) ☁️

Esto expone tu app a internet con HTTPS, sin abrir puertos en el swarm.

1. Entrá a **Cloudflare → Zero Trust → Networks → Tunnels → Create a tunnel**.
2. Elegí **Cloudflared**, dale un nombre (ej: `turbolog`), y copiá el **token** que te muestra.
   **Anotá esto:** 🔑 el **token del túnel**.
3. En el paso de **Public Hostnames**, agregá:
   - un subdominio (ej: `turbolog.tuempresa.cl`),
   - que apunte al servicio `http://backend:8000`.
   **Anotá esto:** 🔑 tu **dominio** (`https://turbolog.tuempresa.cl`).
   (Cloudflare configura el DNS solo.)

> El contenedor `cloudflared` del swarm usa ese token para conectarse al túnel.

---

## Paso 3 — Google OAuth para producción 🔐

Para que el login con Google ande en producción, agregá tu dominio nuevo:

1. **Google Cloud Console → APIs & Services → Credentials → tu OAuth Client ID**.
2. En **Authorized redirect URIs**, agregá:
   `https://turbolog.tuempresa.cl/api/auth/google/callback`
   (con TU dominio del Paso 2).
3. **Anotá** el **Client ID** y el **Client Secret** (si no los tenés a mano).

---

## Paso 4 — Completar `docker-stack.yml` ✏️

Abrí `docker-stack.yml` y reemplazá los valores marcados `TODO operador`:

| Campo | Qué poner |
|---|---|
| `auth-proxy` → connection name | tu **Connection name** del Paso 1 (`dockerswarm-491114:southamerica-west1:turbolog`) |
| `APP_URL` (backend y scheduler) | tu dominio con https: `https://turbolog.tuempresa.cl` |
| `CORS_ORIGINS` | lo mismo que `APP_URL` |
| `GOOGLE_CLIENT_ID` | tu Client ID del Paso 3 |
| `JIRA_EMAIL` / `JIRA_DOMAIN` | los de tu JIRA (los mismos de hoy) |
| `ADMIN_EMAILS` | tu email de super-admin |

Los demás (`REMINDER_TIME`, `AUDIT_TIMEZONE`, `LLM_*`, etc.) dejalos como están — son la config de siempre.

---

## Paso 5 — Completar `deploy.sh` ✏️

Abrí `deploy.sh` y poné el nombre de tu nodo manager:
```bash
MANAGER="NOMBRE_DEL_MANAGER"   # ← tu nodo (sacalo con: gcloud compute instances list)
```

---

## Paso 6 — Subir el código (GitHub arma la imagen) 🚀

```bash
git add -A && git commit -m "deploy config"   # si cambiaste algo
git push
```
Al pushear a `main`, GitHub compila y publica la imagen en `ghcr.io/cperez-infoboy/turbolog`.

**Una vez terminado el primer build**, hacé la imagen pública (para que el swarm la descargue sin contraseña):
> GitHub → tu perfil → **Packages** → `turbolog` → **Package settings** → *Change visibility* → **Public**.

---

## Paso 7 — Cargar los 8 secretos en el swarm 🔑

Los secretos son los valores sensibles (passwords, tokens). Se cargan **una vez** en el swarm.

Primero subí al manager el script de creación **y** la key de Cloud SQL:
```bash
MANAGER="NOMBRE_DEL_MANAGER"
gcloud compute scp scripts/create-secrets.sh $MANAGER:~/
gcloud compute scp cloudsql-sa-key.json       $MANAGER:~/
```
Después entrá al manager y corré el script (te pregunta los 8 valores, uno por uno):
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

## Paso 8 — Desplegar el stack (una sola vez) 🏗️

Subí el stack al manager y desplegá:
```bash
# desde tu notebook
gcloud compute scp docker-stack.yml $MANAGER:~/
gcloud compute ssh $MANAGER --tunnel-through-iap -- docker stack deploy -c ~/docker-stack.yml turbolog
```
El swarm levanta los 4 servicios y descarga la imagen de GitHub.

---

## Paso 9 — Verificar que anda ✅

```bash
# los 4 servicios deben estar "replicas 1/1"
gcloud compute ssh $MANAGER -- docker service ls

# la app responde por tu dominio
curl https://turbolog.tuempresa.cl/api/health      # → {"status":"ok"}
```
Después abrí `https://turbolog.tuempresa.cl` en el navegador y probá loguearte con Google.

🎉 **Listo, Turbolog en producción.**

---

## Después: cómo actualizar a una nueva versión ♻️

Cada vez que cambies código:
```bash
git push          # GitHub arma la imagen nueva (tarda unos minutos)
```
**Esperá a que termine el build en GitHub Actions** (pestaña *Actions* del repo).
Si corrés `./deploy.sh` antes de que termine, el swarm se baja la imagen `:latest`
vieja y no ves tu cambio.
```bash
./deploy.sh       # la instala en el swarm (un comando)
```

## Rollback (volver a la versión anterior) ⏪

```bash
./deploy.sh <sha-anterior>     # el sha lo ves en GitHub → Commits
```

## Si algo falla 🔧

```bash
# ver el estado de los servicios
gcloud compute ssh $MANAGER -- docker service ls

# ver logs de un servicio (ej: backend)
gcloud compute ssh $MANAGER -- docker service logs turbolog_backend --tail 50

# ver qué contenedor falla
gcloud compute ssh $MANAGER -- docker stack ps turbolog --no-trunc
```

**Errores comunes:**
- *El backend reinicia en loop* → probablemente un secreto mal cargado. Revisá los 8 con `docker secret ls`. El `assert_prod_secrets` hace que el backend arranque solo si los secretos críticos están bien.
- *La imagen no descarga* → ¿hiciste el paquete de GHCR público (Paso 6)?
- *No llega el HTTPS* → revisá el túnel de Cloudflare y que `APP_URL` tenga el dominio correcto.
