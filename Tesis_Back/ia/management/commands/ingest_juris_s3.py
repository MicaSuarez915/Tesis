from django.core.management.base import BaseCommand
import os, boto3
from ia.ingest import ingest_from_metadata
from django.conf import settings

BUCKET = settings.AWS_S3_BUCKET_NAME_IA

class Command(BaseCommand):
    help = "Ingesta metadata.json desde S3: textea, chunkea, embebe, guarda en Postgres."

    def add_arguments(self, parser):
        parser.add_argument("--prefix", required=True)
        parser.add_argument("--limit", type=int, default=100000)

    def handle(self, *args, **opts):
        s3 = boto3.client("s3")
        pref = opts["prefix"].rstrip("/") + "/"
        n = ok = 0
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=pref):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith("metadata.json"): continue
                if n >= opts["limit"]:
                    self.stdout.write(self.style.WARNING("Limit alcanzado")); return
                try:
                    doc_id, cnt = ingest_from_metadata(key)
                    ok += 1
                    self.stdout.write(self.style.SUCCESS(f"[OK] {doc_id} chunks={cnt}"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"[ERR] {key} -> {e}"))
                n += 1
        self.stdout.write(self.style.SUCCESS(f"Listo. {ok}/{n} procesados."))
