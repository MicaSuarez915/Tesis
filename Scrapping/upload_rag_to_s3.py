import os, io, sys, re, json, gzip, glob, mimetypes, hashlib, argparse
from datetime import datetime
from pathlib import Path
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
import pytz

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

def compute_sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()

def guess_content_type(path: str) -> str:
    if path.endswith(".jsonl.gz"): return "application/gzip"
    if path.endswith(".jsonl"):    return "application/x-ndjson"
    if path.endswith(".json"):     return "application/json"
    if path.endswith(".txt"):      return "text/plain; charset=utf-8"
    if path.endswith(".html") or path.endswith(".htm"):
        return "text/html; charset=utf-8"
    ct, _ = mimetypes.guess_type(path)
    return ct or "application/octet-stream"

def s3_put_bytes(bucket: str, key: str, data: bytes, content_type: str = None, metadata: dict = None):
    s3 = s3_client()
    extra = {
        "Bucket": bucket,
        "Key": key,
        "Body": data,
        "ServerSideEncryption": "AES256",
    }
    if content_type:
        extra["ContentType"] = content_type
    if metadata:
        extra["Metadata"] = {str(k): str(v) for k, v in metadata.items()}
    s3.put_object(**extra)
    return f"s3://{bucket}/{key}"

def normalize_paths(paths):
    expanded = []
    for p in paths:
        matches = sorted(glob.glob(p))
        expanded.extend(matches if matches else [p])
    return [m for m in expanded if os.path.exists(m)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True, help="Nombre del S3 bucket")
    ap.add_argument("--prefix", required=True, help="Prefijo base en S3 (ej. biblioteca/laboral)")
    ap.add_argument("--paths", nargs="+", required=True, help="Rutas/globs a subir (ej. rag_fulltexts.jsonl RAG_*.zip)")
    ap.add_argument("--gzip-jsonl", action="store_true", help="Comprimir JSONL a .gz antes de subir")
    args = ap.parse_args()

    bucket = args.bucket
    prefix = args.prefix.strip("/")
    files  = normalize_paths(args.paths)
    if not files:
        print("No se encontraron archivos para subir.")
        sys.exit(1)

    uploaded = []
    for path in files:
        path = os.path.abspath(path)
        basename = os.path.basename(path)
        key = f"{prefix}/{basename}"

        with open(path, "rb") as fh:
            data = fh.read()

        meta = {
            "sha256": compute_sha256_bytes(data),
            "size_bytes": str(len(data)),
            "uploaded_at": datetime.utcnow().isoformat() + "Z",
        }

        # Si es JSONL y se pidió gzip, subimos además .gz
        if args.gzip_jsonl and basename.endswith(".jsonl"):
            gz_name = basename + ".gz"
            gz_key  = f"{prefix}/{gz_name}"
            gz_bytes = gzip.compress(data, compresslevel=6)
            s3_uri_gz = s3_put_bytes(bucket, gz_key, gz_bytes, content_type="application/gzip", metadata=meta)
            uploaded.append({"local": path, "s3": s3_uri_gz, "content_type": "application/gzip"})
            print(f"[OK] {s3_uri_gz}")

        # Subida "normal"
        ct = guess_content_type(path)
        s3_uri = s3_put_bytes(bucket, key, data, content_type=ct, metadata=meta)
        uploaded.append({"local": path, "s3": s3_uri, "content_type": ct})
        print(f"[OK] {s3_uri}")

    # Subir manifiesto
    manifest = {
        "bucket": bucket,
        "prefix": prefix,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "entries": uploaded,
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    ba_tz = pytz.timezone("America/Argentina/Buenos_Aires")
    mf_name = f"manifest_{datetime.now(ba_tz).strftime('%Y%m%dT%H%M%SZ')}.json"
    mf_key  = f"{prefix}/{mf_name}"
    s3_put_bytes(bucket, mf_key, manifest_bytes, content_type="application/json; charset=utf-8")
    print(f"[MANIFEST] s3://{bucket}/{mf_key}")

if __name__ == "__main__":
    main()