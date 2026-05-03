"""
init_db.py — Inicialización de la base de datos para Render cold-start.

Ejecutado automáticamente por render.yaml antes de arrancar uvicorn:
    python mlops/init_db.py && uvicorn mlops.main:app ...

Lógica:
  1. Conecta a PostgreSQL (DATABASE_URL o vars individuales del .env)
  2. Si staging.huawei_raw ya tiene filas → no hace nada (idempotente)
  3. Si está vacía → ejecuta huawei_star_schema.sql + carga el CSV
"""

from __future__ import annotations

import os
import sys
from io import StringIO
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

_DATABASE_URL = os.getenv("DATABASE_URL")
_DB_CONFIG = dict(
    host=os.getenv("DB_HOST", "127.0.0.1"),
    port=int(os.getenv("DB_PORT", 5432)),
    dbname=os.getenv("DB_NAME", "huawei_smad"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
)

SQL_FILE = ROOT / "huawei_star_schema.sql"
CSV_FILE = ROOT / "data" / "huawei_dynamic_alignment_data.csv"

COL_RENAME = {
    "R&D_Expenditure_USD_M":              "RD_Expenditure_USD_M",
    "R&D_Intensity_Pct":                  "RD_Intensity_Pct",
    "Product_Development_Cycle_Weeks":    "Product_Development_Cycle_Wks",
    "Frontline_Decision_Authority_Index": "Frontline_Decision_Authority",
    "Country_of_Origin_Perception_Index": "Country_of_Origin_Perception",
    "Analyst_Strategy_Clarity_Rating":    "Analyst_Strategy_Clarity",
}


def get_conn():
    if _DATABASE_URL:
        return psycopg2.connect(_DATABASE_URL)
    return psycopg2.connect(**_DB_CONFIG)


def schema_is_populated(conn) -> bool:
    """Devuelve True si staging.huawei_raw ya tiene filas."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='staging' AND table_name='huawei_raw')"
            )
            exists = cur.fetchone()[0]
            if not exists:
                return False
            cur.execute("SELECT COUNT(*) FROM staging.huawei_raw")
            return cur.fetchone()[0] > 0
    except Exception:
        return False


def split_sql(text: str):
    marker = "-- PASO 1: DIMENSIONES"
    idx = text.find(marker)
    if idx == -1:
        raise ValueError("Marcador de split no encontrado en el SQL.")
    return text[:idx].strip(), text[idx:].strip()


def run_sql(cur, sql: str):
    cur.execute(sql)


def load_csv(conn):
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
    print(f"[init_db] CSV cargado: {len(df)} filas → staging.huawei_raw")


def main():
    print("[init_db] Conectando a PostgreSQL...")
    try:
        conn = get_conn()
    except Exception as exc:
        print(f"[init_db] ERROR conectando: {exc}", file=sys.stderr)
        sys.exit(1)

    if schema_is_populated(conn):
        print("[init_db] Base de datos ya inicializada — omitiendo ETL.")
        conn.close()
        return

    print("[init_db] Base de datos vacía — ejecutando schema + carga CSV...")
    sql_text = SQL_FILE.read_text(encoding="utf-8")
    phase1, phase2 = split_sql(sql_text)

    try:
        # Fase 1: schemas + staging table
        with conn.cursor() as cur:
            run_sql(cur, phase1)
        conn.commit()
        print("[init_db] Fase 1 OK: schemas + staging.huawei_raw creados")

        # Carga CSV
        load_csv(conn)
        conn.commit()

        # Fase 2: warehouse + analytics + índices
        with conn.cursor() as cur:
            run_sql(cur, phase2)
        conn.commit()
        print("[init_db] Fase 2 OK: warehouse dims + fact + analytics views")

        # Verificación rápida
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM warehouse.fact_performance")
            n = cur.fetchone()[0]
        print(f"[init_db] Verificación: {n} filas en fact_performance")
        if n != 34:
            print(f"[init_db] ADVERTENCIA: se esperaban 34 filas, hay {n}",
                  file=sys.stderr)

    except Exception as exc:
        conn.rollback()
        print(f"[init_db] ERROR en ETL: {exc}", file=sys.stderr)
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()

    print("[init_db] Inicialización completada.")


if __name__ == "__main__":
    main()
