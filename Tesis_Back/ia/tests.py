from unittest.mock import patch
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework.authtoken.models import Token


class IATestCase(APITestCase):
    """Pruebas básicas para los endpoints de IA."""

    def setUp(self) -> None:
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="tester", password="pass1234")
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    @patch("ia.views.summarize_text.delay")
    def test_summarize_endpoint(self, mock_delay):
        mock_delay.return_value.get.return_value = "resumen"
        response = self.client.post("/api/ia/summarize/", {"text": "texto largo"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["summary"], "resumen")

    @patch("ia.views.grammar_check_text.delay")
    def test_grammar_check_endpoint(self, mock_delay):
        mock_delay.return_value.get.return_value = "texto corregido"
        response = self.client.post("/api/ia/grammar-check/", {"text": "texto malo"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["corrected_text"], "texto corregido")
