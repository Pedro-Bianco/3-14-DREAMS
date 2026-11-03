# Avisos de terceiros

O **código do PI dreams** é distribuído sob a licença [MIT](LICENSE).

O **instalador para Windows** (`PIDreams-Setup-*.exe`) embute bibliotecas de terceiros.
Uma delas, o **Piper** (síntese de voz), é **GPL-3.0-or-later** e traz o **eSpeak NG**
(também GPL-3.0). Por isso, **o instalador como um todo é distribuído sob a GPL-3.0**
([texto](LICENSES/GPL-3.0.txt)): você pode redistribuí-lo e modificá-lo nesses termos, e o
código-fonte completo correspondente é este repositório. A licença MIT do código do PI dreams é
compatível com a GPL-3.0.

## Componentes embutidos no instalador

| Componente | Uso no PI dreams | Licença |
|---|---|---|
| [piper-tts](https://github.com/OHF-Voice/piper1-gpl) + eSpeak NG | Voz (síntese de fala) | GPL-3.0-or-later |
| [num2words](https://github.com/savoirfairelinux/num2words) | Números por extenso na fala | LGPL-2.1 ([texto](LICENSES/LGPL-2.1.txt)) |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [CTranslate2](https://github.com/OpenNMT/CTranslate2) | Reconhecimento de voz | MIT |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | Execução de modelos (voz, memória) | MIT |
| [Ollama Python](https://github.com/ollama/ollama-python) | Cliente do Ollama | MIT |
| [qdrant-client](https://github.com/qdrant/qdrant-client) | Memória vetorial local | Apache-2.0 |
| [FastEmbed](https://github.com/qdrant/fastembed) | Embeddings da memória | Apache-2.0 |
| [OpenCV](https://github.com/opencv/opencv-python) | Câmera | Apache-2.0 |
| [LangChain text splitters / experimental / core / community](https://github.com/langchain-ai/langchain) | Divisão de texto da base de conhecimento | MIT |
| [tiktoken](https://github.com/openai/tiktoken) | Divisão por tokens | MIT |
| [NumPy](https://numpy.org/) | Cálculo numérico | BSD-3-Clause (e outras permissivas) |
| [Pillow](https://python-pillow.org/) | Imagens (rosto, câmera) | MIT-CMU |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) | Microfone e alto-falante | MIT |
| [psutil](https://github.com/giampaolo/psutil) | Monitor do sistema | BSD-3-Clause |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | Conexão com servidores MCP | MIT |
| [icalendar](https://github.com/collective/icalendar), [recurring-ical-events](https://github.com/niccokunzmann/python-recurring-ical-events) (+ x-wr-timezone, python-dateutil) | Leitura da agenda | BSD-2-Clause, LGPL-3.0-or-later, Apache-2.0/BSD |
| [tzdata](https://github.com/python/tzdata) | Tabela de fusos horários | Apache-2.0 |
| [pypdf](https://github.com/py-pdf/pypdf) | Texto de PDFs na base de conhecimento | BSD-3-Clause |
| [pyperclip](https://github.com/asweigart/pyperclip) | Área de transferência | BSD-3-Clause |
| [sgp4](https://github.com/brandon-rhodes/python-sgp4) | Posição dos satélites (Monitoramento) | MIT |
| [miniaudio](https://github.com/irmen/pyminiaudio) | Rádios MP3 (Monitoramento) | MIT |
| Python 3.12 (embutido pelo PyInstaller) | Runtime | PSF License |

## Distribuídos junto, mas não código

| Item | Licença |
|---|---|
| Voz `pt_BR-faber-medium` ([Piper voices](https://huggingface.co/rhasspy/piper-voices)) | Dataset CC0 (domínio público) |
| Geometria do rosto 3D (`pidreams/ui/assets/face_mesh.json`), convertida do [canonical face model do MediaPipe](https://github.com/google-ai-edge/mediapipe) (Copyright The MediaPipe Authors) | Apache-2.0 (`LICENSES/Apache-2.0.txt`); modificada: vértices arredondados, triângulos e arestas, sem textura |
| Ícone (`installer/assets/pidreams.ico`) | Gerado por código; MIT |
| Contornos dos países (`pidreams/assets/world_110m.json`), derivados do [Natural Earth](https://www.naturalearthdata.com) 1:110m | Domínio público |

## Dados consultados pelo Monitoramento e pela Pesquisa profunda (só em uso, nada é redistribuído)

| Fonte | Para quê | Termos |
|---|---|---|
| Feeds de notícias da [Agência Brasil](https://agenciabrasil.ebc.com.br), [BBC News Brasil](https://www.bbc.com/portuguese), [DW Brasil](https://www.dw.com/pt-br), [ONU News](https://news.un.org/pt) e [RTP](https://www.rtp.pt/noticias) | Manchetes (Monitoramento, Pesquisa profunda e busca na web) | Feeds RSS que os veículos publicam para leitores, liberados no robots.txt de cada um; cada notícia sai com o nome do veículo e o link |
| [The GDELT Project](https://www.gdeltproject.org) | Notícias (reserva) | Uso livre e irrestrito com citação e link; no máximo uma consulta a cada 5 s |
| [Wikipédia](https://www.wikipedia.org) (API) | Pesquisa profunda e busca na web | Textos sob CC BY-SA 4.0; os relatórios citam cada artigo e registram a licença |
| [Open-Meteo](https://open-meteo.com) | Clima e nomes de lugares | CC BY 4.0, uso não comercial; crédito com link ao lado do clima no app. Os nomes de lugares vêm do [GeoNames](https://www.geonames.org) (CC BY 4.0) |
| [USGS Earthquake Hazards](https://earthquake.usgs.gov) | Terremotos | Domínio público (governo dos EUA) |
| [CelesTrak](https://celestrak.org) | Órbitas e catálogo de satélites | Dados públicos; baixados no máximo a cada 6 h |
| [adsb.lol](https://adsb.lol) | Voos | Dados abertos (ODbL), com atribuição |
| [Radio Browser](https://www.radio-browser.info) | Catálogo de rádios | Domínio público, livre para apps; servidores descobertos pelo DNS, como pedem as regras; cada transmissão é da sua rádio |

## Baixados durante a instalação (não redistribuídos por este projeto)

Cada um sob a licença do autor, que você aceita ao baixar:
[Ollama](https://github.com/ollama/ollama) (MIT); modelos de conversa **Qwen3 4B Instruct**, **Qwen3 8B**
e **Qwen 2.5 14B** e o de visão **Qwen3-VL 2B** (todos Apache-2.0, via Ollama), escolhidos pelo
hardware; **Whisper** small (MIT, versão CTranslate2 da Systran) e
**multilingual-e5-large** (MIT, versão ONNX da Qdrant).
