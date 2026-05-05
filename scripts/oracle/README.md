# Variantes Oracle de los scripts

Esta carpeta contiene la **variante Oracle** de los 4 scripts de prueba de la raíz, para que puedas reutilizar el mismo lab (vWAN + Arc + `tc netem`) contra una BBDD Oracle (Autonomous DB, Database@Azure, on-prem, OCI con peering, etc.).

> ⚠️ **No están probados contra una instancia Oracle real** — el lab desplegado usa PostgreSQL Flexible Server. Los scripts están escritos siguiendo la API estable de [`python-oracledb`](https://python-oracledb.readthedocs.io/) en *thin mode* (sin Instant Client).

## Equivalencia con la versión PostgreSQL

| PostgreSQL (raíz `scripts/`) | Oracle (esta carpeta) | Cambio principal |
|---|---|---|
| `seed.py`           | `seed_oracle.py`           | `BIGSERIAL` → `IDENTITY`; `COPY FROM STDIN` → `cursor.executemany()` con array binding |
| `chatty.py`         | `chatty_oracle.py`         | placeholders `%s` → `:1`; `ON CONFLICT … DO UPDATE` → `MERGE INTO … USING dual` |
| `chunky.py`         | `chunky_oracle.py`         | `cursor.copy()` → `cursor.executemany()` |
| `latency_probe.py`  | `latency_probe_oracle.py`  | `SELECT 1` → `SELECT 1 FROM dual` |
| `run_experiments.sh`| `run_experiments_oracle.sh`| arranca `*_oracle.py` |
| `requirements.txt`  | `requirements-oracle.txt`  | `psycopg[binary]` → `oracledb` + `opentelemetry-instrumentation-dbapi` |

Todo lo demás (tabla de items, lógica chatty/chunky, sonda, formato CSV, telemetría a App Insights) es idéntico, así que **`merge_raw_csvs.py` y `build_notebook.py` valen sin tocar**.

## Variables de entorno

Crea un `.env` en esta carpeta (no se commitea — está en `.gitignore` global):

```bash
ORA_USER="ADMIN"
ORA_PASSWORD="<...>"
# Tres formas válidas de DSN:

# 1) EZConnect simple (Oracle DB self-managed o Database@Azure con private endpoint):
ORA_DSN="db-prod.corp.local:1521/PRODDB"

# 2) tnsnames (Autonomous DB):
ORA_DSN="mydb_high"
# ...y antes de ejecutar:  export TNS_ADMIN=/opt/wallet

# 3) Easy Connect+ con wallet en línea:
ORA_DSN="adb.eu-frankfurt-1.oraclecloud.com:1522/abc123_mydb_high.adb.oraclecloud.com?wallet_location=/opt/wallet"

APPLICATIONINSIGHTS_CONNECTION_STRING="<el del workspace de App Insights>"
ENV_LABEL="onprem-wan"   # o "spoke-lan"
```

## Cómo ejecutarlos

```bash
# Sólo la primera vez:
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-oracle.txt

# Sembrar (5000 filas en items + crea run_log)
python seed_oracle.py --rows 5000

# Sonda de latencia
python latency_probe_oracle.py --samples 50

# Experimento entero (3 chatty + 3 chunky con 500 items cada uno)
bash run_experiments_oracle.sh 500 3
```

Los CSVs generados tienen exactamente las **mismas columnas** que la versión PG, así que para meterlos en el notebook basta con renombrar:

```bash
mv results-oracle-*.csv results/raw/experiments_onprem-wan-oracle.csv
mv latency_probe_oracle.csv results/raw/latency_probe_onprem-wan-oracle.csv
python scripts/merge_raw_csvs.py
python scripts/build_notebook.py
python -m jupyter nbconvert --to notebook --execute --inplace results/notebook/analysis.ipynb
```

## Qué esperar

El patrón **se mantiene**: chatty pagará el RTT por cada item (con netem 80 ms → ~85 s para 500 items), chunky lo hará en 4 round-trips (~1 s).

Diferencias específicas de Oracle a tener en cuenta:

1. **TLS handshake**: contra Autonomous DB con mTLS, abrir conexión cuesta 2 round-trips extra. La sonda los excluye porque reusa una conexión, pero los workloads pagan eso 1 vez al arranque.
2. **Server result-set caching**: si lanzas `SELECT 1 FROM dual` 50 veces seguidas contra una sesión caliente, Oracle puede cachear el plan. No afecta al **network RTT** pero sí dejaría el `min` artificialmente bajo. La sonda incluye un `cur.execute("SELECT 1 FROM dual")` de warmup antes de medir para neutralizarlo.
3. **`autocommit`**: en `oracledb` por defecto **no** está activado. Lo seteamos explícitamente a `True` para igualar el comportamiento de PG y no contar el round-trip extra del COMMIT.
4. **Array DML**: `executemany()` con `batcherrors=True` te permite ver qué filas fallaron sin cancelar el lote — útil si el dataset tiene ruido.

## Si tienes una Autonomous DB Free Tier en OCI

El lab vale para medir Azure→OCI también. Pasos rápidos:

1. Crea la Autonomous DB Free Tier (ATP), descarga el wallet.
2. Sube el wallet a la VM on-prem (`scp wallet.zip azureuser@$ONPREM_IP:/opt/wallet.zip && unzip ...`).
3. `export TNS_ADMIN=/opt/wallet ORA_DSN=mydb_high`.
4. Lanza `seed_oracle.py` y luego `run_experiments_oracle.sh`.

Sin VPN/peering, el RTT Madrid → Frankfurt vía internet pública es ~30–40 ms. Con el `tc netem 80 ms` que pinta el lab encima, total efectivo ~110–120 ms — chatty se va a ~2 minutos.
