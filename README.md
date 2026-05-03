# SMAD Huawei — Sistema de Monitoreo de Alineamiento Dinámico

API REST + Motor de cálculos analíticos sobre el dataset histórico de Huawei (1987-2020).
Desplegable en [Render.com](https://render.com) con un solo clic.

---

## Arquitectura

```
smad-huawei/
├── data/
│   └── huawei_dynamic_alignment_data.csv   # Dataset 34 años (1987-2020)
├── src/
│   ├── huawei_calculations.py              # TIRM, OKR, RandomForest, NLG
│   └── outputs/                            # CSVs generados para Power BI
├── etl/
│   └── load_schema_and_csv.py              # ETL local: schema SQL + carga CSV
├── mlops/
│   ├── main.py                             # API FastAPI (4 endpoints)
│   ├── init_db.py                          # Inicialización DB (idempotente)
│   └── test_endpoints.py                   # Pruebas con httpx
├── huawei_star_schema.sql                  # Star schema: staging → warehouse → analytics
├── requirements.txt
└── render.yaml                             # Blueprint de despliegue en Render
```

### Star Schema (PostgreSQL)

```
staging.huawei_raw
    ↓ ETL
warehouse.dim_time  ──┐
warehouse.dim_org   ──┼──→  warehouse.fact_performance
warehouse.dim_eco   ──┘
    ↓
analytics.v_financial_ecosystem
analytics.v_agility_okr
analytics.v_customer_innovation
analytics.v_ai_emergency_brake
```

---

## API — Endpoints

Base URL local: `http://127.0.0.1:8080`
Base URL Render: `https://smad-huawei-api.onrender.com`

Documentación interactiva: `GET /docs` (Swagger UI)

### `GET /health`
Estado del sistema.
```json
{
  "status": "ok",
  "db_connected": true,
  "model_loaded": true,
  "data_years": "1987–2020",
  "version": "1.0.0"
}
```

### `GET /metrics/{year}`
Métricas SMAD completas del año (1987-2020), leídas desde PostgreSQL.
Devuelve 49 campos: financieros, agilidad, ecosistema, talento, índices compuestos.

```bash
curl http://127.0.0.1:8080/metrics/2020
```

Campos destacados:
| Campo | Descripción |
|---|---|
| `revenue_usd_m` | Ingresos en millones USD |
| `agility_okr_progress_pct` | Progreso OKR reducción ciclo (target 36 sem) |
| `csat_risk_flag` | Semáforo CSAT: GREEN / YELLOW / RED |
| `composite_innovation_index` | Índice compuesto 0-1 (patentes + I+D + digital) |
| `decentralization_index` | Índice de descentralización organizacional |

### `POST /predict`
Clasifica el nivel de riesgo operativo con el modelo **Emergency Brake** (RandomForest, entrenado sobre 1987-2020).

```bash
curl -X POST http://127.0.0.1:8080/predict \
  -H "Content-Type: application/json" \
  -d '{
    "product_development_cycle_weeks": 21.4,
    "employee_engagement_score": 86.1,
    "customer_satisfaction_index": 93.6,
    "cross_departmental_projects": 430,
    "revenue_growth": 10.6,
    "engagement_lag1": 85.2,
    "csat_lag1": 92.0,
    "cycle_change": -1.5,
    "cross_proj_normalized": 2.18,
    "rd_intensity_pct": 15.13
  }'
```

Respuesta:
```json
{
  "risk_level": 0,
  "risk_label": "NOMINAL",
  "emergency_probability": 0.0,
  "warning_probability": 0.0,
  "nominal_probability": 1.0,
  "timestamp": "2026-05-03T18:34:55.173748"
}
```

Niveles de riesgo:
| `risk_level` | `risk_label` | Acción |
|---|---|---|
| 0 | NOMINAL | Monitoreo estándar |
| 1 | WARNING / BURNOUT_RISK | Revisión en 30 días |
| 2 | EMERGENCY BRAKE | Escalado inmediato a C-Suite |

### `GET /summary/{year}`
Resumen ejecutivo NLG automático anti-sandbagging.

```bash
curl http://127.0.0.1:8080/summary/2020
```

---

## Instalación local

### Requisitos
- Python 3.11+
- PostgreSQL 16+ corriendo en localhost:5432

```bash
# 1. Clonar
git clone https://github.com/<tu-usuario>/smad-huawei.git
cd smad-huawei

# 2. Entorno virtual
python -m venv smad-env
smad-env\Scripts\activate          # Windows
# source smad-env/bin/activate     # Linux/Mac

# 3. Dependencias
pip install -r requirements.txt

# 4. Variables de entorno
copy .env.example .env             # editar con tus credenciales PG

# 5. Inicializar base de datos
python mlops/init_db.py

# 6. Arrancar API
uvicorn mlops.main:app --host 127.0.0.1 --port 8080
```

---

## Despliegue en Render

### Un clic con Blueprint
1. Fork este repositorio en GitHub
2. En Render Dashboard: **New → Blueprint**
3. Conectar el repositorio → Render detecta `render.yaml` automáticamente
4. Confirmar: crea el web service + la base de datos PostgreSQL
5. El `init_db.py` se ejecuta en el primer start y carga el schema + datos

### Variables de entorno en Render
`DATABASE_URL` se inyecta automáticamente desde la base de datos del Blueprint.
Las demás variables (`PYTHONUTF8`, `ENVIRONMENT`) están en `render.yaml`.

---

## Módulos de cálculo (`src/huawei_calculations.py`)

| Módulo | Descripción |
|---|---|
| `calcular_tirm()` | TIRM rolling 5Y del portafolio I+D (rf=8%, rr=12%) |
| `calcular_okr_agilidad()` | OKR reducción ciclo 97.3→36 semanas + proyección 2021-2025 |
| `construir_modelo_freno_emergencia()` | RandomForest classifier con TimeSeriesSplit |
| `prescripcion_capital()` | Optimización ROI marginal por nodo de ecosistema |
| `generar_resumen_ejecutivo()` | NLG anti-sandbagging con alertas automáticas |

---

## Outputs para Power BI (`src/outputs/`)

| Archivo | Contenido |
|---|---|
| `output_tirm.csv` | TIRM global y rolling 5Y por año |
| `output_okr_agilidad.csv` | Progreso OKR, estado semáforo, datos bullet chart |
| `output_riesgo_predictivo.csv` | Predicción de riesgo y probabilidades por año |

---

## Licencia
MIT — Ver [LICENSE](LICENSE)
