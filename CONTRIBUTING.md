# Como contribuir

Obrigado pelo interesse! Issues e pull requests são bem-vindos, em português. Ao participar,
você concorda com o [Código de Conduta](CODE_OF_CONDUCT.md).

## Preparar o ambiente

Requer Windows 10 ou 11, o [Python 3.12 do python.org](https://www.python.org/downloads/) (não o
da Microsoft Store: a sandbox dele bloqueia a câmera) e o [Ollama](https://ollama.com).

```powershell
git clone https://github.com/Pedro-Bianco/3-14-DREAMS
cd 3-14-DREAMS
python -m venv .venv-dev
.venv-dev\Scripts\pip install -r requirements\build.txt
.venv-dev\Scripts\python -m pidreams          # abre o app
```

## Antes de abrir um pull request

```powershell
.venv-dev\Scripts\python -m pytest -q                  # sem rede, sem placa de vídeo e sem modelos
.venv-dev\Scripts\python -m tests.eval.<nome>          # opcional: avaliações com os modelos reais
```

Todo pull request passa pela CI no Windows. Feche o PI antes de rodar os testes: um deles confere
que só uma instância abre e falha com o app aberto.

## Regras do projeto

- **Código, nomes, comentários e logs em inglês; interface, prompts, ferramentas do assistente e
  documentação em português do Brasil.**
- **Só dados fictícios** em código, testes, capturas de tela e vídeos (ex.: "Ana Exemplo",
  "Cidade Exemplo"). Nunca dados pessoais reais, credenciais ou chaves; um teste procura isso em
  todos os arquivos versionados. Capturas mostram só a janela do PI, nunca a tela inteira.
- **Local e grátis**: a IA roda no computador da pessoa. Recurso novo não pode exigir conta,
  chave paga ou nuvem; fontes de dados externas são consultadas só em uso e com os termos de uso
  respeitados (registre em `THIRD_PARTY_NOTICES.md`).
- **Medir antes de afirmar**: números de qualidade ou velocidade no README vêm de medições
  (`tests/eval`, logs do app). Mudança em prompt, limiar ou modelo só entra com a medição de antes
  e depois.
- **Testes não mexem nos dados reais**: nada de gravar no `settings.json` ou na memória de quem
  roda os testes; use pastas temporárias.
- **Simplicidade**: entre duas soluções, a com menos código e menos dependências; nada de
  abstração sem um uso real.

## Licenças

O código é MIT. Dependência ou modelo novo precisa de licença compatível com uso num assistente
pessoal distribuído de graça; registre em `THIRD_PARTY_NOTICES.md` e, se for embutido no
instalador, a licença completa em `LICENSES/`.

## Relatar problemas

Abra uma issue pelo formulário (problema ou melhoria), com o que você fez, o que esperava e o que
aconteceu. O log fica em `%LOCALAPPDATA%\PIDreams\logs` e não guarda o texto das conversas, mas
confira antes de anexar. Não inclua dados pessoais. Falhas de segurança: veja
[SECURITY.md](SECURITY.md).
