from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator
from .models import *
from ia.models import SummaryRun
from ia.serializers import SummaryRunSerializer

class DomicilioSerializer(serializers.ModelSerializer):
    class Meta: model = Domicilio; fields = "__all__"

class ParteSerializer(serializers.ModelSerializer):
    class Meta: model = Parte; fields = "__all__"

class ParteSimpleSerializer(serializers.Serializer):
    tipo_persona = serializers.ChoiceField(choices=Parte.TIPO_PERSONA_CHOICES, required=True)
    nombre_razon_social = serializers.CharField(required=True, max_length=200)
    documento = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    cuit_cuil = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    telefono = serializers.CharField(required=False, allow_blank=True)
    domicilio = serializers.CharField(required=False, allow_blank=True, max_length=250)

    def get_or_create(self):
        data = self.validated_data
        q = models.Q(nombre_razon_social=data["nombre_razon_social"])
        if data.get("documento"):
            q |= models.Q(documento=data["documento"])
        if data.get("cuit_cuil"):
            q |= models.Q(cuit_cuil=data["cuit_cuil"])

        existente = Parte.objects.filter(q).first()
        if existente:
            return existente

        return Parte.objects.create(**data)



class RolParteSerializer(serializers.ModelSerializer):
    class Meta: model = RolParte; fields = "__all__"

class ProfesionalSerializer(serializers.ModelSerializer):
    class Meta: model = Profesional; fields = "__all__"

class DocumentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Documento
        fields = ["id", "titulo", "archivo", "fecha", "creado_en", "causa"]
        read_only_fields = ["id", "creado_en"]

class EventoProcesalSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventoProcesal
        fields = ["id", "titulo", "descripcion", "fecha", "plazo_limite", "creado_en", "causa"]
        read_only_fields = ["id", "creado_en"]

class CausaParteSerializer(serializers.ModelSerializer):
    causa = serializers.PrimaryKeyRelatedField(queryset=Causa.objects.all(), required=True)
    parte = serializers.PrimaryKeyRelatedField(queryset=Parte.objects.all(), required=True)
    #rol_parte = serializers.PrimaryKeyRelatedField(queryset=RolParte.objects.all(), required=False, allow_null=True)
    #observaciones = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = CausaParte
        # dejamos solo los campos necesarios
        fields = ["id", "causa", "parte"]
        extra_kwargs = {
            "causa": {"required": True},
            "parte": {"required": True},
        }


class CausaProfesionalSerializer(serializers.ModelSerializer):
    class Meta:
        model = CausaProfesional
        fields = ["id", "causa", "profesional", "rol_profesional"]

class CausaGrafoSerializer(serializers.ModelSerializer):
    data = serializers.JSONField()  # <— ¡no read_only!

    class Meta:
        model = CausaGrafo
        fields = ["id", "causa", "data", "actualizado_en"]
        read_only_fields = ["id", "causa", "actualizado_en"]

    def update(self, instance, validated_data):
        # Sólo actualizamos el JSON del grafo
        if "data" in validated_data:
            instance.data = validated_data["data"]
        instance.save(update_fields=["data", "actualizado_en"])
        return instance


class CausaParteReadSerializer(serializers.ModelSerializer):
    # devolvemos el objeto parte completo
    parte = ParteSerializer(read_only=True)

    class Meta:
        model = CausaParte
        # devolvemos causa como ID y parte como objeto expandido
        fields = ("causa", "parte")


class CausaSerializer(serializers.ModelSerializer):
    partes = CausaParteReadSerializer(many=True, read_only=True)
    profesionales = CausaProfesionalSerializer(source="causa_profesionales", many=True, read_only=True)
    documentos = DocumentoSerializer(many=True, read_only=True)
    eventos = EventoProcesalSerializer(many=True, read_only=True)
    grafo = CausaGrafoSerializer(read_only=True)
    summary_runs = SummaryRunSerializer(many=True, read_only=True)

    class Meta:
        model = Causa
        fields = [
            "id", "numero_expediente", "caratula", "fuero", "jurisdiccion",
            "fecha_inicio", "estado", "creado_en", "actualizado_en", "creado_por",
            "partes", "profesionales", "documentos", "eventos", "grafo", "summary_runs"
        ]
        read_only_fields = ["id", "creado_en", "actualizado_en"]
        validators = [
            UniqueTogetherValidator(
                queryset=Causa.objects.all(),
                fields=("numero_expediente", "fuero", "jurisdiccion"),
                message="Los campos numero_expediente, fuero, jurisdiccion deben formar un conjunto único."
            )
        ]


class TimelineResponseSerializer(serializers.Serializer):
    causa = serializers.IntegerField()
    eventos = EventoProcesalSerializer(many=True)
    documentos = DocumentoSerializer(many=True, required=False)

class ProximosResponseSerializer(serializers.Serializer):
    desde = serializers.DateField()
    hasta = serializers.DateField()
    eventos = EventoProcesalSerializer(many=True)


# ── CREATE/UPSERT HELPERS ──────────────────────────────────────────────────────
from django.db import transaction, IntegrityError
from django.utils import timezone
import uuid

class RolParteRefSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    nombre = serializers.CharField(required=False, allow_blank=False)

    def get_or_create(self):
        data = self.validated_data
        if "id" in data:
            return RolParte.objects.get(pk=data["id"])
        nombre = data.get("nombre")
        if not nombre:
            raise serializers.ValidationError("Debe enviar rol_parte.id o rol_parte.nombre")
        obj, _ = RolParte.objects.get_or_create(nombre=nombre.strip())
        return obj

class DomicilioWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Domicilio
        fields = ("calle","numero","ciudad","provincia","pais")

class ParteWriteSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    tipo_persona = serializers.ChoiceField(choices=Parte.TIPO_PERSONA_CHOICES, required=False)
    nombre_razon_social = serializers.CharField(required=False)
    documento = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    cuit_cuil = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    telefono = serializers.CharField(required=False, allow_blank=True)
    domicilio = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def get_or_create(self):
        data = self.validated_data
        if "id" in data:
            return Parte.objects.get(pk=data["id"])

        # Claves de búsqueda (prioridad): documento, cuit/cuil, (nombre+email)
        q = None
        if data.get("documento"):
            q = models.Q(documento=data["documento"])
        if data.get("cuit_cuil"):
            q = (q | models.Q(cuit_cuil=data["cuit_cuil"])) if q else models.Q(cuit_cuil=data["cuit_cuil"])
        if data.get("nombre_razon_social") and data.get("email"):
            cond = models.Q(nombre_razon_social=data["nombre_razon_social"], email=data["email"])
            q = (q | cond) if q else cond

        if q:
            existente = Parte.objects.filter(q).first()
            if existente:
                # opcionalmente actualizar campos vacíos
                patch_fields = ["tipo_persona","telefono","email","documento","cuit_cuil"]
                changed = False
                for f in patch_fields:
                    v = data.get(f)
                    if v not in (None, "") and getattr(existente, f) in (None, "",):
                        setattr(existente, f, v)
                        changed = True
                if changed:
                    existente.save()
                return existente

        # crear nuevo
       
        obj = Parte.objects.create(
            tipo_persona=data.get("tipo_persona") or Parte.FISICA,
            nombre_razon_social=data.get("nombre_razon_social") or "",
            documento=data.get("documento"),
            cuit_cuil=data.get("cuit_cuil"),
            email=data.get("email",""),
            telefono=data.get("telefono",""),
            domicilio=data.get("domicilio",""),
        )
        return obj

class CausaParteWriteSerializer(serializers.Serializer):
    parte = ParteWriteSerializer()
   

class ProfesionalWriteSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    nombre = serializers.CharField(required=False)
    apellido = serializers.CharField(required=False)
    matricula = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    telefono = serializers.CharField(required=False, allow_blank=True)

    def get_or_create(self):
        data = self.validated_data
        if "id" in data:
            return Profesional.objects.get(pk=data["id"])

        # Buscar por matrícula (única) o por (apellido, nombre, email)
        if data.get("matricula"):
            existente = Profesional.objects.filter(matricula=data["matricula"]).first()
            if existente:
                # opcionalmente completar datos faltantes
                for f in ("nombre","apellido","email","telefono"):
                    v = data.get(f)
                    if v and not getattr(existente, f):
                        setattr(existente, f, v)
                existente.save()
                return existente

        if data.get("apellido") and data.get("nombre") and data.get("email"):
            existente = Profesional.objects.filter(
                apellido=data["apellido"], nombre=data["nombre"], email=data["email"]
            ).first()
            if existente:
                return existente

        return Profesional.objects.create(
            nombre=data.get("nombre",""),
            apellido=data.get("apellido",""),
            matricula=data.get("matricula",""),
            email=data.get("email",""),
            telefono=data.get("telefono",""),
        )

class CausaProfesionalWriteSerializer(serializers.Serializer):
    profesional = ProfesionalWriteSerializer()
    rol_profesional = serializers.ChoiceField(choices=CausaProfesional.ROLES)

class DocumentoInSerializer(serializers.Serializer):
    titulo = serializers.CharField()
    fecha = serializers.DateField(required=False, allow_null=True)
    # Para MVP: permitir ruta/clave ya subida (S3/Cloudinary) o subir luego.
    archivo = serializers.FileField(required=False, allow_empty_file=False, allow_null=True)
    archivo_key = serializers.CharField(required=False, allow_blank=False)

class EventoInSerializer(serializers.Serializer):
    titulo = serializers.CharField()
    descripcion = serializers.CharField(required=False, allow_blank=True, default="")
    fecha = serializers.DateField()
    plazo_limite = serializers.DateField(required=False, allow_null=True)

class GrafoInSerializer(serializers.Serializer):
    data = serializers.JSONField(required=False)

