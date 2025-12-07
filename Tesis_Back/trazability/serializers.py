from rest_framework import serializers
from .models import Trazability, Move

class MoveSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    causa_id = serializers.IntegerField(source='causa.id', read_only=True)
    trazability_id = serializers.CharField(source='trazability.id', read_only=True)

    class Meta:
        model = Move
        fields = [
            'id',
            'trazability_id',
            'causa_id',
            'user_name',
            'user_id',
            'timestamp',
            'action',
            'entity_type',
            'previous_value',
            'summary'
        ]
        read_only_fields = fields


class TrazabilitySerializer(serializers.ModelSerializer):
    causa_id = serializers.IntegerField(source='causa.id', read_only=True)
    moves = serializers.SerializerMethodField()

    class Meta:
        model = Trazability
        fields = ['id', 'causa_id', 'moves']

    def get_moves(self, obj):
        """Retorna los últimos 10 movimientos por defecto"""
        limit = self.context.get('moves_limit', 10)
        recent_moves = obj.get_recent_moves(limit=limit)
        return MoveSerializer(recent_moves, many=True).data


class TrazabilityDetailSerializer(serializers.ModelSerializer):
    """Para el endpoint que trae todos los movimientos"""
    causa_id = serializers.IntegerField(source='causa.id', read_only=True)
    moves = MoveSerializer(many=True, read_only=True)

    class Meta:
        model = Trazability
        fields = ['id', 'causa_id', 'moves']