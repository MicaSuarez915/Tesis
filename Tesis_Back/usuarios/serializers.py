from rest_framework import serializers
from .models import Usuario, Rol, EstudioJuridico, EstudioUsuario

class RolSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rol
        fields = "__all__"

class HealthCheckSerializer(serializers.Serializer):
    status = serializers.CharField(default="OK")

class UsuarioSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)
    serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)

    class Meta:
        model = Usuario
        fields = ["id", "email", "first_name", "last_name", "matricula_id", "telefono", "rol", "creado_en", "password"]
        read_only_fields = ["id", "creado_en"]

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        user = Usuario(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        return user

class EstudioJuridicoSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstudioJuridico
        fields = "__all__"

class UsuarioMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Usuario
        fields = ["id", "email", "first_name", "last_name", "telefono", "rol", "creado_en"]
        read_only_fields = ["id", "creado_en"]
        
class EstudioUsuarioSerializer(serializers.ModelSerializer):
    # ⇩⇩ Mostrar detalle anidado (solo lectura)
    usuario = UsuarioMiniSerializer(read_only=True)
    estudio = EstudioJuridicoSerializer(read_only=True)
    rol = RolSerializer(read_only=True)

    # ⇩⇩ Aceptar IDs al crear/editar (solo escritura)
    usuario_id = serializers.PrimaryKeyRelatedField(
        source="usuario", queryset=Usuario.objects.all(), write_only=True
    )
    estudio_id = serializers.PrimaryKeyRelatedField(
        source="estudio", queryset=EstudioJuridico.objects.all(), write_only=True
    )
    rol_id = serializers.PrimaryKeyRelatedField(
        source="rol", queryset=Rol.objects.all(), write_only=True
    )

    class Meta:
        model = EstudioUsuario
        fields = [
            "id", "fecha_alta", "fecha_baja", "vigente", "permisos",
            "usuario", "estudio", "rol",          # ← lecturas anidadas
            "usuario_id", "estudio_id", "rol_id", # ← escritura por ID
        ]