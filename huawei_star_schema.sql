-- ============================================================
-- HUAWEI DYNAMIC ALIGNMENT MONITORING SYSTEM
-- SQL: Star Schema + ETL desde dataset crudo (1987-2020)
-- Arquitectura: Snowflake-compatible / BigQuery / PostgreSQL 14+
-- Autor: Arquitecto Senior BI — Metodología AIDA
-- ============================================================


-- ============================================================
-- PASO 0: STAGING — Carga raw y limpieza de tipos
-- ============================================================
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS warehouse;
CREATE SCHEMA IF NOT EXISTS analytics;

DROP TABLE IF EXISTS staging.huawei_raw;
CREATE TABLE staging.huawei_raw (
    Year                          SMALLINT,
    Revenue_USD_M                 NUMERIC(14,4),
    Net_Income_USD_M              NUMERIC(14,4),
    Total_Assets_USD_M            NUMERIC(14,4),
    RD_Expenditure_USD_M          NUMERIC(14,4),   -- renombrado: R&D -> RD
    RD_Intensity_Pct              NUMERIC(7,4),   -- fix: valores hasta 100.0 requieren p≥7
    Patent_Applications_Filed     INTEGER,
    Frontier_Tech_Research_Index  NUMERIC(6,2),
    Total_Employees               INTEGER,
    International_Employees_Pct   NUMERIC(7,4),
    Countries_with_Presence       SMALLINT,
    International_Sales_Pct       NUMERIC(7,4),
    Emerging_Markets_Sales_Pct    NUMERIC(7,4),
    Developed_Markets_Sales_Pct   NUMERIC(7,4),
    Services_Revenue_Share_Pct    NUMERIC(7,4),
    Customized_Solutions_Count    INTEGER,
    Customer_CoCreation_Projects  INTEGER,
    Customer_Satisfaction_Index   NUMERIC(6,2),
    Service_24_7_Coverage_Pct     NUMERIC(7,4),
    Product_Development_Cycle_Wks NUMERIC(6,2),
    Cross_Departmental_Projects   INTEGER,
    Frontline_Decision_Authority  NUMERIC(6,2),
    Organizational_Structure_Type VARCHAR(20),
    Strategic_Partnerships_Count  INTEGER,
    JV_Count                      INTEGER,
    University_Collaborations     INTEGER,
    Tech_Partnership_Agreements   INTEGER,
    Ecosystem_Partners_Count      INTEGER,
    Country_of_Origin_Perception  NUMERIC(6,2),
    Analyst_Strategy_Clarity      NUMERIC(6,2),
    Brand_Premium_Index           NUMERIC(6,2),
    Government_Credit_Lines_USD_M NUMERIC(14,4),
    Geopolitical_Risk_Score       NUMERIC(6,2),
    Employee_Engagement_Score     NUMERIC(6,2),
    Training_Hours_Per_Employee   NUMERIC(6,2),
    New_Products_Launched         INTEGER,
    Digital_Maturity_Score        NUMERIC(6,2)
);

-- ============================================================
-- PASO 1: DIMENSIONES (Dim Tables)
-- ============================================================

-- DIM_TIME: Granularidad anual con bandas estratégicas
DROP TABLE IF EXISTS warehouse.dim_time;
CREATE TABLE warehouse.dim_time (
    time_key               SERIAL PRIMARY KEY,
    year                   SMALLINT NOT NULL UNIQUE,
    decade                 SMALLINT GENERATED ALWAYS AS (FLOOR(year / 10) * 10) STORED,
    strategic_era          VARCHAR(50),   -- fix: valores hasta 38 chars
    transformation_phase   VARCHAR(25),  -- Centralizado / Transitional / Descentralizado
    years_since_founding   SMALLINT GENERATED ALWAYS AS (year - 1987) STORED,
    is_crisis_year         BOOLEAN       -- 2001 dotcom, 2008 financiero
);

INSERT INTO warehouse.dim_time (year, strategic_era, transformation_phase, is_crisis_year)
SELECT
    year,
    CASE
        WHEN year BETWEEN 1987 AND 1995 THEN 'Fase 1: Supervivencia y Bootstrapping'
        WHEN year BETWEEN 1996 AND 2003 THEN 'Fase 2: Expansión Regional Agresiva'
        WHEN year BETWEEN 2004 AND 2010 THEN 'Fase 3: Globalización y Escala'
        WHEN year BETWEEN 2011 AND 2016 THEN 'Fase 4: Liderazgo en Ecosistema'
        WHEN year BETWEEN 2017 AND 2020 THEN 'Fase 5: Resiliencia Geopolítica'
    END,
    Organizational_Structure_Type,
    CASE WHEN year IN (2001, 2008, 2009) THEN TRUE ELSE FALSE END
