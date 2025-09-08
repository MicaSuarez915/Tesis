from rest_framework import serializers


class CausaSummaryDBRequestSerializer(serializers.Serializer):
    max_words = serializers.IntegerField(required=False, min_value=80, default=300)
    style = serializers.ChoiceField(choices=["neutral","executive","legal-brief"], default="legal-brief")
    # no pedimos include_doc_text_field



class CausaSummaryDBResponseSerializer(serializers.Serializer):
    causa_id = serializers.IntegerField()
    summary = serializers.CharField()
    engine = serializers.CharField()

class GrammarCheckRequestSerializer(serializers.Serializer):
    text = serializers.CharField()

class GrammarCheckResponseSerializer(serializers.Serializer):
    corrected_text = serializers.CharField()
    issues = serializers.ListField(child=serializers.DictField())
    engine = serializers.CharField()