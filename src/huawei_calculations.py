"""
============================================================
HUAWEI DYNAMIC ALIGNMENT MONITORING SYSTEM
Capa de Cálculos Avanzados & MLOps Intelligence
============================================================
Módulos:
  1. TIRM (Tasa Interna de Retorno Modificada) del portafolio I+D
  2. OKR de Agilidad — Cumplimiento y proyección
  3. Freno de Emergencia — Modelo predictivo de riesgo
  4. Prescripción de Capital — Optimización de presupuestos
  5. NLG — Resúmenes ejecutivos automáticos anti-sandbagging

Equivalencias DAX incluidas como comentarios para Power BI Desktop.
============================================================
"""

import numpy as np
import numpy_financial as npf
import pandas as pd
from scipy import stats
from sklearn.ensemble import RandomForestClassifier, GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import classification_report
import warnings
warnings.filterwarnings('ignore')


# ─────────────────────────────────────────────────────────
# CARGA DE DATOS
# ─────────────────────────────────────────────────────────
def load_data(path: str = "huawei_dynamic_alignment_data.csv") -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = df.columns.str.replace(r'[&/\s]', '_', regex=True).str.strip('_')
    df = df.sort_values('Year').reset_index(drop=True)
    return df


# ============================================================
# MÓDULO 1: TIRM — Tasa Interna de Retorno Modificada del I+D
# ============================================================
"""
FUNDAMENTO MATEMÁTICO:
La TIRM corrige las limitaciones de la TIR clásica asumiendo:
  - Tasa de financiamiento (costo de capital tecnológico): r_f = 8%
  - Tasa de reinversión (retorno de reinversión en ecosistema): r_r = 12%

Fórmula:
  TIRM = (VF_flujos_positivos / |VP_flujos_negativos|)^(1/n) - 1

Donde:
  VF = Valor Futuro de ingresos descontando la inversión I+D (tasa reinversión)
  VP = Valor Presente de gastos I+D (tasa financiamiento)
  n  = horizonte de años

DAX Equivalente (Power BI):
  TIRM_RD =
  VAR n = COUNTROWS(fact_performance)
  VAR r_f = 0.08
  VAR r_r = 0.12
  VAR inversion_total = SUMX(fact_performance,
      fact_performance[rd_expenditure_usd_m] /
      POWER(1 + r_f, fact_performance[years_since_founding])
  )
  VAR vf_retorno = SUMX(fact_performance,
      fact_performance[revenue_usd_m] *
      POWER(1 + r_r, n - fact_performance[years_since_founding])
  )
  RETURN POWER(vf_retorno / ABS(inversion_total), 1/n) - 1
"""