FROM staging.huawei_raw;


-- DIM_ORGANIZATION: Estructura organizacional por año
DROP TABLE IF EXISTS warehouse.dim_organization;
CREATE TABLE warehouse.dim_organization (
    org_key                       SERIAL PRIMARY KEY,
    year                          SMALLINT NOT NULL,
    total_employees               INTEGER,
    international_employees_pct   NUMERIC(7,4),
    countries_with_presence       SMALLINT,
    frontline_decision_authority  NUMERIC(6,2),
    training_hours_per_employee   NUMERIC(6,2),
    organizational_structure_type VARCHAR(20),
    decentralization_index        NUMERIC(6,3) -- calculado
);

INSERT INTO warehouse.dim_organization
SELECT
    NEXTVAL('warehouse.dim_organization_org_key_seq'),
    year,
    Total_Employees,
    International_Employees_Pct,
    Countries_with_Presence,
    Frontline_Decision_Authority,
    Training_Hours_Per_Employee,
    Organizational_Structure_Type,
    -- Índice compuesto: autonomía + internacionalización + cobertura geográfica
    ROUND(
        (Frontline_Decision_Authority / 100.0) * 0.4
        + (International_Employees_Pct / 100.0) * 0.3
        + LEAST(Countries_with_Presence / 175.0, 1.0) * 0.3
    , 3)
FROM staging.huawei_raw;


-- DIM_ECOSYSTEM: Socios, JVs, Universidades
DROP TABLE IF EXISTS warehouse.dim_ecosystem;
CREATE TABLE warehouse.dim_ecosystem (
    ecosystem_key                SERIAL PRIMARY KEY,
    year                         SMALLINT NOT NULL,
    strategic_partnerships_count INTEGER,
    jv_count                     INTEGER,
    university_collaborations    INTEGER,
    tech_partnership_agreements  INTEGER,
    ecosystem_partners_count     INTEGER,
    ecosystem_density_index      NUMERIC(8,4), -- partners / países
    knowledge_network_score      NUMERIC(6,3)  -- compuesto I+D externo
);

INSERT INTO warehouse.dim_ecosystem
SELECT
    NEXTVAL('warehouse.dim_ecosystem_ecosystem_key_seq'),
    r.year,
    r.Strategic_Partnerships_Count,
    r.JV_Count,
    r.University_Collaborations,
    r.Tech_Partnership_Agreements,
    r.Ecosystem_Partners_Count,
    -- Densidad: partners por país presente
    ROUND(NULLIF(r.Ecosystem_Partners_Count, 0)::NUMERIC /
          NULLIF(r.Countries_with_Presence, 0), 4),
    -- Knowledge Network: peso hacia universidades y tech-partnerships
    ROUND(
        (LEAST(r.University_Collaborations / 225.0, 1.0)) * 0.5
        + (LEAST(r.Tech_Partnership_Agreements / 315.0, 1.0)) * 0.3
        + (LEAST(r.JV_Count / 105.0, 1.0)) * 0.2
    , 3)
FROM staging.huawei_raw r;


