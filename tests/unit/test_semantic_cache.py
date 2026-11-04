from pidreams.memory.cache import SemanticCache


class _TestEmbedder:
    def embed_query(self, text):
        return text

    def similarity(self, a, b):
        return 1.0 if a == b else 0.0


def test_limpar_esquece_respostas_antigas():
    cache = SemanticCache(_TestEmbedder())
    cache.put("quem é você?", "Olá, chefe!")
    assert cache.get("quem é você?") == "Olá, chefe!"
    cache.clear()                     # ex.: tratamento trocado nas configurações
    assert cache.get("quem é você?") is None


def test_resposta_de_ontem_nao_vale_hoje(monkeypatch):
    """"Que dia é hoje?" respondido ontem estaria errado hoje."""
    import datetime as dt

    from pidreams.memory import cache as module

    class _Embedder:
        def embed_query(self, q):
            return [1.0]

        def similarity(self, a, b):
            return 1.0

    c = module.SemanticCache(_Embedder())
    c.put("que dia é hoje?", "Hoje é quinta.")
    assert c.get("que dia é hoje?") == "Hoje é quinta."

    tomorrow = dt.date.today() + dt.timedelta(days=1)

    class _Tomorrow(dt.date):
        @classmethod
        def today(cls):
            return tomorrow

    monkeypatch.setattr(module.dt, "date", _Tomorrow)
    assert c.get("que dia é hoje?") is None
