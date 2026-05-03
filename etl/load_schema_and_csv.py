"""
ETL: Ejecuta el star schema SQL y carga el CSV en staging.huawei_raw.
Orden: schemas DDL -> carga CSV -> warehouse DDL -> analytics DDL.
"""
import os, sys
import pandas as pd
import psycopg2
from psycopg2 import sql
from io import StringIO
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

CONN_PARAMS = dict(
    host=os.getenv("DB_HOST", "127.0.0.1"),
    port=int(os.getenv("DB_PORT", 5432)),
    dbname=os.getenv("DB_NAME", "huawei_smad"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
)

SQL_FILE  = ROOT / "huawei_star_schema.sql"
CSV_FILE  = ROOT / "data" / "huawei_dynamic_alignment_data.csv"

# Mapeo: nombre columna CSV -> nombre columna tabla staging.huawei_raw
COL_RENAME = {
    "R&D_Expenditure_USD_M":              "RD_Expenditure_USD_M",
    "R&D_Intensity_Pct":                  "RD_Intensity_Pct",
    "Product_Development_Cycle_Weeks":    "Product_Development_Cycle_Wks",
    "Frontline_Decision_Authority_Index": "Frontline_Decision_Authority",
    "Country_of_Origin_Perception_Index": "Country_of_Origin_Perception",
    "Analyst_Strategy_Clarity_Rating":    "Analyst_Strategy_Clarity",
}


def split_sql(sql_text: str):
    """Divide el SQL en: [fase1] DDL staging, [fase2] warehouse+analytics."""
    marker = "-- PASO 1: DIMENSIONES"
    idx = sql_text.find(marker)
    if idx == -1:
        raise ValueError("No se encontró el marcador de split en el SQL")
    return sql_text[:idx].strip(), sql_text[idx:].strip()


def run_sql_block(cur, block: str, label: str):
    """Ejecuta un bloque SQL completo. Detiene ante errores."""
    print(f"\n{'='*60}")
    print(f"  Ejecutando: {label}")
    print(f"{'='*60}")
    cur.execute(block)
    print(f"  OK: {label}")


def load_csv(conn, csv_path: Path):
    """Lee el CSV, renombra columnas y hace COPY desde buffer en memoria."""
    print(f"\n{'='*60}")
    print(f"  Cargando CSV: {csv_path.name}")
    print(f"{'='*60}")

    df = pd.read_csv(csv_path)
    print(f"  Filas leídas del CSV : {len(df)}")
    print(f"  Años               : {df['Year'].min()} - {df['Year'].max()}")

    # Renombrar columnas al esquema de la tabla
    df = df.rename(columns=COL_RENAME)

    # Serializar a TSV en memoria para COPY FROM STDIN
    buf = StringIO()
    df.to_csv(buf, index=False, sep="\t", header=False, na_rep="\\N")
    buf.seek(0)

    # PostgreSQL folds unquoted identifiers to lowercase; use lowercase here
    table_cols = ", ".join(c.lower() for c in df.columns)
    copy_sql = f"COPY staging.huawei_raw ({table_cols}) FROM STDIN WITH (FORMAT TEXT, DELIMITER E'\\t', NULL '\\N')"
    with conn.cursor() as cur:
        cur.copy_expert(copy_sql, buf)
    print(f"  COPY completado: {len(df)} filas -> staging.huawei_raw")


def verify(cur):
    """Cuenta filas y muestra rango de años en las tablas clave."""
    tables = [
        ("staging.huawei_raw",         "Year"),
        ("warehouse.dim_time",          "year"),
        ("warehouse.dim_organization",  "year"),
        ("warehouse.dim_ecosystem",     "year"),
        ("warehouse.fact_performance",  None),
    ]
    print(f"\n{'='*60}")
    print(f"  VERIFICACIÓN DE FILAS")
    print(f"{'='*60}")
    print(f"  {'Tabla':<40} {'Filas':>6}  {'Años'}")
    print(f"  {'-'*60}")
    all_ok = True
    for table, year_col in tables:
        if year_col:
            cur.execute(f"SELECT COUNT(*), MIN({year_col}), MAX({year_col}) FROM {table}")
            cnt, yr_min, yr_max = cur.fetchone()
            rng = f"{yr_min} - {yr_max}"
        else:
            cur.execute(f"""
                SELECT COUNT(*), MIN(dt.year), MAX(dt.year)
                FROM {table} fp
                JOIN warehouse.dim_time dt USING (time_key)
            """)
            cnt, yr_min, yr_max = cur.fetchone()
            rng = f"{yr_min} - {yr_max}"

        status = "OK" if cnt == 34 else f"WARN ({cnt}!=34)"
        if cnt != 34:
            all_ok = False
        print(f"  {table:<40} {cnt:>6}   {rng}   [{status}]")

    print(f"\n  {'RESULTADO GLOBAL: OK (34 filas en todas las tablas)' if all_ok else 'ADVERTENCIA: alguna tabla no tiene 34 filas'}")
    return all_ok


def main():
    sql_text = SQL_FILE.read_text(encoding="utf-8")
    phase1_ddl, phase2_ddl = split_sql(sql_text)

    conn = psycopg2.connect(**CONN_PARAMS)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            # Fase 1: schemas + staging table (DROP/CREATE)
            run_sql_block(cur, phase1_ddl, "Fase 1: schemas + staging.huawei_raw DDL")
        conn.commit()

        # Fase 2: carga CSV (autocommit=False, commit tras COPY)
        load_csv(conn, CSV_FILE)
        conn.commit()

        with conn.cursor() as cur:
            # Fase 3: warehouse + analytics
            run_sql_block(cur, phase2_ddl, "Fase 2: warehouse dims + fact + analytics views + indexes")
        conn.commit()

        with conn.cursor() as cur:
            ok = verify(cur)

        if not ok:
            sys.exit(1)

    except Exception as e:
        conn.rollback()
        print(f"\nERROR: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()

    print("\nETL completado correctamente.\n")


if __name__ == "__main__":
    main()