-- ============================================================
-- PASO 2: TABLA DE HECHOS CENTRAL (Fact_Performance)
-- ============================================================
DROP TABLE IF EXISTS warehouse.fact_performance;
CREATE TABLE warehouse.fact_performance (
    perf_key                       BIGSERIAL PRIMARY KEY,

    -- Claves foráneas
    time_key                       INTEGER REFERENCES warehouse.dim_time(time_key),
    org_key                        INTEGER REFERENCES warehouse.dim_organization(org_key),
    ecosystem_key                  INTEGER REFERENCES warehouse.dim_ecosystem(ecosystem_key),

    -- === FINANCIEROS ===
    revenue_usd_m                  NUMERIC(14,4),
    net_income_usd_m               NUMERIC(14,4),
    total_assets_usd_m             NUMERIC(14,4),
    rd_expenditure_usd_m           NUMERIC(14,4),
    rd_intensity_pct               NUMERIC(7,4),
    government_credit_lines_usd_m  NUMERIC(14,4),
    patent_applications_filed      INTEGER,
    new_products_launched          INTEGER,
    services_revenue_share_pct     NUMERIC(7,4),

    -- === MERCADOS ===
    international_sales_pct        NUMERIC(7,4),
    emerging_markets_sales_pct     NUMERIC(7,4),
    developed_markets_sales_pct    NUMERIC(7,4),

    -- === AGILIDAD OPERATIVA ===
    product_development_cycle_wks  NUMERIC(6,2),
    cross_departmental_projects    INTEGER,

    -- === CLIENTE E INNOVACIÓN ===
    customer_satisfaction_index    NUMERIC(6,2),
    customer_cocreation_projects   INTEGER,
    customized_solutions_count     INTEGER,
    service_24_7_coverage_pct      NUMERIC(7,4),

    -- === TALENTO ===
    employee_engagement_score      NUMERIC(6,2),

    -- === ÍNDICES EXTERNOS ===
    digital_maturity_score         NUMERIC(6,2),
    geopolitical_risk_score        NUMERIC(6,2),
    frontier_tech_research_index   NUMERIC(6,2),
    brand_premium_index            NUMERIC(6,2),
    analyst_strategy_clarity       NUMERIC(6,2),

    -- === MÉTRICAS DERIVADAS (calculadas en ETL) ===
    revenue_yoy_growth_pct         NUMERIC(8,4),
    rd_roi_simple                  NUMERIC(8,4),   -- Revenue / RD gasto acum
    income_margin_pct              NUMERIC(8,4),
    agility_okr_progress_pct       NUMERIC(8,4),   -- puede superar 100% si ciclo < 36 sem
    csat_risk_flag                 VARCHAR(10),     -- GREEN / YELLOW / RED
    engagement_risk_flag           VARCHAR(10),
    composite_innovation_index     NUMERIC(6,4)
);

INSERT INTO warehouse.fact_performance
SELECT
    NEXTVAL('warehouse.fact_performance_perf_key_seq'),
    dt.time_key,
    dorg.org_key,
    dec.ecosystem_key,

    -- Financieros raw
    r.Revenue_USD_M,
    r.Net_Income_USD_M,
    r.Total_Assets_USD_M,
    r.RD_Expenditure_USD_M,
    r.RD_Intensity_Pct,
    r.Government_Credit_Lines_USD_M,
    r.Patent_Applications_Filed,
    r.New_Products_Launched,
    r.Services_Revenue_Share_Pct,

    -- Mercados raw
    r.International_Sales_Pct,
    r.Emerging_Markets_Sales_Pct,
    r.Developed_Markets_Sales_Pct,

    -- Agilidad raw
    r.Product_Development_Cycle_Wks,
    r.Cross_Departmental_Projects,

    -- Cliente raw
    r.Customer_Satisfaction_Index,
    r.Customer_CoCreation_Projects,
    r.Customized_Solutions_Count,
    r.Service_24_7_Coverage_Pct,

    -- Talento raw
    r.Employee_Engagement_Score,

    -- Índices externos raw
    r.Digital_Maturity_Score,
    r.Geopolitical_Risk_Score,
    r.Frontier_Tech_Research_Index,
    r.Brand_Premium_Index,
    r.Analyst_Strategy_Clarity,

    -- === MÉTRICAS DERIVADAS ===

    -- 1. Revenue YoY Growth %
    ROUND(
        (r.Revenue_USD_M - LAG(r.Revenue_USD_M) OVER (ORDER BY r.Year))
        / NULLIF(LAG(r.Revenue_USD_M) OVER (ORDER BY r.Year), 0) * 100
    , 4),

    -- 2. RD ROI Simple (Revenue generado por cada USD invertido en I+D, lag 3 años)
    ROUND(
        r.Revenue_USD_M /
        NULLIF(
            SUM(r.RD_Expenditure_USD_M) OVER (
                ORDER BY r.Year ROWS BETWEEN 3 PRECEDING AND CURRENT ROW
            ), 0
        )
    , 4),

    -- 3. Margen Neto
    ROUND(r.Net_Income_USD_M / NULLIF(r.Revenue_USD_M, 0) * 100, 4),

    -- 4. OKR Agilidad: Reducción de ciclos (baseline=97.3 semanas 1987, target=36)
    --    Progreso = (97.3 - Actual) / (97.3 - 36) * 100
    ROUND(
        GREATEST(0,
            (97.3 - r.Product_Development_Cycle_Wks) / (97.3 - 36.0) * 100
        )
    , 4),

    -- 5. CSAT Risk Flag (umbral: <75 RED, 75-85 YELLOW, >85 GREEN)
    CASE
        WHEN r.Customer_Satisfaction_Index < 75  THEN 'RED'
        WHEN r.Customer_Satisfaction_Index < 85  THEN 'YELLOW'
        ELSE 'GREEN'
    END,

    -- 6. Engagement Risk Flag (umbral: <60 RED, 60-70 YELLOW, >70 GREEN)
    CASE
        WHEN r.Employee_Engagement_Score < 60  THEN 'RED'
        WHEN r.Employee_Engagement_Score < 70  THEN 'YELLOW'
        ELSE 'GREEN'
    END,

    -- 7. Índice de Innovación Compuesto
    --    Peso: Patentes(25%) + I+D%(20%) + Digital Maturity(20%) +
    --          Frontier Tech(20%) + CoCreation(15%)
    ROUND(
        (LEAST(r.Patent_Applications_Filed / 17360.0, 1.0) * 0.25)
        + (LEAST(r.RD_Intensity_Pct / 20.0, 1.0)           * 0.20)
        + (LEAST(r.Digital_Maturity_Score / 100.0, 1.0)    * 0.20)
        + (LEAST(r.Frontier_Tech_Research_Index / 100.0, 1.0) * 0.20)
        + (LEAST(r.Customer_CoCreation_Projects / 220.0, 1.0) * 0.15)
    , 4)

