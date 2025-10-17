
# -*- coding: utf-8 -*-
"""
fetch_and_build_jsonl.py
Descarga los textos completos desde InfoLEG / Argentina.gob.ar / SAIJ / PDFs y arma un JSONL listo para RAG.
Uso:
  pip install requests beautifulsoup4 lxml pdfminer.six tqdm pyyaml
  python fetch_and_build_jsonl.py --sources sources.yaml --seed seed_curated.jsonl --out rag_fulltexts.jsonl
"""
import re, os, json, argparse, yaml, time
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from io import BytesIO
from pdfminer.high_level import extract_text

HEADERS = {"User-Agent": "RAG-Legal-Builder/1.0"}

def load_sources(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def resolve_url(sources, key_path):
    # key_path like "lct_20744.infoleg_texto_actualizado"
    keys = key_path.split(".")
    node = sources
    for k in keys:
        node = node[k]
    return node

def clean_text(txt):
    # Remove excessive whitespace
    return re.sub(r'\s+\n', '\n', re.sub(r'[ \t]+', ' ', txt)).strip()

def fetch_html_text(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    # InfoLEG body
    # Try common containers
    for sel in ["div#norma", "div#cuerpo", "div.entry-content", "article", "body"]:
        el = soup.select_one(sel)
        if el:
            return clean_text(el.get_text("\n"))
    return clean_text(soup.get_text("\n"))

def fetch_pdf_text(url):
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    with BytesIO(r.content) as bio:
        txt = extract_text(bio) or ""
    return clean_text(txt)

def is_pdf_url(url):
    path = urlparse(url).path.lower()
    return path.endswith(".pdf")

def slice_article_range(full_text, range_str):
    # Very simple slicer for "Art." occurrences
    if not range_str:
        return full_text
    # Normalize
    t = full_text
    # For ranges like "71-73"
    m = re.match(r'^\s*(\d+)\s*-\s*(\d+)\s*$', range_str)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        pattern = r'(?:^|\n)\s*ART[ÍI]CULO\s+{n}\b.*?(?=(?:^|\n)\s*ART[ÍI]CULO\s+{n2}\b|$\Z)'
        # Build article by article and join
        parts = []
        for num in range(a, b+1):
            # Lookahead to next number or end
            nxt = num+1
            regex = re.compile(pattern.format(n=num, n2=nxt), flags=re.IGNORECASE|re.DOTALL|re.MULTILINE)
            m2 = regex.search(t)
            if m2:
                parts.append(m2.group(0))
        return "\n\n".join(parts) if parts else full_text
    else:
        # Single number or "14 bis", "75 inc. 22", etc.
        # Try to match variants
        key = range_str.replace("inc.", "").replace("INC.", "").strip()
        key = key.replace("bis","bis").replace(" ", "\\s*")
        regex = re.compile(r'(?:^|\n)\s*ART[ÍI]CULO\s+' + key + r'\b.*?(?=(?:^|\n)\s*ART[ÍI]CULO\s+\d+|\Z)', flags=re.IGNORECASE|re.DOTALL|re.MULTILINE)
        m2 = regex.search(t)
        return m2.group(0) if m2 else full_text

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--out", default="rag_fulltexts.jsonl")
    args = ap.parse_args()

    sources = load_sources(args.sources)

    out_f = open(args.out, "w", encoding="utf-8")
    total = 0
    with open(args.seed, "r", encoding="utf-8") as f:
        for line in tqdm(f, desc="Descargando y construyendo"):
            rec = json.loads(line)
            url = resolve_url(sources, rec["source_url_key"])
            rec["url"] = url
            try:
                if is_pdf_url(url):
                    full = fetch_pdf_text(url)
                else:
                    full = fetch_html_text(url)
                # recorte por artículo si corresponde
                text_final = slice_article_range(full, rec.get("article_range"))
                rec["text"] = text_final
            except Exception as e:
                rec["text"] = ""
                rec["error"] = f"{type(e).__name__}: {e}"
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            total += 1
    out_f.close()
    print(f"Listo. Registros procesados: {total}. Salida: {args.out}")

if __name__ == "__main__":
    main()
