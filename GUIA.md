# Guía paso a paso — Azure Hybrid Latency Lab

Esta es la guía exhaustiva para reproducir el laboratorio desde cero, en **español**, con todos los comandos exactos y los outputs esperados. Está pensada para que la sigas sin tener que adivinar nada.

> ⏱️ Tiempo total: ~ 30–40 min reloj (de los cuales ~25 min son el provisioning del vWAN hub).
> 💸 Coste mientras está vivo: ~ 0,40 €/h.

## Índice

1. [Pre-requisitos](#paso-1--pre-requisitos)
2. [Login y selección de suscripción](#paso-2--login-y-suscripción)
3. [Generar la clave SSH](#paso-3--generar-la-clave-ssh)
4. [Desplegar la infraestructura con Bicep](#paso-4--desplegar-la-infraestructura)
5. [Onboarding de la VM "on-prem" a Azure Arc](#paso-5--onboarding-de-la-vm-on-prem-a-azure-arc)
6. [Sembrar la BBDD desde la VM spoke](#paso-6--sembrar-la-bbdd)
7. [Ejecutar el experimento desde on-prem (WAN, 80 ms simulados)](#paso-7--ejecutar-el-experimento-desde-on-prem)
8. [Ejecutar el experimento desde el spoke (LAN)](#paso-8--ejecutar-el-experimento-desde-el-spoke)
9. [Sonda de latencia pura por query](#paso-9--sonda-de-latencia)
10. [Generar el notebook de análisis](#paso-10--generar-el-notebook)
11. [Inspeccionar telemetría en Azure](#paso-11--telemetría-en-azure)
12. [Limpiar todo](#paso-12--limpieza)
13. [Solución de problemas](#solución-de-problemas-frecuentes)

---

## Paso 1 — Pre-requisitos

### 1.1 Cuenta y permisos en Azure

- Suscripción Azure activa.
- Permisos **Owner** sobre la suscripción (o Contributor + User Access Administrator). Necesitas crear un service principal para Arc, y eso requiere asignar roles.

### 1.2 Herramientas locales

Comprueba que tienes todo:

```bash
az --version              # >= 2.60
az bicep version          # >= 0.27
ssh-keygen -V             # cualquier versión OpenSSH
python --version          # >= 3.10  (sólo si vas a regenerar el notebook localmente)
```

En Windows con PowerShell 7+ o WSL todo funciona igual; los scripts `.sh` los puedes ejecutar desde Git Bash, WSL o cualquier shell POSIX.

### 1.3 Clonar el repo

```bash
git clone https://github.com/chapi-dev/azure-hybrid-latency-lab.git
cd azure-hybrid-latency-lab
```

---

## Paso 2 — Login y suscripción

```bash
az login
az account list --output table
az account set --subscription "<NOMBRE_O_ID_DE_TU_SUSCRIPCION>"
az account show --query "{name:name, id:id, tenantId:tenantId}" -o table
```

Apunta el **Subscription ID** y el **Tenant ID** — los necesitarás para Arc.

---

## Paso 3 — Generar la clave SSH

```bash
ssh-keygen -t ed25519 -f ~/.ssh/hyblat_id_ed25519 -N '' -C hybrid-latency-lab
```

Esto crea:
- `~/.ssh/hyblat_id_ed25519` (clave privada — no la subas a ningún sitio)
- `~/.ssh/hyblat_id_ed25519.pub` (clave pública — la inyecta Bicep en las VMs)

En Windows con PowerShell:

```powershell
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\hyblat_id_ed25519" -N '""' -C hybrid-latency-lab
```

---

## Paso 4 — Desplegar la infraestructura

### 4.1 Lanza el script de despliegue

```bash
cd infra
./deploy.sh
```

Salida esperada (extracto):

```
Generated PG password (save it): <GENERATED_PASSWORD_24_CHARS>Aa1!
{
  "id": "/subscriptions/.../resourceGroups/rg-hybrid-latency-lab",
  ...
}
Name      ResourceGroup            Mode         ProvisioningState
--------  -----------------------  -----------  -----------------
lab-...   rg-hybrid-latency-lab    Incremental  Succeeded
Deployment complete.
```

🚨 **Apunta la `PG_PASSWORD`** que imprime — sólo se muestra una vez. La vas a necesitar en el Paso 7.

### 4.2 ¿Qué se crea?

| Recurso | Nombre por defecto | Propósito |
|---|---|---|
| Resource Group | `rg-hybrid-latency-lab` | Contenedor de todo |
| Virtual WAN | `hyblat-vwan` | Backbone híbrido |
| Virtual Hub | `hyblat-hub` (Standard, 10.0.0.0/24) | Hub central, conecta los dos VNets |
| VNet spoke | `hyblat-spoke-vnet` (10.10.0.0/16) | Red "Azure" donde vive PG |
| VNet on-prem | `hyblat-onprem-vnet` (10.100.0.0/16) | Red que simula on-prem |
| VM spoke | `hyblat-vm-spoke` (Standard_B2s_v2, Ubuntu 24.04) | Cliente "LAN" |
| VM on-prem | `hyblat-vm-onprem` (Standard_B2s_v2, Ubuntu 24.04) | Cliente "WAN" |
| PostgreSQL Flex | `hyblat-pg-<random>` (B1ms) | BBDD bajo prueba |
| Log Analytics | `hyblat-law` | Workspace de logs |
| Application Insights | `hyblat-ai` | Trazas / dependencias / métricas |
| Connection Monitor | `hyblat-cm-onprem-to-pg` | Probes TCP/5432 cada 60 s desde on-prem |

### 4.3 Comprueba el despliegue

```bash
az resource list -g rg-hybrid-latency-lab -o table
```

Deberías ver ~30 recursos (incluyendo NICs, IPs públicas, NSGs, etc.).

### 4.4 Outputs del despliegue

```bash
RG=rg-hybrid-latency-lab
DN=$(az deployment group list -g $RG --query "[0].name" -o tsv)
az deployment group show -g $RG -n "$DN" --query properties.outputs -o jsonc
```

Salida esperada:

```jsonc
{
  "pgFqdn": { "value": "hyblat-pg-xxxx.postgres.database.azure.com" },
  "appInsightsConnectionString": { "value": "InstrumentationKey=...;IngestionEndpoint=..." },
  "vmOnpremPublicIp": { "value": "20.x.x.x" },
  "vmSpokePublicIp": { "value": "104.x.x.x" }
}
```

### 4.5 Atajo: ejecutar todos los siguientes pasos en una sola orden

Si confías en mí y quieres ir al grano:

```bash
export PG_PASSWORD="<la-que-imprimió-deploy.sh>"
bash scripts/post_deploy.sh
```

Esto hace los pasos 5 (parcial — onboarding manual a Arc no), 6, 7 y genera las gráficas locales del primer run on-prem. Para reproducir la comparación WAN-vs-LAN del notebook, sigue además los pasos 8, 9 y 10.

---

## Paso 5 — Onboarding de la VM "on-prem" a Azure Arc

Esto es opcional para el experimento de latencia, pero es lo que hace que el lab sea fiel al patrón híbrido. La VM aparecerá en *Azure Portal → Servers - Azure Arc* como un host hybrido.

### 5.1 Crear un service principal para Arc

```bash
SUB_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)

az ad sp create-for-rbac -n hyblat-arc-onboard \
  --role "Azure Connected Machine Onboarding" \
  --scopes "/subscriptions/$SUB_ID/resourceGroups/rg-hybrid-latency-lab"
```

Salida (apunta `appId` y `password` — la `password` no se vuelve a mostrar):

```json
{
  "appId": "xxxx-xxxx-xxxx-xxxx",
  "displayName": "hyblat-arc-onboard",
  "password": "xxxx-xxxx-xxxx-xxxx",
  "tenant": "0f192c00-..."
}
```

### 5.2 SSH a la VM on-prem y onboarding

```bash
ONPREM_IP=$(az vm show -d -g rg-hybrid-latency-lab -n hyblat-vm-onprem --query publicIps -o tsv)
ssh -i ~/.ssh/hyblat_id_ed25519 azureuser@$ONPREM_IP
```

Dentro de la VM:

```bash
# IMPORTANTE: el agente lee MSFT_ARC_TEST del entorno de systemd, NO del shell.
# Hay que setear la variable a nivel systemd ANTES de instalar el agente.
sudo systemctl set-environment MSFT_ARC_TEST=true

# Instalar el agente
curl -fsSL -o /tmp/install_arc.sh https://aka.ms/azcmagent
sudo bash /tmp/install_arc.sh

# Conectar
sudo azcmagent connect \
  --service-principal-id <APP_ID_DEL_PASO_5.1> \
  --service-principal-secret <PASSWORD_DEL_PASO_5.1> \
  --tenant-id <TENANT_ID> \
  --subscription-id <SUB_ID> \
  --resource-group rg-hybrid-latency-lab \
  --location westeurope \
  --resource-name hyblat-onprem-arc \
  --tags 'lab=hyblat'

# Verificar
sudo azcmagent show
exit
```

Comprueba desde tu local:

```bash
az connectedmachine show -g rg-hybrid-latency-lab -n hyblat-onprem-arc \
  --query "{name:name, status:status, osName:osName, agentVersion:agentVersion}" -o table
# Name                Status     OsName    AgentVersion
# hyblat-onprem-arc   Connected  linux     1.63.x
```

> ⚠️ **Trampa habitual**: si haces `export MSFT_ARC_TEST=true` en el shell antes de `azcmagent connect`, el agente **no la ve** porque corre como systemd unit. La forma correcta es `sudo systemctl set-environment MSFT_ARC_TEST=true`.

---

## Paso 6 — Sembrar la BBDD

Lo hacemos **desde la VM spoke** (LAN, sin latencia añadida) para que la siembra sea rápida.

```bash
RG=rg-hybrid-latency-lab
DN=$(az deployment group list -g $RG --query "[0].name" -o tsv)
PG_FQDN=$(az deployment group show -g $RG -n "$DN" --query properties.outputs.pgFqdn.value -o tsv)
SPOKE_IP=$(az vm show -d -g $RG -n hyblat-vm-spoke --query publicIps -o tsv)

# Copiar seed.py
scp -i ~/.ssh/hyblat_id_ed25519 scripts/seed.py azureuser@$SPOKE_IP:/home/azureuser/

# Instalar deps + sembrar
ssh -i ~/.ssh/hyblat_id_ed25519 azureuser@$SPOKE_IP <<EOF
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip postgresql-client
python3 -m venv ~/latency-lab-venv
source ~/latency-lab-venv/bin/activate
pip install --quiet psycopg[binary]
PG_CONNINFO='host=$PG_FQDN dbname=latencylab user=pgadmin password=$PG_PASSWORD sslmode=require' \
  python ~/seed.py --rows 5000
EOF
```

Salida esperada: `Seeded 5000 rows into table 'items' in 1.42 s`.

---

## Paso 7 — Ejecutar el experimento desde on-prem

### 7.1 Configurar la VM (cambiar hostname, instalar deps, **inyectar 80 ms de netem**)

```bash
APPI_CS=$(az deployment group show -g $RG -n "$DN" --query properties.outputs.appInsightsConnectionString.value -o tsv)
ONPREM_IP=$(az vm show -d -g $RG -n hyblat-vm-onprem --query publicIps -o tsv)

# Copiar scripts
scp -i ~/.ssh/hyblat_id_ed25519 \
  scripts/{setup_onprem.sh,chatty.py,chunky.py,seed.py,run_experiments.sh,latency_probe.py} \
  azureuser@$ONPREM_IP:/tmp/

ssh -i ~/.ssh/hyblat_id_ed25519 azureuser@$ONPREM_IP <<EOF
sudo bash /tmp/setup_onprem.sh '$PG_FQDN' '$PG_PASSWORD' '$APPI_CS' 80
mkdir -p /home/azureuser/latency-lab
mv /tmp/chatty.py /tmp/chunky.py /tmp/seed.py /tmp/run_experiments.sh /tmp/latency_probe.py \
   /home/azureuser/latency-lab/
EOF
```

`setup_onprem.sh` hace:
1. `apt install` python3-venv, dnsutils, postgresql-client, iproute2, mtr, jq, curl
2. `hostnamectl set-hostname db-batch-server` y añade `db-batch-server.corp.local` a `/etc/hosts`
3. Crea alias `pg-prod.corp.local` apuntando a la IP privada del PG (vía DNS resolution)
4. Crea venv en `/home/azureuser/latency-lab/.venv` con `psycopg`, `azure-monitor-opentelemetry`, etc.
5. Escribe `/home/azureuser/latency-lab/.env` (con permisos 600) con las credenciales y la connection string
6. **`tc qdisc add dev eth0 root netem delay 80ms 5ms distribution normal`** — esto es la magia: a partir de aquí, todo el tráfico saliente de la VM paga 80 ms ± 5 ms

### 7.2 Verificar que netem está activo

```bash
ssh -i ~/.ssh/hyblat_id_ed25519 azureuser@$ONPREM_IP "tc qdisc show dev eth0; ping -c 4 pg-prod.corp.local"
```

El ping debe devolver ~80 ms por respuesta. Si ves <1 ms, netem **no se aplicó** — revisa la sección [Solución de problemas](#solución-de-problemas-frecuentes).

### 7.3 Ejecutar el experimento

```bash
ssh -i ~/.ssh/hyblat_id_ed25519 azureuser@$ONPREM_IP \
  "cd /home/azureuser/latency-lab && bash run_experiments.sh 500 3"
```

`run_experiments.sh ITEMS RUNS` corre `RUNS` × chatty + `RUNS` × chunky con `ITEMS` items, escribe un CSV `results-YYYYMMDDHHMMSS.csv` con columnas `workload,run_id,items,roundtrips,duration_ms`.

Tarda **~5 minutos** (3 × 85 s de chatty + 3 × 1 s de chunky + overhead).

Salida final esperada:

```
----- SUMMARY (results-20260505123456.csv) -----
workload,run_id,items,roundtrips,duration_ms
chatty,abc123,500,1003,85462
chatty,def456,500,1003,85211
chatty,ghi789,500,1003,85901
chunky,jkl012,500,4,1162
chunky,mno345,500,4,1148
chunky,pqr678,500,4,1175
```

### 7.4 Descargar resultados

```bash
mkdir -p results/raw
scp -i ~/.ssh/hyblat_id_ed25519 \
  azureuser@$ONPREM_IP:/home/azureuser/latency-lab/results-*.csv \
  results/raw/experiments_onprem-wan.csv
```

(Renombramos a `experiments_onprem-wan.csv` porque `merge_raw_csvs.py` deriva el `env_label` del nombre del fichero.)

---

## Paso 8 — Ejecutar el experimento desde el spoke

Mismo código, mismo dataset, misma BBDD — pero **sin** `tc netem`, ejecutándose dentro del mismo VNet que PG.

```bash
SPOKE_IP=$(az vm show -d -g $RG -n hyblat-vm-spoke --query publicIps -o tsv)

# Copiar scripts
scp -i ~/.ssh/hyblat_id_ed25519 \
  scripts/{chatty.py,chunky.py,run_experiments.sh,latency_probe.py,requirements.txt} \
  azureuser@$SPOKE_IP:/home/azureuser/latency-lab/

# Crear venv y escribir .env (¡SIN netem!)
ssh -i ~/.ssh/hyblat_id_ed25519 azureuser@$SPOKE_IP <<EOF
cd /home/azureuser/latency-lab
python3 -m venv .venv
source .venv/bin/activate
pip install --quiet -r requirements.txt
cat > .env <<ENV
PG_CONNINFO="host=$PG_FQDN dbname=latencylab user=pgadmin password=$PG_PASSWORD sslmode=require"
APPLICATIONINSIGHTS_CONNECTION_STRING="$APPI_CS"
ENV_LABEL="spoke-lan"
ENV
chmod 600 .env
bash run_experiments.sh 500 3
EOF

# Descargar
scp -i ~/.ssh/hyblat_id_ed25519 \
  azureuser@$SPOKE_IP:/home/azureuser/latency-lab/results-*.csv \
  results/raw/experiments_spoke-lan.csv
```

Tarda **~12 segundos** (3 × 2.6 s + 3 × 0.07 s).

---

## Paso 9 — Sonda de latencia

Una métrica más limpia que el experimento entero: 50× `SELECT 1;` reusando la misma conexión, así excluimos el coste de TLS handshake y dejamos el RTT puro.

```bash
# En la VM on-prem
ssh -i ~/.ssh/hyblat_id_ed25519 azureuser@$ONPREM_IP \
  "cd /home/azureuser/latency-lab && source .venv/bin/activate && set -a && . ./.env && set +a && \
   ENV_LABEL=onprem-wan python latency_probe.py --samples 50"
scp -i ~/.ssh/hyblat_id_ed25519 \
  azureuser@$ONPREM_IP:/home/azureuser/latency-lab/latency_probe_onprem.csv \
  results/raw/latency_probe_onprem-wan.csv

# En la VM spoke
ssh -i ~/.ssh/hyblat_id_ed25519 azureuser@$SPOKE_IP \
  "cd /home/azureuser/latency-lab && source .venv/bin/activate && set -a && . ./.env && set +a && \
   ENV_LABEL=spoke-lan python latency_probe.py --samples 50"
scp -i ~/.ssh/hyblat_id_ed25519 \
  azureuser@$SPOKE_IP:/home/azureuser/latency-lab/latency_probe_spoke.csv \
  results/raw/latency_probe_spoke-lan.csv
```

Salida esperada por la sonda:

```
[onprem-wan] 50 samples: min=78.20 ms p50=79.31 ms p95=89.13 ms max=158.40 ms
[spoke-lan]  50 samples: min=0.39 ms p50=0.48 ms p95=0.80 ms max=1.14 ms
```

Eso es el **RTT puro de red**, sin nada del lado aplicativo. Confirma que la diferencia entre los dos entornos es **únicamente** la red.

---

## Paso 10 — Generar el notebook

Localmente, con Python ≥ 3.10:

```bash
pip install pandas matplotlib jupyter nbformat

# Unifica los 4 CSVs crudos en 2 ficheros con la columna env_label
python scripts/merge_raw_csvs.py

# Construye el .ipynb (markdown + cells)
python scripts/build_notebook.py

# Lo ejecuta y deja los outputs embebidos
python -m jupyter nbconvert --to notebook --execute --inplace \
  results/notebook/analysis.ipynb
```

Resultado: `results/notebook/analysis.ipynb` (~260 KB con todas las gráficas embebidas) + 5 PNGs sueltos. Lo puedes abrir directamente en GitHub o en JupyterLab.

---

## Paso 11 — Telemetría en Azure

Mientras el lab está vivo, todo lo que ocurre se escribe a Application Insights. Puedes consultarlo en *Azure Portal → Application Insights → hyblat-ai → Logs*.

Queries listas en [`monitoring/queries.kql`](monitoring/queries.kql). Las más útiles:

```kusto
// 1. ms_per_roundtrip por workload (debería ser ~80 ms en chatty desde on-prem)
dependencies
| where timestamp > ago(1h)
| where name in ("chatty.run", "chunky.run")
| summarize avg_dur_ms = avg(duration),
            avg_rt = avg(toint(customDimensions.roundtrips))
         by name
| extend ms_per_roundtrip = avg_dur_ms / avg_rt

// 2. Round-trips por minuto (la pared de chatty se ve clarísima)
dependencies
| where timestamp > ago(2h)
| where target endswith ".postgres.database.azure.com"
| summarize round_trips = count() by bin(timestamp, 1m)
| render timechart

// 3. RTT del Connection Monitor durante los runs
NWConnectionMonitorTestResult
| where TimeGenerated > ago(2h)
| where TestGroupName == "DefaultTestGroup"
| summarize avg(AvgRoundTripTimeMs) by bin(TimeGenerated, 1m), TestResult
| render timechart
```

Workbook completo: importa [`monitoring/workbook.json`](monitoring/workbook.json) en *Workbooks → + New → Advanced editor*, pega el JSON, *Apply*, *Done editing*, *Save*.

---

## Paso 12 — Limpieza

Cuando termines:

```bash
# Borra todo el resource group (incluye Arc, vWAN, VMs, PG, monitoring)
az group delete -n rg-hybrid-latency-lab --yes --no-wait

# Borra el connected machine de Azure (si el RG aún no se ha borrado del todo)
az connectedmachine delete -g rg-hybrid-latency-lab -n hyblat-onprem-arc --yes 2>/dev/null || true

# Borra el service principal de Arc
az ad sp delete --id $(az ad sp list --display-name hyblat-arc-onboard --query "[0].appId" -o tsv) 2>/dev/null || true
```

El `--no-wait` hace que no bloquee tu shell — el borrado tarda ~10–15 min.

---

## Solución de problemas frecuentes

### `tc netem` no se aplica / el ping sigue siendo <1 ms

```bash
# Comprueba el qdisc actual
sudo tc qdisc show dev eth0
# Si no aparece "netem", reinstala:
sudo tc qdisc del dev eth0 root 2>/dev/null
sudo tc qdisc add dev eth0 root netem delay 80ms 5ms distribution normal
```

Recuerda que **netem se aplica al egress de una interfaz concreta**. Si tu VM tiene varias NICs, cambia `eth0` por la que toque (`ip -o -4 route show default`).

### Arc dice `MSFT_ARC_TEST not set`

```bash
# Mal:
sudo MSFT_ARC_TEST=true azcmagent connect ...
# Bien:
sudo systemctl set-environment MSFT_ARC_TEST=true
sudo azcmagent connect ...
```

### `seed.py` falla con `connection refused`

- ¿La regla de firewall de PG permite tu IP? El despliegue por defecto sólo abre VNet → PG. Si quieres conectarte desde fuera (pruebas locales), añade tu IP:
  ```bash
  MY_IP=$(curl -s https://api.ipify.org)
  PG_NAME=$(az postgres flexible-server list -g rg-hybrid-latency-lab --query "[0].name" -o tsv)
  az postgres flexible-server firewall-rule create -g rg-hybrid-latency-lab \
    -n $PG_NAME --rule-name MyIp --start-ip-address $MY_IP --end-ip-address $MY_IP
  ```

### El experimento se queda colgado en SSH

El `tc netem 80 ms` aplica también al SSH. Si lanzas un comando que produce mucha stdout, la sesión puede tardar 60+ segundos en devolverte el control. Workarounds:
- Usa `nohup ... > log 2>&1 &` y luego haces `tail -f log` desde otra sesión.
- Usa `--no-pager` en `az`.
- Pre-formatea el output con `awk` antes de mandarlo por la red.

### `jupyter` no está en el PATH

```bash
# Funciona aunque no esté en el PATH:
python -m jupyter nbconvert --to notebook --execute --inplace results/notebook/analysis.ipynb
```

### El notebook tira `psycopg.OperationalError: password authentication failed`

El `.env` en la VM tiene la `PG_PASSWORD` antigua de un despliegue anterior. Re-ejecuta `setup_onprem.sh` con el password nuevo:

```bash
ssh azureuser@$ONPREM_IP \
  "sudo bash /tmp/setup_onprem.sh '$PG_FQDN' '$PG_PASSWORD' '$APPI_CS' 80"
```

---

## ¿Y ahora qué?

Si quieres ir más allá:

- Cambia el `LATENCY_MS` en `setup_onprem.sh` a 200 ms (Madrid → Singapur) y vuelve a correr `run_experiments.sh`. Verás que `chatty` se va a ~3 minutos.
- Añade un tercer workload: `chatty_pipelined.py` que use [`psycopg.pipeline`](https://www.psycopg.org/psycopg3/docs/advanced/pipeline.html). Mismas N+1 queries pero pipelined → debería bajar el tiempo casi al de `chunky`.
- Mide el efecto del `sslmode=verify-full` con cert pinning (otro round-trip TLS extra).
- Sustituye el `tc netem` por el real: cambia la VM "on-prem" por una VM de verdad fuera de Azure (o un Raspberry Pi en tu casa) conectado al hub vía VPN S2S — el patrón sigue siendo el mismo, sólo cambia la magnitud del RTT.