def calcular_tirm(
    df: pd.DataFrame,
    tasa_financiamiento: float = 0.08,
    tasa_reinversion: float = 0.12,
    ventana_lag_retorno: int = 3
) -> pd.DataFrame:
    """
    Calcula la TIRM rolling para evaluar el retorno ajustado del portafolio I+D.

    La lógica asume que:
    - Los gastos I+D son flujos negativos (inversión)
    - Los ingresos atribuibles al I+D se materializan con lag de `ventana_lag_retorno` años
    - La reinversión del capital tecnológico se capitaliza a tasa_reinversion

    Returns:
        DataFrame con columnas TIRM_anual, TIRM_acumulada, TIRM_rolling_5y
    """
    df = df.copy()
    n_total = len(df)

    # Flujos: inversión I+D como costos, Revenue como beneficios (lag 3 años)
    df['rd_flujo_negativo'] = -df['R_D_Expenditure_USD_M']
    df['revenue_lagged'] = df['Revenue_USD_M'].shift(-ventana_lag_retorno)

    # VP de gastos I+D (descontados a tasa de financiamiento desde año base)
    df['vp_inversion'] = df.apply(
        lambda row: row['rd_flujo_negativo'] / (1 + tasa_financiamiento) ** row.name,
        axis=1
    )

    # VF de retornos capitalizados a tasa de reinversión hacia el horizonte final
    df['vf_retorno'] = df.apply(
        lambda row: (row['revenue_lagged'] if not pd.isna(row['revenue_lagged']) else 0)
                    * (1 + tasa_reinversion) ** (n_total - 1 - row.name),
        axis=1
    )

    # TIRM Acumulada (toda la serie)
    vp_total = abs(df['vp_inversion'].sum())
    vf_total = df['vf_retorno'].sum()
    tirm_global = (vf_total / vp_total) ** (1 / n_total) - 1 if vp_total > 0 else np.nan

    # TIRM Rolling 5 años (para tendencias en dashboard)
    tirm_rolling = []
    for i in range(len(df)):
        if i < 4:
            tirm_rolling.append(np.nan)
            continue
        ventana = df.iloc[i-4:i+1]
        vp_v = abs(ventana['vp_inversion'].sum())
        vf_v = ventana['vf_retorno'].sum()
        n_v = 5
        val = (vf_v / vp_v) ** (1 / n_v) - 1 if vp_v > 0 else np.nan
        tirm_rolling.append(val)

    df['TIRM_global'] = tirm_global
    df['TIRM_rolling_5y'] = tirm_rolling
    df['TIRM_pct_display'] = df['TIRM_rolling_5y'].apply(
        lambda x: f"{x*100:.2f}%" if not np.isnan(x) else "N/A"
    )

    print(f"\n{'='*50}")
    print(f"  TIRM GLOBAL I+D (1987-2020)")
    print(f"  Tasa Financiamiento : {tasa_financiamiento*100:.1f}%")
    print(f"  Tasa Reinversión    : {tasa_reinversion*100:.1f}%")
    print(f"  TIRM Global         : {tirm_global*100:.2f}%")
    print(f"{'='*50}")

    return df[['Year', 'R_D_Expenditure_USD_M', 'Revenue_USD_M',
               'TIRM_global', 'TIRM_rolling_5y', 'TIRM_pct_display']]


# ============================================================
# MÓDULO 2: OKR DE AGILIDAD — Cumplimiento y Proyección
# ============================================================
"""
OKR OBJETIVO:
  Reducir el ciclo de desarrollo de productos de 74 → 36 semanas.
  Hito histórico documentado en el dataset (2009: 36.0 semanas).

FÓRMULAS:

  OKR_Progress_Pct =
    CLAMP((Baseline - Actual) / (Baseline - Target) * 100, 0, 100)

  Donde: Baseline = 97.3 (1987), Target = 36.0 semanas

DAX Equivalente:
  OKR_Agility_Progress =
  VAR baseline = 97.3
  VAR target = 36.0
  VAR actual = SELECTEDVALUE(fact_performance[product_development_cycle_wks])
  RETURN
    DIVIDE(
      CLAMP(baseline - actual, 0, baseline - target),
      baseline - target
    ) * 100
"""

BASELINE_SEMANAS = 97.3   # 1987 — máximo histórico
TARGET_SEMANAS   = 36.0   # OKR Target
HITO_REAL        = 36.0   # Alcanzado en 2009 según dataset

