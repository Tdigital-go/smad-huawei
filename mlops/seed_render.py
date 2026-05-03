"""
seed_render.py — Carga inicial de la base de datos PostgreSQL en Render.

USO:
    # Con DATABASE_URL como variable de entorno:
    set RENDER_DATABASE_URL=postgres://user:pass@host/db
    python mlops/seed_render.py

    # O directamente como argumento:
    python mlops/seed_render.py --url "postgres://user:pass@host/db"

    # Forzar re-carga aunque la DB ya tenga datos:
    python mlops/seed_render.py --url "..." --force

DESCRIPCIÓN:
    1. Conecta a la PostgreSQL de Render vía DATABASE_URL
    2. Ejecuta huawei_star_schema.sql (schemas + tablas + vistas)
    3. Carga data/huawei_dynamic_alignment_data.csv en staging.huawei_raw
    4. Verifica que las 34 filas (1987-2020) están en fact_performance
    5. Imprime un resumen de validación final
"""

from __future__ import annotations

import argparse
import os
import sys
from io import StringIO
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras

# ── Rutas ─────────────────────────────────────────────────────────────────────
ROOT     = Path(__file__).parent.parent
SQL_FILE = ROOT / "huawei_star_schema.sql"
CSV_FILE = ROOT / "data" / "huawei_dynamic_alignment_data.csv"

# ── Renombrado de columnas CSV → columnas DB ───────────────────────────────────
COL_RENAME = {
    "R&D_Expenditure_USD_M":              "RD_Expenditure_USD_M",
    "R&D_Intensity_Pct":                  "RD_Intensity_Pct",
    "Product_Development_Cycle_Weeks":    "Product_Development_Cycle_Wks",
    "Frontline_Decision_Authority_Index": "Frontline_Decision_Authority",
    "Country_of_Origin_Perception_Index": "Country_of_Origin_Perception",
    "Analyst_Strategy_Clarity_Rating":    "Analyst_Strategy_Clarity",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def fix_url(url: str) -> str:
    """
    Render entrega URLs con esquema 'postgres://' pero psycopg2
    requiere 'postgresql://'. Corregimos silenciosamente.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def get_conn(url: str):
    return psycopg2.connect(fix_url(url))


def split_sql(text: str) -> tuple[str, str]:
    """
    Divide el SQL en dos fases:
      Fase 1: schemas + staging.huawei_raw  (antes del marcador)
      Fase 2: warehouse dims + fact + analytics views (después del marcador)
    """
    marker = "-- PASO 1: DIMENSIONES"
    idx = text.find(marker)
    if idx == -1:
        raise ValueError(
            f"Marcador '{marker}' no encontrado en {SQL_FILE}. "
            "Verifica que el archivo SQL está actualizado."
        )
    return text[:idx].strip(), text[idx:].strip()


def is_populated(conn) -> bool:
    """Devuelve True si staging.huawei_raw ya tiene filas."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_schema='staging' AND table_name='huawei_raw'"
                ")"
            )
            if not cur.fetchone()[0]:
                return False
            cur.execute("SELECT COUNT(*) FROM staging.huawei_raw")
            return cur.fetchone()[0] > 0
    except Exception:
        return False


def run_phase(conn, sql: str, label: str):
    """Ejecuta un bloque SQL completo en una transacción."""
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    print(f"  ✓ {label}")


def load_csv(conn):
    """Carga el CSV en staging.huawei_raw mediante COPY FROM STDIN."""
    if not CSV_FILE.exists():
        raise FileNotFoundError(f"CSV no encontrado: {CSV_FILE}")

    df = pd.read_csv(CSV_FILE).rename(columns=COL_RENAME)
    cols = ", ".join(c.lower() for c in df.columns)
    copy_sql = (
        f"COPY staging.huawei_raw ({cols}) "
        f"FROM STDIN WITH (FORMAT TEXT, DELIMITER E'\\t', NULL '\\N')"
    )
    buf = StringIO()
    df.to_csv(buf, index=False, sep="\t", header=False, na_rep="\\N")
    buf.seek(0)

    with conn.cursor() as cur:
        cur.copy_expert(copy_sql, buf)
    conn.commit()
    print(f"  ✓ CSV cargado: {len(df)} filas → staging.huawei_raw")


