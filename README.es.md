# auto-proxy-cloudflare

> También disponible en: [English](README.md)

Un daemon ligero que desactiva y reactiva automáticamente el proxy de Cloudflare en tus registros DNS cuando La Liga bloquea los rangos de IPs de Cloudflare.

## El problema

La Liga opera un sistema de bloqueo de IPs ordenado judicialmente en España que apunta a las IPs de proxy de Cloudflare durante las ventanas de partidos de fútbol — y a veces más allá. Si tu servidor está detrás de un dominio con proxy de Cloudflare, tus usuarios en España pueden quedarse sin acceso sin ningún aviso previo. La única solución es desactivar temporalmente el proxy para que el tráfico llegue directamente a la IP real de tu servidor.

Este servicio automatiza ese proceso: detecta el bloqueo, apaga el proxy, y lo vuelve a activar en cuanto se levanta el bloqueo — todo sin intervención manual.

## Cómo funciona

```
┌─────────────────────────────────────────────────────┐
│                  Bucle de sondeo                    │
│  Cada CHECK_INTERVAL segundos por cada dominio:     │
│                                                     │
│  1. Consulta la API de comprobación de deinser.com  │
│     → domain_blocked: true / false                  │
│                                                     │
│  2a. Si está BLOQUEADO y el proxy está activo       │
│      → API de Cloudflare: proxied=false             │
│      → (opcional) Notificación de Discord           │
│                                                     │
│  2b. Si está DESBLOQUEADO y el proxy lo apagamos    │
│      → API de Cloudflare: proxied=true              │
│      → (opcional) Notificación de Discord           │
└─────────────────────────────────────────────────────┘
```

**Importante:** el servicio solo reactiva el proxy en dominios que él mismo desactivó. Nunca tocará registros DNS que no haya modificado.

## API de detección de bloqueos

El estado de bloqueo se comprueba usando la API pública de [deinser.com](https://deinser.com):

```
GET https://deinser.com/cloudflare/laliga/?domain=<dominio>&json=1
```

Ejemplo de respuesta:

```json
{
  "domain": "sub.example.com",
  "domain_ips": ["188.114.96.3", "188.114.97.3"],
  "domain_with_cloudflare_proxy": true,
  "domain_blocked": true,
  "blocked_ips": [],
  "futbol_blocking_active": true,
  "from_cache": true
}
```

El servicio lee el campo `domain_blocked` para decidir si actuar.

## Configuración

Toda la configuración se hace mediante variables de entorno. Copia `.env.example` a `.env` y rellena los valores.

| Variable | Requerida | Por defecto | Descripción |
|---|---|---|---|
| `CF_API_TOKEN` | una de las dos | — | API Token de Cloudflare (**recomendado**) |
| `CF_API_KEY` + `CF_EMAIL` | una de las dos | — | Clave API global de Cloudflare + email de la cuenta (legacy) |
| `DOMAINS` | sí | — | Lista de dominios a monitorizar separados por comas |
| `CHECK_INTERVAL` | no | `300` | Segundos entre comprobaciones |
| `DISCORD_WEBHOOK_URL` | no | — | URL del webhook de Discord para notificaciones |
| `LOG_LEVEL` | no | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

### Permisos del API Token de Cloudflare

Al usar `CF_API_TOKEN` (recomendado frente a la clave API global), crea un token con:

- **Permiso:** `Zone` → `DNS` → `Edit`
- **Recursos de zona:** incluye solo la(s) zona(s) que quieres gestionar

Esto otorga al servicio el acceso mínimo necesario.

## Ejecutar con Docker

### Descargar desde GHCR

```bash
docker pull ghcr.io/Ninjakito/auto-proxy-cloudflare:latest
```

### Con Docker Compose

```bash
cp .env.example .env
# edita .env con tus valores
cp docker-compose.example.yml docker-compose.yml
docker compose up -d
```

### Con `docker run`

```bash
docker run -d \
  --name auto-proxy-cloudflare \
  --restart unless-stopped \
  --env-file .env \
  ghcr.io/Ninjakito/auto-proxy-cloudflare:latest
```

### Construir localmente

```bash
docker build -t auto-proxy-cloudflare .
docker run --env-file .env auto-proxy-cloudflare
```

## Ejecutar sin Docker

Requiere Python 3.12+.

```bash
pip install -r requirements.txt
cp .env.example .env
# edita .env
export $(grep -v '^#' .env | xargs)
python src/main.py
```

## Notificaciones de Discord

Cuando `DISCORD_WEBHOOK_URL` está configurado, el servicio envía un mensaje embed a tu canal de Discord en cada cambio de estado:

- **Embed rojo** — dominio bloqueado, proxy desactivado
- **Embed verde** — dominio desbloqueado, proxy reactivado

Las notificaciones son opcionales y nunca son necesarias para que el servicio funcione.

## Imagen Docker

Las imágenes multi-arquitectura (`linux/amd64` y `linux/arm64`) se construyen automáticamente mediante GitHub Actions y se publican en el GitHub Container Registry en cada push a `main`. Se publican dos tags por build: `:latest` y `:sha-<commit_corto>` para fijar una versión específica.

## Licencia

MIT
