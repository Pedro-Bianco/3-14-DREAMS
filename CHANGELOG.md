# Mudanças

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões seguem
[Versionamento Semântico](https://semver.org/lang/pt-BR/). Cada versão tem o instalador e as
notas completas na [página de releases](https://github.com/Pedro-Bianco/3-14-DREAMS/releases).

## [Não lançado]

### Melhorado

- O Monitoramento mostra satélites, terremotos e rádios na hora: as camadas carregam ao mesmo
  tempo e a cópia guardada aparece primeiro, trocada quando a fonte responde.

### Corrigido

- Um barulho durante a calibração do microfone não impede mais o PI de perceber o fim da fala.
- No modo voz, texto digitado interrompe a escuta e é respondido em voz.
- A Base responde com documentos curtos (com poucos trechos, antes nada passava do limite).

## [1.2.0] - 2026-11-09

### Adicionado

- Abertura animada: anéis em estilo HUD com o progresso seguindo as etapas reais do carregamento
  e um som de abertura original (pode ser desligado em Configurações → Áudio e voz).

### Melhorado

- Abre mais rápido: reconhecimento de voz, voz, modelo de conversa e memória carregam ao mesmo
  tempo (de ~32 s para ~12 s no PC de referência).

### Corrigido

- Buscas na web levam só o assunto pesquisado; quando o PI não consegue ler os resultados, diz
  que abriu a busca no navegador.
- "Apague os lembretes" tira todos de uma vez.

## [1.1.0] - 2026-11-09

### Adicionado

- Reconhecimento de voz na placa de vídeo Intel (Whisper large-v3-turbo via OpenVINO): de ~1,4 s
  para ~0,1 s por fala, com escolha automática e nas configurações.
- Rotinas ("protocolos") disparadas por frase, como "modo trabalho".
- Lembretes avisados com o PI dormindo (voz e notificação do Windows); entende "daqui a 10
  minutos" e "às 11 e 20".
- Botão "Só com PI": responde só quando a frase começa com o nome dele.

### Privacidade

- O log não guarda mais o texto do que é dito nem do que o PI responde (opção em Configurações →
  Avançado para investigar problemas, desligada por padrão).

## [1.0.1] - 2026-11-09

### Corrigido

- O instalador não leva mais o caminho da máquina que o gerou; o build confere isso.

## [1.0.0] - 2026-11-09

### Adicionado

- Modo bandeja: dormir sem janela e sem o modelo na placa de vídeo, acordando em ~3 s.
- Duas palmas ou um clique no ícone acordam o PI; calibração das palmas nas configurações.
- Iniciar junto com o Windows e fechar por completo ao abrir um jogo.

### Corrigido

- O Monitoramento e a Pesquisa profunda abrem e fecham com frases livres.
- Abrir um programa que não existe responde "não encontrei" em vez de uma confirmação falsa.

## [0.9.2] - 2026-11-07

### Corrigido

- O app instalado voltou a abrir (faltava um módulo das conexões na 0.9.0 e na 0.9.1) e a voz
  padrão voltou a falar; o build agora abre o app empacotado e confere todos os módulos.

## [0.9.1] - 2026-11-07

### Adicionado

- Globo do Monitoramento desenhado pela placa de vídeo (OpenGL), com o GDI do Windows como
  reserva, e abertura em tela cheia.

## [0.9.0] - 2026-11-04

### Adicionado

- Voz padrão nova, em streaming, e vozes Kokoro opcionais com efeito de assistente.
- Testes e avaliações no repositório, rodando no GitHub Actions a cada envio.

### Melhorado

- Do fim da fala à resposta: de 8–12 s para 2–4 s (resposta em streaming, Qwen3 8B inteiro na
  placa de vídeo de até 16 GB).
- Interromper falando por cima separa a voz do eco das caixas de som.

## [0.8.0] - 2026-11-03

### Adicionado

- Aviões em tempo real no Monitoramento, com rastros, detalhes do voo e comandos por voz.

## [0.7.3] - 2026-11-03

### Mudado

- Notícias, busca na web e clima só por caminhos que os serviços permitem (feeds dos veículos,
  Wikipédia, Open-Meteo com crédito); o PI se identifica em todas as fontes que consulta.

## [0.7.2] - 2026-11-03

### Mudado

- Revisão de licenças e termos de uso: câmera com o Qwen3-VL 2B (Apache-2.0), rádios pelo DNS do
  Radio Browser e licenças documentadas em `THIRD_PARTY_NOTICES.md`.

[Não lançado]: https://github.com/Pedro-Bianco/3-14-DREAMS/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/Pedro-Bianco/3-14-DREAMS/releases/tag/v1.2.0
[1.1.0]: https://github.com/Pedro-Bianco/3-14-DREAMS/releases/tag/v1.1.0
[1.0.1]: https://github.com/Pedro-Bianco/3-14-DREAMS/releases/tag/v1.0.1
[1.0.0]: https://github.com/Pedro-Bianco/3-14-DREAMS/releases/tag/v1.0.0
[0.9.2]: https://github.com/Pedro-Bianco/3-14-DREAMS/releases/tag/v0.9.2
[0.9.1]: https://github.com/Pedro-Bianco/3-14-DREAMS/releases/tag/v0.9.1
[0.9.0]: https://github.com/Pedro-Bianco/3-14-DREAMS/releases/tag/v0.9.0
[0.8.0]: https://github.com/Pedro-Bianco/3-14-DREAMS/releases/tag/v0.8.0
[0.7.3]: https://github.com/Pedro-Bianco/3-14-DREAMS/releases/tag/v0.7.3
[0.7.2]: https://github.com/Pedro-Bianco/3-14-DREAMS/releases/tag/v0.7.2