FROM staging.huawei_raw r
JOIN warehouse.dim_time dt ON r.Year = dt.year
JOIN warehouse.dim_organization dorg ON r.Year = dorg.year
JOIN warehouse.dim_ecosystem dec ON r.Year = dec.year;


-- ============================================================
-- PASO 3: VISTAS ANALÍTICAS PARA POWER BI (Capa Semántica)
-- ============================================================

-- VISTA 1: Tab 1 — Visión Ecosistémica y Financiera
CREATE OR REPLACE VIEW analytics.v_financial_ecosystem AS
SELECT
    dt.year,
    dt.strategic_era,
    dt.transformation_phase,
    fp.revenue_usd_m,
    fp.net_income_usd_m,
    fp.rd_expenditure_usd_m,
    fp.rd_intensity_pct,
    fp.revenue_yoy_growth_pct,
    fp.rd_roi_simple,
    fp.income_margin_pct,
    fp.patent_applications_filed,
    fp.international_sales_pct,
    fp.emerging_markets_sales_pct,
    fp.developed_markets_sales_pct,
    fp.services_revenue_share_pct,
    fp.government_credit_lines_usd_m,
    fp.geopolitical_risk_score,
    dec.ecosystem_partners_count,
    dec.ecosystem_density_index,
    -- Acumulado I+D para cálculo TIRM (exportado a Python/DAX)
    SUM(fp.rd_expenditure_usd_m) OVER (ORDER BY dt.year) AS rd_cumulative_usd_m
FROM warehouse.fact_performance fp
JOIN warehouse.dim_time dt USING (time_key)
JOIN warehouse.dim_ecosystem dec USING (ecosystem_key)
ORDER BY dt.year;


-- VISTA 2: Tab 2 — Agilidad Operativa
CREATE OR REPLACE VIEW analytics.v_agility_okr AS
SELECT
    dt.year,
    dt.strategic_era,
    dt.transformation_phase,
    fp.product_development_cycle_wks,
    fp.cross_departmental_projects,
    fp.employee_engagement_score,
    fp.engagement_risk_flag,
    fp.agility_okr_progress_pct,
    dorg.frontline_decision_authority,
    dorg.decentralization_index,
    dorg.training_hours_per_employee,
    dorg.total_employees,
    -- Hito histórico: 74 semanas a 36 semanas (2009-2019)
    CASE
        WHEN fp.product_development_cycle_wks <= 36   THEN 'OKR_LOGRADO'
        WHEN fp.product_development_cycle_wks <= 50   THEN 'OKR_EN_CAMINO'
        WHEN fp.product_development_cycle_wks <= 74   THEN 'OKR_INICIADO'
        ELSE 'PRE_TRANSFORMACION'
    END AS okr_agility_status,
    -- Correlación cruzada para scatter chart
    fp.cross_departmental_projects * 1.0 / NULLIF(dorg.total_employees, 0) * 1000
        AS cross_proj_per_1k_employees