def verify(conn) -> dict:
    """Verifica conteos en todas las tablas clave y retorna resumen."""
    tables = {
        "staging.huawei_raw":          "filas raw",
        "warehouse.dim_time":          "períodos",
        "warehouse.dim_organization":  "orgs",
        "warehouse.dim_ecosystem":     "ecosistemas",
        "warehouse.fact_performance":  "hechos (1987-2020)",
    }
    views = [
        "analytics.v_financial_ecosystem",
        "analytics.v_agility_okr",
        "analytics.v_customer_innovation",
        "analytics.v_ai_emergency_brake",
    ]
    results = {}
    with conn.cursor() as cur:
        for table, label in tables.items():
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            n = cur.fetchone()[0]
            results[table] = n
            status = "✓" if n == 34 else "⚠"
            print(f"  {status} {table}: {n} {label}")
        for view in views:
            cur.execute(f"SELECT COUNT(*) FROM {view}")
            n = cur.fetchone()[0]
            results[view] = n
            print(f"  ✓ {view}: {n} filas")
    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Seed de la base de datos Render para SMAD Huawei."
    )
    parser.add_argument(
        "--url",
        default=os.getenv("RENDER_DATABASE_URL") or os.getenv("DATABASE_URL"),
        help="DATABASE_URL de Render (o exportar RENDER_DATABASE_URL)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Forzar re-carga aunque la DB ya tenga datos",
    )
    args = parser.parse_args()

    if not args.url:
        print(
            "\n[ERROR] No se encontró DATABASE_URL.\n"
            "Opciones:\n"
            "  1. Exportar: set RENDER_DATABASE_URL=postgres://...\n"
            "  2. Pasar como argumento: python mlops/seed_render.py --url \"postgres://...\"\n",
            file=sys.stderr,
        )
        sys.exit(1)

    # Ocultar credenciales en el log
    safe_url = args.url.split("@")[-1] if "@" in args.url else args.url
    print(f"\n[seed_render] Conectando a: ...@{safe_url}")

    try:
        conn = get_conn(args.url)
        conn.autocommit = False
        print("  ✓ Conexión establecida")
    except Exception as exc:
        print(f"[ERROR] No se pudo conectar: {exc}", file=sys.stderr)
        sys.exit(1)

    # ── Verificar si ya está poblada ─────────────────────────────────────────
    if is_populated(conn) and not args.force:
        print("\n[seed_render] La base de datos ya tiene datos.")
        print("  → Ejecuta con --force para re-cargar desde cero.\n")
        print("[seed_render] Verificación del estado actual:")
        verify(conn)
        conn.close()
        return

    if args.force:
        print("\n[seed_render] Modo --force: re-inicializando base de datos...")

    # ── Leer SQL ─────────────────────────────────────────────────────────────
    if not SQL_FILE.exists():
        print(f"[ERROR] SQL no encontrado: {SQL_FILE}", file=sys.stderr)
        sys.exit(1)

    sql_text  = SQL_FILE.read_text(encoding="utf-8")
    phase1_sql, phase2_sql = split_sql(sql_text)

    try:
        # Fase 1: schemas + staging.huawei_raw
        print("\n[seed_render] Fase 1: creando schemas y tabla staging...")
        run_phase(conn, phase1_sql, "schemas + staging.huawei_raw creados")

        # Carga CSV
        print("\n[seed_render] Cargando CSV...")
        load_csv(conn)

        # Fase 2: warehouse dims + fact + analytics
        print("\n[seed_render] Fase 2: warehouse + analytics...")
        run_phase(conn, phase2_sql, "dims + fact_performance + vistas analytics creados")

    except Exception as exc:
        conn.rollback()
        print(f"\n[ERROR] Fallo en ETL: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        conn.close()
        sys.exit(1)

    # ── Verificación final ───────────────────────────────────────────────────
    print("\n[seed_render] Verificación final:")
    counts = verify(conn)

    fact_n = counts.get("warehouse.fact_performance", 0)
    if fact_n != 34:
        print(
            f"\n  ⚠ ADVERTENCIA: se esperaban 34 filas en fact_performance, hay {fact_n}",
            file=sys.stderr,
        )
    else:
        print("\n  ✓ Base de datos Render inicializada correctamente (34 años, 1987-2020)")

    conn.close()
    print("[seed_render] Completado.\n")


if __name__ == "__main__":
    main()
