"""Servidor local compatível com /v1/chat/completions, para demonstrações.

    python scripts/fake_llm.py            # http://127.0.0.1:8799/v1

- O primeiro pedido responde HTTP 429 com Retry-After: 1 (testa o retry).
- Prompts que contenham "Bruno" recebem texto livre, fora do contrato JSON
  (testa a validação da saída e o fallback por template).
- Os restantes recebem JSON válido com 210 tokens de prompt e 60 de resposta.
- FAKE_LLM_FAIL=1 faz todos os pedidos devolverem HTTP 503 (testa o circuit
  breaker sem precisar de derrubar nada).
"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.getenv("FAKE_LLM_PORT", "8799"))
ALWAYS_FAIL = os.getenv("FAKE_LLM_FAIL") == "1"
_calls = 0
_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        pass

    def _reply(self, status: int, payload: dict | None = None, **headers: str) -> None:
        body = json.dumps(payload or {}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - nome exigido pelo http.server
        global _calls
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prompt = request["messages"][-1]["content"]
        with _lock:
            _calls += 1
            call_number = _calls
        if ALWAYS_FAIL:
            self._reply(503, {"error": "indisponível"})
            return
        if call_number == 1:
            self._reply(429, {"error": "rate limited"}, Retry_After="1")
            return
        if "Bruno" in prompt:
            content = "Desculpe, não consigo responder em JSON."
        else:
            content = json.dumps(
                {
                    "bem_em": "Matemática e História, com notas acima da média.",
                    "atencao_em": "Manter a regularidade nas revisões.",
                    "proximos_passos": "Resolver uma lista de exercícios por semana.",
                },
                ensure_ascii=False,
            )
        self._reply(
            200,
            {
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 210, "completion_tokens": 60},
            },
        )


if __name__ == "__main__":
    print(f"LLM falso em http://127.0.0.1:{PORT}/v1 (falha total: {ALWAYS_FAIL})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