FROM warehouse.fact_performance fp
JOIN warehouse.dim_time dt USING (time_key)
JOIN warehouse.dim_organization dorg USING (org_key)
ORDER BY dt.year;


-- VISTA 3: Tab 3 — Innovación Centrada en el Cliente
CREATE OR REPLACE VIEW analytics.v_customer_innovation AS
SELECT
    dt.year,
    dt.strategic_era,
    fp.customer_satisfaction_index,
    fp.csat_risk_flag,
    fp.customer_cocreation_projects,
    fp.customized_solutions_count,
    fp.service_24_7_coverage_pct,
    fp.composite_innovation_index,
    dec.university_collaborations,
    dec.tech_partnership_agreements,
    dec.knowledge_network_score,
    dorg.international_employees_pct,
    -- Velocidad de co-creación YoY
    fp.customer_cocreation_projects
        - LAG(fp.customer_cocreation_projects) OVER (ORDER BY dt.year)
        AS cocreation_delta_yoy,
    -- CSAT con banda semáforo para formato condicional Power BI
    CASE
        WHEN fp.customer_satisfaction_index >= 88 THEN '#00C851'  -- Verde corporativo
        WHEN fp.customer_satisfaction_index >= 78 THEN '#FFB300'  -- Ámbar
        ELSE '#FF4444'                                             -- Rojo alerta
    END AS csat_color_hex,
    fp.brand_premium_index,
    fp.digital_maturity_score
FROM warehouse.fact_performance fp
JOIN warehouse.dim_time dt USING (time_key)
JOIN warehouse.dim_ecosystem dec USING (ecosystem_key)
JOIN warehouse.dim_organization dorg USING (org_key)
ORDER BY dt.year;


-- VISTA 4: AI Layer — Freno de Emergencia (datos para modelo predictivo)
CREATE OR REPLACE VIEW analytics.v_ai_emergency_brake AS
SELECT
    dt.year,
    fp.product_development_cycle_wks,
    fp.employee_engagement_score,
    fp.customer_satisfaction_index,
    fp.cross_departmental_projects,
    fp.revenue_yoy_growth_pct,
    fp.rd_intensity_pct,
    fp.csat_risk_flag,
    fp.engagement_risk_flag,
    -- Señal de alarma combinada (usada por modelo RandomForest en capa MLOps)
    CASE
        WHEN fp.csat_risk_flag = 'RED'
          OR fp.engagement_risk_flag = 'RED' THEN 'EMERGENCY_BRAKE'
        WHEN fp.csat_risk_flag = 'YELLOW'
          AND fp.engagement_risk_flag = 'YELLOW' THEN 'WARNING'
        WHEN fp.revenue_yoy_growth_pct > 30
          AND fp.employee_engagement_score < 70 THEN 'BURNOUT_RISK'
        ELSE 'NOMINAL'
    END AS ai_system_alert
FROM warehouse.fact_performance fp
JOIN warehouse.dim_time dt USING (time_key)
ORDER BY dt.year;


-- ============================================================
-- PASO 4: ÍNDICES DE PERFORMANCE (Query Optimization)
-- ============================================================
CREATE INDEX idx_fact_time     ON warehouse.fact_performance(time_key);
CREATE INDEX idx_fact_org      ON warehouse.fact_performance(org_key);
CREATE INDEX idx_fact_eco      ON warehouse.fact_performance(ecosystem_key);
CREATE INDEX idx_dim_time_year ON warehouse.dim_time(year);
CREATE INDEX idx_csat_flag     ON warehouse.fact_performance(csat_risk_flag);
CREATE INDEX idx_eng_flag      ON warehouse.fact_performance(engagement_risk_flag);


-- ============================================================
-- VERIFICACIÓN: Row counts esperados
-- ============================================================
-- SELECT 'staging.huawei_raw'         AS tabla, COUNT(*) FROM staging.huawei_raw
-- UNION ALL
-- SELECT 'warehouse.fact_performance' AS tabla, COUNT(*) FROM warehouse.fact_performance
-- UNION ALL
-- SELECT 'analytics.v_financial_ecosystem', COUNT(*) FROM analytics.v_financial_ecosystem;
-- Resultado esperado: 34 filas en cada tabla (1987-2020)
