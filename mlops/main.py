"""
SMAD Huawei — API FastAPI
Expone métricas, predicción de riesgo y resúmenes NLG sobre el dataset 1987-2020.
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# ─── Rutas del proyecto ───────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent          # C:\smad-huawei
SRC  = ROOT / "src"
sys.path.insert(0, str(SRC))

from huawei_calculations import (            # noqa: E402
    load_data,
    calcular_tirm,
    calcular_okr_agilidad,
    construir_modelo_freno_emergencia,
    generar_resumen_ejecutivo,
)

# ─── Entorno ──────────────────────────────────────────────────────────────────
load_dotenv(ROOT / ".env")

# Render entrega 'postgres://' pero psycopg2 requiere 'postgresql://'
def _fix_url(url: str) -> str:
    if url and url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url

# Render inyecta DATABASE_URL completa; localmente usamos vars individuales
_DATABASE_URL = _fix_url(os.getenv("DATABASE_URL", ""))
DB_CONFIG = dict(
    host=os.getenv("DB_HOST", "127.0.0.1"),
    port=int(os.getenv("DB_PORT", 5432)),
    dbname=os.getenv("DB_NAME", "huawei_smad"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
)

CSV_PATH = ROOT / "data" / "huawei_dynamic_alignment_data.csv"

# ─── Estado global de la aplicación ──────────────────────────────────────────
class AppState:
    df         = None   # DataFrame completo
    tirm_df    = None   # DataFrame TIRM
    rf_model   = None   # RandomForestClassifier entrenado
    scaler     = None   # StandardScaler
    risk_df    = None   # Predicciones históricas
    feature_cols: list[str] = [
        "Product_Development_Cycle_Weeks", "Employee_Engagement_Score",
        "Customer_Satisfaction_Index", "Cross_Departmental_Projects",
        "revenue_growth", "engagement_lag1", "csat_lag1",
        "cycle_change", "cross_proj_normalized", "R_D_Intensity_Pct",
    ]

state = AppState()


# ─── Lifespan: carga modelo al arrancar ───────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n[SMAD] Iniciando carga de modelos...")

    state.df      = load_data(str(CSV_PATH))
    state.tirm_df = calcular_tirm(state.df)

    calcular_okr_agilidad(state.df)   # calentamos caches internas, salida no requerida

    state.rf_model, state.scaler, state.risk_df, _ = \
        construir_modelo_freno_emergencia(state.df)

    print(f"[SMAD] Modelo RF cargado — {len(state.df)} años de datos (1987-2020)")
    print(f"[SMAD] API lista en http://127.0.0.1:8000\n")
    yield
    print("[SMAD] Apagando API.")


# ─── Aplicación ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="SMAD Huawei — API de Monitoreo",
    description="Métricas, predicción de riesgo y resúmenes NLG del dataset 1987-2020.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:8080",
        "https://app.powerbi.com",
        "https://api.powerbi.com",
        "https://analysis.windows.net",
    ],
    allow_origin_regex=r"https://.*\.powerbi\.com",
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ─── Helpers DB ──────────────────────────────────────────────────────────────
def get_db_conn():
    if _DATABASE_URL:                          # Render / producción
        return psycopg2.connect(_DATABASE_URL)
    return psycopg2.connect(**DB_CONFIG)       # local con .env vars


def db_query(sql: str, params: tuple = ()) -> list[dict]:
    with get_db_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


# ─── Modelos Pydantic ─────────────────────────────────────────────────────────
class PredictRequest(BaseModel):
    product_development_cycle_weeks: float = Field(..., ge=0, le=200,
        description="Semanas actuales del ciclo de desarrollo (OKR target: 36)")
    employee_engagement_score: float       = Field(..., ge=0, le=100)
    customer_satisfaction_index: float     = Field(..., ge=0, le=100)
    cross_departmental_projects: int       = Field(..., ge=0)
    revenue_growth: float                  = Field(...,
        description="Crecimiento YoY de ingresos en %")
    engagement_lag1: float                 = Field(..., ge=0, le=100,
        description="Engagement del año anterior")
    csat_lag1: float                       = Field(..., ge=0, le=100,
        description="CSAT del año anterior")
    cycle_change: float                    = Field(...,
        description="Δ semanas vs año anterior (negativo = mejora)")
    cross_proj_normalized: float           = Field(...,
        description="Proyectos X-dept por cada 1,000 empleados")
    rd_intensity_pct: float                = Field(..., ge=0,
        description="I+D como % de ingresos")


class PredictResponse(BaseModel):
    risk_level: int
    risk_label: str
    emergency_probability: float
    warning_probability: float
    nominal_probability: float
    timestamp: str


class HealthResponse(BaseModel):
    status: str
    db_connected: bool
    model_loaded: bool
    data_years: str
    timestamp: str
    version: str


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/dashboard", tags=["Dashboard"], include_in_schema=False)
def dashboard():
    """Sirve el dashboard HTML autocontenido (Chart.js + 4 tabs)."""
    path = ROOT / "dashboard" / "index.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Dashboard no encontrado.")
    return HTMLResponse(content=path.read_text(encoding="utf-8"))


@app.get("/debug/db", tags=["Sistema"], include_in_schema=False)
def debug_db():
    """Diagnóstico de conexión DB — solo para troubleshooting, remover en producción."""
    url_present = bool(_DATABASE_URL)
    url_preview = (_DATABASE_URL[:30] + "...") if _DATABASE_URL else "NOT SET"
    err = None
    try:
        db_query("SELECT 1")
        connected = True
    except Exception as exc:
        connected = False
        err = str(exc)
    return {
        "database_url_set": url_present,
        "database_url_preview": url_preview,
        "connected": connected,
        "error": err,
    }


@app.get("/health", response_model=HealthResponse, tags=["Sistema"])
def health():
    """Estado del sistema: conectividad DB y modelo ML."""
    db_ok = False
    try:
        db_query("SELECT 1")
        db_ok = True
    except Exception:
        pass

    return HealthResponse(
        status="ok" if db_ok and state.rf_model is not None else "degraded",
        db_connected=db_ok,
        model_loaded=state.rf_model is not None,
        data_years=f"{int(state.df['Year'].min())}–{int(state.df['Year'].max())}" if state.df is not None else "N/A",
        timestamp=datetime.utcnow().isoformat(),
        version="1.0.0",
    )


@app.get("/metrics/{year}", tags=["Datos"])
def metrics(year: int):
    """
    Métricas SMAD completas del año solicitado, leídas desde PostgreSQL.
    Incluye datos de fact_performance, dim_time, dim_organization y dim_ecosystem.
    """
    if year < 1987 or year > 2020:
        raise HTTPException(status_code=400, detail="Año fuera de rango (1987-2020).")

    rows = db_query(
        """
        SELECT
            dt.year,
            dt.strategic_era,
            dt.transformation_phase,
            dt.is_crisis_year,

            fp.revenue_usd_m,
            fp.net_income_usd_m,
            fp.total_assets_usd_m,
            fp.rd_expenditure_usd_m,
            fp.rd_intensity_pct,
            fp.revenue_yoy_growth_pct,
            fp.rd_roi_simple,
            fp.income_margin_pct,
            fp.patent_applications_filed,
            fp.new_products_launched,
            fp.services_revenue_share_pct,
            fp.government_credit_lines_usd_m,
            fp.geopolitical_risk_score,

            fp.international_sales_pct,
            fp.emerging_markets_sales_pct,
            fp.developed_markets_sales_pct,

            fp.product_development_cycle_wks,
            fp.cross_departmental_projects,
            fp.agility_okr_progress_pct,

            fp.customer_satisfaction_index,
            fp.csat_risk_flag,
            fp.customer_cocreation_projects,
            fp.customized_solutions_count,
            fp.service_24_7_coverage_pct,

            fp.employee_engagement_score,
            fp.engagement_risk_flag,

            fp.digital_maturity_score,
            fp.frontier_tech_research_index,
            fp.brand_premium_index,
            fp.analyst_strategy_clarity,
            fp.composite_innovation_index,

            dorg.total_employees,
            dorg.international_employees_pct,
            dorg.countries_with_presence,
            dorg.frontline_decision_authority,
            dorg.training_hours_per_employee,
            dorg.organizational_structure_type,
            dorg.decentralization_index,

            dec.strategic_partnerships_count,
            dec.jv_count,
            dec.university_collaborations,
            dec.tech_partnership_agreements,
            dec.ecosystem_partners_count,
            dec.ecosystem_density_index,
            dec.knowledge_network_score
        FROM warehouse.fact_performance fp
        JOIN warehouse.dim_time         dt   USING (time_key)
        JOIN warehouse.dim_organization dorg USING (org_key)
        JOIN warehouse.dim_ecosystem    dec  USING (ecosystem_key)
        WHERE dt.year = %s
        """,
        (year,),
    )

    if not rows:
        raise HTTPException(status_code=404, detail=f"No hay datos para el año {year}.")

    # Convertir Decimal → float para serialización JSON limpia
    row: dict[str, Any] = rows[0]
    return {
        k: float(v) if hasattr(v, "__float__") and not isinstance(v, (bool, int)) else v
        for k, v in row.items()
    }


@app.post("/predict", response_model=PredictResponse, tags=["ML"])
def predict(payload: PredictRequest):
    """
    Clasifica el nivel de riesgo operativo usando el modelo Emergency Brake
    (RandomForest, entrenado sobre dataset 1987-2020).

    Niveles:
      0 → NOMINAL
      1 → WARNING / BURNOUT_RISK
      2 → EMERGENCY BRAKE
    """
    if state.rf_model is None:
        raise HTTPException(status_code=503, detail="Modelo no disponible.")

    feature_vector = np.array([[
        payload.product_development_cycle_weeks,
        payload.employee_engagement_score,
        payload.customer_satisfaction_index,
        payload.cross_departmental_projects,
        payload.revenue_growth,
        payload.engagement_lag1,
        payload.csat_lag1,
        payload.cycle_change,
        payload.cross_proj_normalized,
        payload.rd_intensity_pct,
    ]])

    X_scaled   = state.scaler.transform(feature_vector)
    prediction = int(state.rf_model.predict(X_scaled)[0])
    probas     = state.rf_model.predict_proba(X_scaled)[0]

    label_map = {
        0: "NOMINAL",
        1: "WARNING / BURNOUT_RISK",
        2: "EMERGENCY BRAKE",
    }

    # predict_proba puede tener 2 o 3 clases según los datos de entrenamiento
    n_classes = len(probas)
    p_nominal   = float(probas[0]) if n_classes > 0 else 0.0
    p_warning   = float(probas[1]) if n_classes > 1 else 0.0
    p_emergency = float(probas[2]) if n_classes > 2 else 0.0

    return PredictResponse(
        risk_level=prediction,
        risk_label=label_map.get(prediction, "UNKNOWN"),
        emergency_probability=round(p_emergency, 4),
        warning_probability=round(p_warning, 4),
        nominal_probability=round(p_nominal, 4),
        timestamp=datetime.utcnow().isoformat(),
    )


@app.get("/summary/{year}", tags=["NLG"])
def summary(year: int):
    """
    Resumen ejecutivo NLG automático para el año solicitado.
    Incluye métricas clave, alertas del sistema y nota anti-sandbagging.
    """
    if year < 1987 or year > 2020:
        raise HTTPException(status_code=400, detail="Año fuera de rango (1987-2020).")

    if state.df is None:
        raise HTTPException(status_code=503, detail="Dataset no cargado.")

    if year not in state.df["Year"].values:
        raise HTTPException(status_code=404, detail=f"Año {year} no encontrado en el dataset.")

    texto = generar_resumen_ejecutivo(state.df, year, state.tirm_df)
    return {"year": year, "summary": texto}