class CausaFullCreateSerializer(serializers.Serializer):
    # Causa base
    # Generar un idempotency_key automático si no vino
    
    numero_expediente = serializers.CharField()
    caratula = serializers.CharField()
    fuero = serializers.CharField(required=False, allow_blank=True, default="")
    jurisdiccion = serializers.CharField(required=False, allow_blank=True, default="")
    fecha_inicio = serializers.DateField(required=False, allow_null=True)
    estado = serializers.ChoiceField(choices=Causa.ESTADOS, required=False, default="abierta")
    # Idempotencia opcional
    idempotency_key = serializers.CharField(required=False, allow_blank=False)
    # creado_por se toma del user autenticado en la request (view)

    # Anidados
    partes = CausaParteWriteSerializer(many=True, required=False, default=list)
    profesionales = CausaProfesionalWriteSerializer(many=True, required=False, default=list)
    documentos = DocumentoInSerializer(many=True, required=False, default=list)
    eventos = EventoInSerializer(many=True, required=False, default=list)
    grafo = GrafoInSerializer(required=False)

    def create(self, validated_data):
        user = self.context["request"].user
        
        if not validated_data.get("creado_por"):
            validated_data["creado_por"] = user

        idem = validated_data.pop("idempotency_key", None) or f"gpt-{uuid.uuid4()}"
        partes = validated_data.pop("partes", [])
        profesionales = validated_data.pop("profesionales", [])
        documentos = validated_data.pop("documentos", [])
        eventos = validated_data.pop("eventos", [])
        grafo_in = validated_data.pop("grafo", None)
        idem = validated_data.pop("idempotency_key", None)

        # Idempotencia simple: si existe una causa con mismas triple-clave + user y misma idem_key (opcional),
        # la devolvemos. Para no complicar el modelo, lo resolvemos por la constraint + owner.
        existing = Causa.objects.filter(
            numero_expediente=validated_data.get("numero_expediente"),
            fuero=validated_data.get("fuero", ""),
            jurisdiccion=validated_data.get("jurisdiccion", ""),
            creado_por=user,
        ).first()
        if existing and idem:
            return existing

        with transaction.atomic():
            causa = Causa.objects.create(**validated_data)

            # Partes
            for item in partes:
                parte_obj = ParteWriteSerializer(data=item.get("parte"))
                parte_obj.is_valid(raise_exception=True)
                parte = parte_obj.get_or_create()

                CausaParte.objects.get_or_create(
                    causa=causa, parte=parte
                )

            # Profesionales
            for item in profesionales:
                prof_ser = ProfesionalWriteSerializer(data=item["profesional"])
                prof_ser.is_valid(raise_exception=True)
                prof = prof_ser.get_or_create()

                CausaProfesional.objects.get_or_create(
                    causa=causa, profesional=prof,
                    rol_profesional=item["rol_profesional"]
                )

            # Documentos
            for doc in documentos:
                file_field = doc.get("archivo")
                key = doc.get("archivo_key")
                if not file_field and not key:
                    # permitir crear metadata y subir luego
                    Documento.objects.create(causa=causa, titulo=doc["titulo"], fecha=doc.get("fecha"))
                elif file_field:
                    Documento.objects.create(causa=causa, titulo=doc["titulo"],
                                             archivo=file_field, fecha=doc.get("fecha"))
                else:
                    # Si usás un storage que mapea key->name, podés setear .name directamente
                    d = Documento(causa=causa, titulo=doc["titulo"], fecha=doc.get("fecha"))
                    d.archivo.name = key  # p.ej. "causas/123/docs/lo-que-sea.pdf"
                    d.save()

            # Eventos
            bulk_eventos = [
                EventoProcesal(causa=causa,
                               titulo=e["titulo"],
                               descripcion=e.get("descripcion",""),
                               fecha=e["fecha"],
                               plazo_limite=e.get("plazo_limite"))
                for e in eventos
            ]
            if bulk_eventos:
                EventoProcesal.objects.bulk_create(bulk_eventos, batch_size=100)

            # Grafo (opcional)
            # --- Grafo: generar/actualizar de forma idempotente ---
            # Si vino un grafo en el payload lo usamos; si no, lo construimos desde DB.
            if grafo_in and isinstance(grafo_in.get("data"), dict):
                data = grafo_in["data"]
            else:
                from .utils import build_causa_graph
                data = build_causa_graph(causa)

            # Evita el UniqueViolation cuando ya existe para esa causa
            CausaGrafo.objects.update_or_create(causa=causa, defaults={"data": data})
        # Devolver expandido con el serializer de lectura ya existente
        return causa

    def to_representation(self, instance):
        return CausaSerializer(instance).data


class S3TestUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    causa_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_file(self, f):
        allowed_exts = {".pdf", ".doc", ".docx", ".xls", ".xlsx"}
        name = f.name.lower()
        ok = any(name.endswith(ext) for ext in allowed_exts)
        if not ok:
            raise serializers.ValidationError(
                "Formato no permitido. Aceptados: PDF, Word (.doc/.docx) y Excel (.xls/.xlsx)."
            )
        # Opcional: validar tamaño (p.ej., 20MB)
        max_mb = 20
        if f.size > max_mb * 1024 * 1024:
            raise serializers.ValidationError(f"El archivo supera {max_mb} MB.")
        return f