import os
import io
import re
import time
import json
import hashlib
import mimetypes
import urllib.parse
import requests
import pandas as pd
from slugify import slugify
from dateutil.parser import parse as dtparse

import boto3
from botocore.exceptions import ClientError

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from dotenv import load_dotenv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)
def s3_client():
    region = "us-east-1"
    session = boto3.session.Session(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),  
        region_name=region,
    )
    return session.client("s3", region_name=region)


# ==========================
# CONFIG
# ==========================
SAIJ_URL = "https://www.saij.gob.ar/buscador/jurisprudencia-nacional"
S3_BUCKET_NAME = "documentos-lexgo-ia-scrapping"  
S3_PREFIX_BASE = "jurisprudencia/pba-laboral"                   
REQUESTS_TIMEOUT = (10, 25)  # (connect, read)


# ==========================
# SELENIUM
# ==========================
def setup_driver(headless=True):
    chrome_opts = Options()
    if headless:
        chrome_opts.add_argument("--headless=new")
    chrome_opts.add_argument("--window-size=1400,1000")
    chrome_opts.add_argument("--disable-gpu")
    chrome_opts.add_argument("--no-sandbox")
    chrome_opts.add_argument("--disable-dev-shm-usage")
    chrome_opts.add_argument("--lang=es-AR")
    chrome_opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) "
                             "Chrome/126.0.0.0 Safari/537.36")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_opts)

def wait_body(driver, t=20):
    WebDriverWait(driver, t).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

def open_search_page(driver):
    driver.get(SAIJ_URL)
    wait_body(driver)
    try:
        toggle = driver.find_element(By.XPATH, "//*[contains(., 'Mostrar/ocultar buscador')]")
        toggle.click(); time.sleep(0.5)
    except:
        pass

def _find_field_by_label(driver, label_text):
    xpath = (f"//label[normalize-space()='{label_text}']"
             "/following::*[self::input or self::textarea or self::select][1]")
    return driver.find_element(By.XPATH, xpath)

def _select_option_by_text(select_el, option_text):
    select_el.click()
    opt = select_el.find_element(By.XPATH, f".//option[normalize-space()='{option_text}']")
    opt.click()

def _set_text_if_present(driver, label, value):
    try:
        el = _find_field_by_label(driver, label)
        el.clear(); el.send_keys(value); return True
    except:
        return False

def _set_select_if_present(driver, label, option_text):
    try:
        sel = _find_field_by_label(driver, label)
        _select_option_by_text(sel, option_text); return True
    except:
        return False

def _press_enter_on_any(driver, label_fallback="Texto"):
    try:
        _find_field_by_label(driver, label_fallback).send_keys(Keys.ENTER); return True
    except:
        try:
            btn = driver.find_element(By.XPATH, "//button[.//img[@alt='filtrar por'] or contains(.,'Buscar')]")
            btn.click(); return True
        except:
            return False

def fmt_fecha(d):
    if not d: return d
    try: return dtparse(d).strftime("%d/%m/%Y")
    except: return d

def apply_filters(driver, texto=None, fuero="Laboral",
                  jurisdiccion="Provincia de Buenos Aires",
                  fecha_desde=None, fecha_hasta=None):
    if texto: _set_text_if_present(driver, "Texto", texto)
    _set_select_if_present(driver, "Fuero", fuero)
    _set_select_if_present(driver, "Jurisdicción", jurisdiccion)
    if fecha_desde: _set_text_if_present(driver, "Fecha desde", fmt_fecha(fecha_desde))
    if fecha_hasta: _set_text_if_present(driver, "Fecha hasta", fmt_fecha(fecha_hasta))
    _press_enter_on_any(driver)
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.XPATH, "//*[contains(., 'Resultado') or contains(., 'Resultados')]"))
    )
    time.sleep(1.0)