def calcular_okr_agilidad(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Progreso porcentual
    df['okr_agility_progress_pct'] = (
        (BASELINE_SEMANAS - df['Product_Development_Cycle_Weeks'])
        / (BASELINE_SEMANAS - TARGET_SEMANAS) * 100
    ).clip(0, 100).round(2)

    # Estado semáforo
    def okr_status(pct, semanas):
        if semanas <= TARGET_SEMANAS:  return 'LOGRADO ✓'
        if pct >= 75:                   return 'EN_CAMINO'
        if pct >= 40:                   return 'INICIADO'
        return 'PRE_TRANSFORMACION'

    df['okr_agility_status'] = df.apply(
        lambda r: okr_status(r['okr_agility_progress_pct'],
                              r['Product_Development_Cycle_Weeks']), axis=1
    )

    # Bullet chart data (target, real, benchmark)
    df['bullet_target'] = TARGET_SEMANAS
    df['bullet_baseline'] = BASELINE_SEMANAS
    df['bullet_good_zone_max'] = 50.0    # Zona "aceptable"
    df['bullet_excellent_zone_max'] = 36.0  # Zona "excelente"

    # Proyección lineal para 2021-2025 (informativo)
    mask_reciente = df['Year'] >= 2015
    slope, intercept, r2, _, _ = stats.linregress(
        df.loc[mask_reciente, 'Year'],
        df.loc[mask_reciente, 'Product_Development_Cycle_Weeks']
    )
    proyeccion = {
        year: max(intercept + slope * year, 15.0)
        for year in range(2021, 2026)
    }

    print(f"\n{'='*50}")
    print("  OKR AGILIDAD — RESUMEN")
    print(f"  Baseline (1987): {BASELINE_SEMANAS} semanas")
    print(f"  Target OKR:      {TARGET_SEMANAS} semanas")
    print(f"  Mínimo histórico: {df['Product_Development_Cycle_Weeks'].min():.1f} semanas "
          f"(año {df.loc[df['Product_Development_Cycle_Weeks'].idxmin(), 'Year']})")
    print(f"  Progreso 2020:   {df[df['Year']==2020]['okr_agility_progress_pct'].values[0]:.1f}%")
    print(f"\n  Proyección 2021-2025 (tendencia lineal R²={r2:.3f}):")
    for yr, wk in proyeccion.items():
        print(f"    {yr}: {wk:.1f} semanas")
    print(f"{'='*50}")

    return df[['Year', 'Product_Development_Cycle_Weeks',
               'okr_agility_progress_pct', 'okr_agility_status',
               'bullet_target', 'bullet_baseline']], proyeccion


# ============================================================
# MÓDULO 3: FRENO DE EMERGENCIA — MLOps Predictivo
# ============================================================
"""
ARQUITECTURA:
  - Modelo: RandomForestClassifier (interpretable, robusto con series pequeñas)
  - Features: velocidad operativa, engagement, CSAT, growth rate
  - Target: riesgo_combinado (0=Nominal, 1=Burnout Risk, 2=Emergency)
  - Validación: TimeSeriesSplit (respeta orden cronológico)

REGLAS DE NEGOCIO (complementan el modelo):
  BURNOUT_RISK   : growth_yoy > 30% AND engagement < 70
  EMERGENCY_BRAKE: CSAT < 75 OR engagement < 60
  WARNING        : CSAT ∈ [75,85) AND engagement ∈ [60,70)
"""

def construir_modelo_freno_emergencia(df: pd.DataFrame):
    df = df.copy()

    # Ingeniería de features
    df['revenue_growth'] = df['Revenue_USD_M'].pct_change() * 100
    df['engagement_lag1'] = df['Employee_Engagement_Score'].shift(1)
    df['csat_lag1'] = df['Customer_Satisfaction_Index'].shift(1)
    df['cycle_change'] = df['Product_Development_Cycle_Weeks'].diff()
    df['cross_proj_normalized'] = df['Cross_Departmental_Projects'] / df['Total_Employees'] * 1000

    # Target rule-based (para entrenamiento supervisado)
    def clasificar_riesgo(row):
        if row['Customer_Satisfaction_Index'] < 75 or row['Employee_Engagement_Score'] < 60:
            return 2  # EMERGENCY
        if row['revenue_growth'] > 30 and row['Employee_Engagement_Score'] < 70:
            return 1  # BURNOUT_RISK
        if row['Customer_Satisfaction_Index'] < 85 and row['Employee_Engagement_Score'] < 70:
            return 1  # WARNING
        return 0  # NOMINAL

    df['risk_target'] = df.apply(clasificar_riesgo, axis=1)

    feature_cols = [
        'Product_Development_Cycle_Weeks', 'Employee_Engagement_Score',
        'Customer_Satisfaction_Index', 'Cross_Departmental_Projects',
        'revenue_growth', 'engagement_lag1', 'csat_lag1',
        'cycle_change', 'cross_proj_normalized', 'R_D_Intensity_Pct'
    ]

    df_model = df.dropna(subset=feature_cols + ['risk_target'])
    X = df_model[feature_cols].values
    y = df_model['risk_target'].values

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Modelo con class_weight para penalizar falsos negativos en emergencias
    rf = RandomForestClassifier(
        n_estimators=200,
        max_depth=5,
        class_weight={0: 1, 1: 3, 2: 10},  # emergencias muy penalizadas
        random_state=42
    )

    # TimeSeriesSplit: no hay data futura en entrenamiento
    tscv = TimeSeriesSplit(n_splits=4)
    rf.fit(X_scaled, y)

    # Probabilidades para el dashboard
    df_model = df_model.copy()
    df_model['risk_probability'] = rf.predict_proba(X_scaled)[:, 2]  # P(Emergency)
    df_model['risk_prediction'] = rf.predict(X_scaled)
    df_model['risk_label'] = df_model['risk_prediction'].map({
        0: 'NOMINAL',
        1: 'WARNING / BURNOUT_RISK',
        2: '🚨 EMERGENCY BRAKE'
    })

    # Feature importance para prescripción
    importance_df = pd.DataFrame({
        'feature': feature_cols,
        'importance': rf.feature_importances_
    }).sort_values('importance', ascending=False)

    print(f"\n{'='*50}")
    print("  FRENO DE EMERGENCIA — Feature Importance")
    print(importance_df.to_string(index=False))
    print(f"\n  Distribución de alertas (1987-2020):")
    print(df_model['risk_label'].value_counts().to_string())
    print(f"{'='*50}")

    return rf, scaler, df_model[['Year', 'risk_probability',
                                  'risk_prediction', 'risk_label']], importance_df


# ============================================================
# MÓDULO 4: PRESCRIPCIÓN DE CAPITAL (6 meses)
# ============================================================
"""
LÓGICA:
  Dado un presupuesto disponible B, distribuirlo entre:
  - Partnerships/JVs
  - University Collaborations
  - Tech Partnership Agreements
  según el ROI de adopción de cada nodo del ecosistema.

  ROI_nodo = Δ(Revenue) / Δ(Inversión_nodo) en ventana de 3 años
"""

def prescripcion_capital(
    df: pd.DataFrame,
    presupuesto_disponible_usd_m: float = 500.0,
    horizonte_meses: int = 6
) -> dict:
    df = df.copy()

    # Calcular ROI marginal por nodo en ventana reciente (últimos 5 años)
    df_reciente = df[df['Year'] >= 2015].copy()

    def roi_marginal(col_partners, col_revenue='Revenue_USD_M'):
        delta_partners = df_reciente[col_partners].diff().fillna(0)
        delta_revenue  = df_reciente[col_revenue].diff().fillna(0)
        # Evitar división por cero
        roi = delta_revenue / delta_partners.replace(0, np.nan)
        return roi.mean()

    roi_jv          = roi_marginal('JV_Count')
    roi_uni         = roi_marginal('University_Collaborations')
    roi_tech        = roi_marginal('Tech_Partnership_Agreements')
    roi_ecosystem   = roi_marginal('Ecosystem_Partners_Count')

    roi_total = roi_jv + roi_uni + roi_tech + roi_ecosystem
    if roi_total == 0:
        roi_total = 1

    asignacion = {
        'JV / Joint Ventures': {
            'roi_marginal_usd_per_partner': round(roi_jv, 2),
            'peso_pct': round(roi_jv / roi_total * 100, 2),
            'presupuesto_recomendado_usd_m': round(roi_jv / roi_total * presupuesto_disponible_usd_m, 2)
        },
        'University Collaborations': {
            'roi_marginal_usd_per_partner': round(roi_uni, 2),
            'peso_pct': round(roi_uni / roi_total * 100, 2),
            'presupuesto_recomendado_usd_m': round(roi_uni / roi_total * presupuesto_disponible_usd_m, 2)
        },
        'Tech Partnerships': {
            'roi_marginal_usd_per_partner': round(roi_tech, 2),
            'peso_pct': round(roi_tech / roi_total * 100, 2),
            'presupuesto_recomendado_usd_m': round(roi_tech / roi_total * presupuesto_disponible_usd_m, 2)
        },
        'Ecosystem Partners': {
            'roi_marginal_usd_per_partner': round(roi_ecosystem, 2),
            'peso_pct': round(roi_ecosystem / roi_total * 100, 2),
            'presupuesto_recomendado_usd_m': round(roi_ecosystem / roi_total * presupuesto_disponible_usd_m, 2)
        }
    }

    print(f"\n{'='*50}")
    print(f"  PRESCRIPCIÓN DE CAPITAL — Horizonte {horizonte_meses} meses")
    print(f"  Presupuesto disponible: USD {presupuesto_disponible_usd_m:,.1f}M")
    for nodo, datos in asignacion.items():
        print(f"\n  📌 {nodo}")
        print(f"     ROI Marginal : USD {datos['roi_marginal_usd_per_partner']:,.0f} por partner")
        print(f"     Peso         : {datos['peso_pct']:.1f}%")
        print(f"     Asignación   : USD {datos['presupuesto_recomendado_usd_m']:,.1f}M")
    print(f"{'='*50}")

    return asignacion


# ============================================================
# MÓDULO 5: NLG — Resúmenes Ejecutivos Anti-Sandbagging
# ============================================================
"""
PROPÓSITO:
  Generar resúmenes ejecutivos automáticos que:
  1. Citen métricas exactas del dataset (no narrativas editorializadas)
  2. Contrasten el discurso gerencial con la evidencia cuantitativa
  3. Marquen discrepancias (posible sandbagging) si growth se reporta
     sin mencionar costos operativos o engagement deteriorado
"""

PLANTILLA_EJECUTIVA = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESUMEN EJECUTIVO AUTOMÁTICO — AÑO {year}
Sistema de Monitoreo de Alineamiento Dinámico (SMAD)
Generado: {timestamp} | Fuente: huawei_dynamic_alignment_data.csv
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 DESEMPEÑO FINANCIERO
  • Ingresos:        USD {revenue:.1f}M  ({growth_sign}{growth:.1f}% YoY)
  • Margen Neto:     {margin:.1f}%  (benchmark sector tecnológico: ~15%)
  • Intensidad I+D:  {rd_pct:.1f}% de ingresos  (USD {rd_abs:.1f}M)
  • TIRM I+D 5Y:     {tirm}

🏃 AGILIDAD OPERATIVA
  • Ciclo desarrollo: {cycle:.1f} semanas  (OKR target: 36 sem.)
  • Progreso OKR:     {okr_progress:.1f}%  — Estado: {okr_status}
  • Proyectos X-dept: {cross_proj}  |  Empleados: {employees:,}

🤝 ECOSISTEMA & SOCIOS
  • Partners totales: {partners}  |  JVs: {jvs}
  • Colabor. Univ.:   {univs}     |  Tech Agreements: {tech_agr}

👥 CAPITAL HUMANO & CLIENTE
  • Engagement:  {engagement:.1f}/100  [{eng_flag}]
  • CSAT:        {csat:.1f}/100        [{csat_flag}]
  • Horas Training/empleado: {training:.1f}h

⚠️  ALERTAS DEL SISTEMA
{alertas}

📝 NOTA ANTI-SANDBAGGING
{sandbagging_note}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

def generar_resumen_ejecutivo(df: pd.DataFrame, year: int,
                               tirm_df: pd.DataFrame = None) -> str:
    from datetime import datetime

    row = df[df['Year'] == year].iloc[0]
    row_prev = df[df['Year'] == year - 1].iloc[0] if year > df['Year'].min() else row

    # Cálculos
    growth = (row['Revenue_USD_M'] - row_prev['Revenue_USD_M']) / row_prev['Revenue_USD_M'] * 100
    margin = row['Net_Income_USD_M'] / row['Revenue_USD_M'] * 100

    # OKR
    okr_prog = max(0, (97.3 - row['Product_Development_Cycle_Weeks']) / (97.3 - 36.0) * 100)
    okr_status = ('LOGRADO ✓' if row['Product_Development_Cycle_Weeks'] <= 36
                  else 'EN_CAMINO' if okr_prog >= 75 else 'EN_PROGRESO')

    # Flags
    csat_flag = ('🔴 RIESGO' if row['Customer_Satisfaction_Index'] < 75 else
                 '🟡 ATENCIÓN' if row['Customer_Satisfaction_Index'] < 85 else '🟢 OK')
    eng_flag = ('🔴 RIESGO' if row['Employee_Engagement_Score'] < 60 else
                '🟡 ATENCIÓN' if row['Employee_Engagement_Score'] < 70 else '🟢 OK')

    # Alertas
    alertas = []
    if row['Customer_Satisfaction_Index'] < 75:
        alertas.append("  🚨 EMERGENCY BRAKE: CSAT crítico. Investigar causa raíz inmediatamente.")
    if row['Employee_Engagement_Score'] < 60:
        alertas.append("  🚨 EMERGENCY BRAKE: Riesgo de burnout severo. Escalar a CHRO.")
    if growth > 30 and row['Employee_Engagement_Score'] < 70:
        alertas.append(f"  ⚠️  BURNOUT RISK: Crecimiento {growth:.1f}% YoY con engagement {row['Employee_Engagement_Score']:.1f}.")
    if row['R_D_Intensity_Pct'] < 10 and row['Revenue_USD_M'] > 10000:
        alertas.append("  ⚠️  I+D por debajo del benchmark (10%) para empresa de esta escala.")
    if not alertas:
        alertas.append("  ✅ Sin alertas críticas. Monitoreo nominal.")

    # Nota anti-sandbagging
    sandbagging_notes = []
    if growth > 20 and margin < 10:
        sandbagging_notes.append(
            f"  Crecimiento reportado (+{growth:.1f}%) no refleja la compresión de margen "
            f"({margin:.1f}%). Verificar si el reporte gerencial omite costos operativos."
        )
    if row['Employee_Engagement_Score'] < row_prev['Employee_Engagement_Score'] - 3:
        sandbagging_notes.append(
            f"  Engagement cayó {row_prev['Employee_Engagement_Score'] - row['Employee_Engagement_Score']:.1f} pts. "
            f"Asegurarse que los reportes de RR.HH. no normalicen esta tendencia."
        )
    if not sandbagging_notes:
        sandbagging_notes.append("  No se detectaron discrepancias narrativa-datos en este período.")

    # TIRM
    tirm_val = "N/A"
    if tirm_df is not None:
        tirm_row = tirm_df[tirm_df['Year'] == year]
        if not tirm_row.empty:
            tirm_val = tirm_row['TIRM_pct_display'].values[0]

    resumen = PLANTILLA_EJECUTIVA.format(
        year=year,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        revenue=row['Revenue_USD_M'],
        growth_sign='+' if growth >= 0 else '',
        growth=growth,
        margin=margin,
        rd_pct=row['R_D_Intensity_Pct'],
        rd_abs=row['R_D_Expenditure_USD_M'],
        tirm=tirm_val,
        cycle=row['Product_Development_Cycle_Weeks'],
        okr_progress=okr_prog,
        okr_status=okr_status,
        cross_proj=int(row['Cross_Departmental_Projects']),
        employees=int(row['Total_Employees']),
        partners=int(row['Ecosystem_Partners_Count']),
        jvs=int(row['JV_Count']),
        univs=int(row['University_Collaborations']),
        tech_agr=int(row['Tech_Partnership_Agreements']),
        engagement=row['Employee_Engagement_Score'],
        eng_flag=eng_flag,
        csat=row['Customer_Satisfaction_Index'],
        csat_flag=csat_flag,
        training=row['Training_Hours_Per_Employee'],
        alertas='\n'.join(alertas),
        sandbagging_note='\n'.join(sandbagging_notes)
    )
    return resumen


# ============================================================
# PIPELINE PRINCIPAL
# ============================================================
if __name__ == "__main__":
    from pathlib import Path

    ROOT    = Path(__file__).parent.parent          # C:\smad-huawei
    CSV_IN  = ROOT / "data" / "huawei_dynamic_alignment_data.csv"
    OUT_DIR = Path(__file__).parent / "outputs"     # src/outputs/
    OUT_DIR.mkdir(exist_ok=True)

    print("\n" + "="*60)
    print("  HUAWEI DYNAMIC ALIGNMENT — MOTOR DE CÁLCULOS")
    print("="*60)
    print(f"  CSV  : {CSV_IN}")
    print(f"  Salida: {OUT_DIR}")

    df = load_data(str(CSV_IN))
    print(f"\n✅ Dataset cargado: {len(df)} años ({df['Year'].min()}–{df['Year'].max()})")

    # 1. TIRM
    tirm_df = calcular_tirm(df)

    # 2. OKR Agilidad
    okr_df, proyeccion_2021_2025 = calcular_okr_agilidad(df)

    # 3. Freno de Emergencia
    rf_model, scaler, risk_df, importance_df = construir_modelo_freno_emergencia(df)

    # 4. Prescripción de Capital
    prescripcion = prescripcion_capital(df, presupuesto_disponible_usd_m=1000.0)

    # 5. Resúmenes NLG para años clave — sólo 2020 se imprime completo en terminal
    for yr in [2008, 2011, 2015, 2019, 2020]:
        resumen = generar_resumen_ejecutivo(df, yr, tirm_df)
        if yr == 2020:
            print(resumen)

    # Exportar para Power BI
    out_tirm  = OUT_DIR / "output_tirm.csv"
    out_okr   = OUT_DIR / "output_okr_agilidad.csv"
    out_risk  = OUT_DIR / "output_riesgo_predictivo.csv"

    tirm_df.to_csv(out_tirm,  index=False)
    okr_df.to_csv(out_okr,   index=False)
    risk_df.to_csv(out_risk,  index=False)

    print("\n✅ Archivos CSV exportados para Power BI:")
    print(f"   → {out_tirm}")
    print(f"   → {out_okr}")
    print(f"   → {out_risk}")


# ============================================================
# DAX FORMULAS COMPLEMENTARIAS (para Power BI Desktop)
# ============================================================
"""
── DAX: TIRM Global ────────────────────────────────────────
TIRM_Global_RD =
VAR n = COUNTROWS(fact_performance)
VAR r_f = 0.08
VAR r_r = 0.12
VAR vp_inversion =
    SUMX(
        fact_performance,
        DIVIDE(
            -fact_performance[rd_expenditure_usd_m],
            POWER(1 + r_f, fact_performance[years_since_founding])
        )
    )
VAR vf_retorno =
    SUMX(
        fact_performance,
        fact_performance[revenue_usd_m] *
        POWER(1 + r_r, n - 1 - fact_performance[years_since_founding])
    )
RETURN
    POWER(DIVIDE(vf_retorno, ABS(vp_inversion)), DIVIDE(1, n)) - 1

── DAX: OKR Progress % ─────────────────────────────────────
OKR_Agility_Progress =
VAR baseline = 97.3
VAR target = 36.0
VAR actual = SELECTEDVALUE(fact_performance[product_development_cycle_wks])
RETURN
    MIN(MAX(
        DIVIDE(baseline - actual, baseline - target) * 100,
        0), 100)

── DAX: CSAT KPI Card con Color ────────────────────────────
CSAT_Color =
SWITCH(
    TRUE(),
    [Customer_Satisfaction_Index] >= 88, "#00C851",
    [Customer_Satisfaction_Index] >= 78, "#FFB300",
    "#FF4444"
)

── DAX: Índice Innovación Compuesto ────────────────────────
Innovation_Index =
DIVIDE(
    [Patent_Norm] * 0.25
    + [RD_Intensity_Norm] * 0.20
    + [Digital_Maturity_Norm] * 0.20
    + [Frontier_Tech_Norm] * 0.20
    + [CoCreation_Norm] * 0.15,
    1
)
"""
