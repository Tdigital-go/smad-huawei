"""Prueba los cuatro endpoints de la API SMAD en puerto 8080."""
import httpx, json
from datetime import datetime

BASE = "http://127.0.0.1:8080"

def hr(title):
    print(f"\n{'='*62}")
    print(f"  {title}")
    print(f"{'='*62}")

def show(r):
    print(f"  HTTP {r.status_code}  |  {r.elapsed.total_seconds()*1000:.0f} ms")
    print(json.dumps(r.json(), indent=4, ensure_ascii=False))

# ── 1. GET /health ──────────────────────────────────────────────────
hr("1/4  GET /health")
show(httpx.get(f"{BASE}/health"))

# ── 2. GET /metrics/2020 ────────────────────────────────────────────
hr("2/4  GET /metrics/2020  (campos clave)")
r2 = httpx.get(f"{BASE}/metrics/2020")
print(f"  HTTP {r2.status_code}  |  {r2.elapsed.total_seconds()*1000:.0f} ms")
data = r2.json()
fields = [
    "year", "strategic_era", "revenue_usd_m", "net_income_usd_m",
    "rd_intensity_pct", "agility_okr_progress_pct", "csat_risk_flag",
    "engagement_risk_flag", "composite_innovation_index",
    "total_employees", "ecosystem_partners_count",
]
print(json.dumps({k: data[k] for k in fields}, indent=4, ensure_ascii=False))
print(f"  (total campos en respuesta: {len(data)})")

# ── 3. POST /predict — perfil año 2020 ─────────────────────────────
hr("3/4  POST /predict  — perfil 2020 (esperado: NOMINAL, p_emergency < 0.10)")
payload = {
    "product_development_cycle_weeks": 21.4,
    "employee_engagement_score":       86.1,
    "customer_satisfaction_index":     93.6,
    "cross_departmental_projects":     430,
    "revenue_growth":                  10.6,
    "engagement_lag1":                 85.2,
    "csat_lag1":                       92.0,
    "cycle_change":                    -1.5,
    "cross_proj_normalized":            2.18,
    "rd_intensity_pct":                15.13,
}
print("  Payload:")
print(json.dumps(payload, indent=4))
r3 = httpx.post(f"{BASE}/predict", json=payload)
show(r3)
pred = r3.json()
label_ok = pred["risk_label"] == "NOMINAL"
p_emg_ok = pred["emergency_probability"] < 0.10
print(f"\n  CRITERIOS DE ACEPTACION:")
print(f"  risk_label == NOMINAL       : {'PASS' if label_ok else 'FAIL'}")
print(f"  emergency_prob < 0.10       : {'PASS' if p_emg_ok else 'FAIL'}  (valor={pred['emergency_probability']})")

# ── 4. GET /summary/2020 ────────────────────────────────────────────
hr("4/4  GET /summary/2020")
r4 = httpx.get(f"{BASE}/summary/2020")
print(f"  HTTP {r4.status_code}  |  {r4.elapsed.total_seconds()*1000:.0f} ms")
print(r4.json()["summary"])

print(f"\n{'='*62}")
print(f"  Todos los endpoints respondieron.")
print(f"  Generado: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
print(f"{'='*62}")
