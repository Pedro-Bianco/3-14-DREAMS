# Segurança

## Como relatar uma vulnerabilidade

**Não abra uma issue pública.** Use o relato privado do GitHub: aba **Security** do repositório →
**Report a vulnerability**. Descreva o problema, como reproduzir e o impacto. A resposta vem em
até 7 dias, com o plano de correção; o crédito é seu na nota da versão, se quiser.

## Versões cobertas

Só a versão mais recente recebe correções: o instalador novo instala por cima e mantém memórias,
documentos e configurações.

| Versão | Correções de segurança |
|---|---|
| 1.2.x | sim |
| anteriores | não, atualize |

## O que esperar do PI dreams

- **Local e sem telemetria.** A IA, a voz, a câmera e a memória rodam no computador; não há
  conta nem envio de uso. O que usa a internet, e quando, está na tabela "Privacidade" do
  [README](README.md#privacidade-o-que-fica-e-o-que-sai-do-seu-pc).
- **Áudio** não é gravado em disco: o microfone é lido em memória e descartado depois da
  transcrição; a escuta de palmas na bandeja só mede o volume.
- **Senhas e chaves** (Gmail, agenda, sites) ficam cifradas pelo próprio Windows (DPAPI), presas
  ao usuário do Windows; nunca vão para o `settings.json` nem para o log.
- **Log** em `%LOCALAPPDATA%\PIDreams\logs`: não guarda o texto do que é dito nem respondido, salvo
  se você ligar a opção em Configurações → Avançado.
- **Ações no PC** (abrir e fechar programas, volume, arquivos) só acontecem por ferramentas
  específicas do assistente; ele não executa comandos livres no terminal.
- **Fontes externas** (clima, notícias, Monitoramento, Pesquisa profunda) recebem só o assunto ou
  o lugar consultado, nunca o seu nome ou outros dados do perfil.
- **Instalador**: gerado a partir deste repositório e verificado no VirusTotal antes de cada
  release (o relatório fica na nota da versão). Ele não é assinado digitalmente, então o Windows
  pode mostrar o aviso do SmartScreen; baixe só da
  [página de releases](https://github.com/Pedro-Bianco/3-14-DREAMS/releases).