def _parse_cards(driver):
    rows = []
    cards = driver.find_elements(
        By.XPATH,
        "//a[contains(@href, '/')][normalize-space()][1]/ancestor::*[self::div or self::li][1]"
    )
    seen = set()
    for c in cards:
        try:
            a = c.find_element(By.XPATH, ".//a[normalize-space()][1]")
            titulo = a.text.strip()
            link = a.get_attribute("href") or ""
            if not titulo or (titulo, link) in seen:
                continue

            try:
                resumen = c.find_element(By.XPATH, ".//p[normalize-space()][1]").text.strip()
            except:
                resumen = ""

            tribunal = ""
            for line in c.text.split("\n"):
                l = line.strip()
                if any(k in l for k in ["Tribunal", "Cámara", "Juzgado"]):
                    tribunal = l; break

            fecha = ""
            m = re.search(r"(\d{2}[/-]\d{2}[/-]\d{4}|\d{4}-\d{2}-\d{2})", c.text)
            if m: fecha = m.group(1)

            rows.append({
                "titulo": titulo,
                "tribunal": tribunal,
                "fecha": fecha,
                "link": link,
                "resumen": resumen
            })
            seen.add((titulo, link))
        except:
            continue
    return rows

def _next_page(driver):
    try:
        nxt = driver.find_element(By.XPATH,
            "//*[normalize-space()='Siguiente' or normalize-space()='»' or normalize-space()='>']")
        cls = (nxt.get_attribute("class") or "").lower()
        if "disabled" in cls: return False
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", nxt)
        nxt.click()
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(., 'Resultado') or contains(., 'Resultados')]"))
        )
        time.sleep(0.8)
        return True
    except:
        return False

def buscar_laboral_pba(texto=None, fecha_desde=None, fecha_hasta=None,
                       max_paginas=5, headless=True, pausa_seg=0.8):
    driver = setup_driver(headless=headless)
    data = []
    try:
        open_search_page(driver)
        apply_filters(driver, texto=texto, fuero="Laboral",
                      jurisdiccion="Provincia de Buenos Aires",
                      fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
        page = 1
        while True:
            data.extend(_parse_cards(driver))
            time.sleep(pausa_seg)
            if page >= max_paginas or not _next_page(driver): break
            page += 1
        return data
    finally:
        driver.quit()

# ==========================
# S3 HELPERS
# ==========================
def s3_client():
    return boto3.client("s3")

def sha256_id(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]

def guess_ext_from_ct(content_type: str) -> str:
    if not content_type: return ""
    if "pdf" in content_type.lower(): return ".pdf"
    if "html" in content_type.lower(): return ".html"
    if "text/plain" in content_type.lower(): return ".txt"
    ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ""
    return ext

def safe_filename_from_url(url: str) -> str:
    # intenta usar el nombre de la URL; si es feo/vacío, genera uno
    path = urllib.parse.urlparse(url).path
    name = os.path.basename(path)
    name = urllib.parse.unquote(name)
    if not name or "." not in name:
        return ""
    return name

def download_bytes(url: str):
    try:
        r = requests.get(url, timeout=REQUESTS_TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        ct = r.headers.get("Content-Type", "")
        return r.content, ct
    except requests.RequestException:
        return None, None

def s3_put_bytes(key: str, data: bytes, content_type: str = None, metadata: dict = None):
    cli = s3_client()
    extra = {
        "Bucket": S3_BUCKET_NAME,
        "Key": key,
        "Body": data,
        "ServerSideEncryption": "AES256",
    }
    if content_type:
        extra["ContentType"] = content_type
    if metadata:
        extra["Metadata"] = {str(k): str(v) for k, v in metadata.items()}
    cli.put_object(**extra)
    return f"s3://{S3_BUCKET_NAME}/{key}"

# ==========================
# PIPE: scrape -> upload
# ==========================
def upload_result_and_document(row: dict):
    """
    Sube:
      - metadata.json (siempre)
      - documento (si se pudo descargar)
    Retorna claves S3 subidas.
    """
    # ID estable
    base_id = sha256_id(f"{row.get('titulo','')}|{row.get('link','')}")
    # Año para organizar (si no hay fecha, usa 'sin-fecha')
    year = "sin-fecha"
    fecha = row.get("fecha") or ""
    try:
        if fecha:
            year = str(dtparse(fecha, dayfirst=True).year)
    except:
        pass

    titulo_slug = slugify(row.get("titulo","")[:60]) or "sin-titulo"
    folder = f"{S3_PREFIX_BASE}/{year}/{base_id}-{titulo_slug}"

    # 1) Subir metadata.json
    meta_key = f"{folder}/metadata.json"
    meta_bytes = json.dumps(row, ensure_ascii=False, indent=2).encode("utf-8")
    s3_put_bytes(meta_key, meta_bytes, content_type="application/json; charset=utf-8")

    uploaded = {"metadata_key": meta_key, "document_key": None}

    # 2) Descargar documento (si link parece válido)
    link = row.get("link") or ""
    if link.startswith("http"):
        data, ct = download_bytes(link)
        if data:
            # Nombre amigable
            name = safe_filename_from_url(link)
            if not name:
                ext = guess_ext_from_ct(ct) or (".pdf" if ".pdf" in link.lower() else ".html")
                name = f"documento{ext}"
            doc_key = f"{folder}/{name}"
            s3_put_bytes(doc_key, data, content_type=(ct or mimetypes.guess_type(name)[0] or "application/octet-stream"))
            uploaded["document_key"] = doc_key

    return uploaded

def save_manifest_to_s3(rows: list, prefix: str):
    ts = pd.Timestamp.utcnow().strftime("%Y%m%dT%H%M%SZ")
    # CSV
    df = pd.DataFrame(rows)
    csv_buf = io.StringIO()
    df.to_csv(csv_buf, index=False, encoding="utf-8")
    csv_key = f"{prefix}/manifest_{ts}.csv"
    s3_put_bytes(csv_key, csv_buf.getvalue().encode("utf-8"), content_type="text/csv; charset=utf-8")
    # JSON
    json_key = f"{prefix}/manifest_{ts}.json"
    s3_put_bytes(json_key, json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8"),
                 content_type="application/json; charset=utf-8")
    return csv_key, json_key

def run(texto="despido con causa", fecha_desde="2018-01-01", fecha_hasta="2025-12-31",
        max_paginas=3, headless=True):
    print("Buscando jurisprudencia Laboral – PBA…")
    resultados = buscar_laboral_pba(
        texto=texto,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        max_paginas=max_paginas,
        headless=headless
    )
    print(f"Resultados: {len(resultados)}")

    # Dedup por (titulo, link)
    seen = set()
    clean = []
    for r in resultados:
        k = (r.get("titulo","").strip(), r.get("link","").strip())
        if k in seen: continue
        seen.add(k)
        clean.append(r)

    # Subir cada caso
    uploaded_records = []
    for row in clean:
        try:
            up = upload_result_and_document(row)
            row["_s3_metadata_key"] = up["metadata_key"]
            row["_s3_document_key"] = up["document_key"]
            uploaded_records.append(row)
            time.sleep(0.2)  # cuida al sitio y al S3
        except ClientError as ce:
            print(f"[S3] Error subiendo: {ce}")
        except Exception as e:
            print(f"[WARN] Falla con un item: {e}")

    # Subir manifiesto global
    manifest_csv, manifest_json = save_manifest_to_s3(uploaded_records, f"{S3_PREFIX_BASE}/manifiestos")
    print(f"Subidos manifiestos: s3://{S3_BUCKET_NAME}/{manifest_csv} , s3://{S3_BUCKET_NAME}/{manifest_json}")
    return uploaded_records

if __name__ == "__main__":
    run(
        texto="despido con causa",    
        fecha_desde="2018-01-01",
        fecha_hasta="2025-12-31",
        max_paginas=4,
        headless=True
    )
