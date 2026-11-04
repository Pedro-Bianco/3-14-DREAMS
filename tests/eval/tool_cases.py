"""Casos da avaliação de ferramentas. Só dados fictícios.

Cada caso: frase, ferramentas esperadas (conjunto; vazio = nenhuma), categoria e, opcionais,
mensagens anteriores, câmera ligada e regra dos argumentos (ferramenta -> (campo, trechos
aceitos)). Uma alternativa aceitável entra em "tambem" (ex.: clima pode ser pesquisado).
"""

from dataclasses import dataclass, field


@dataclass
class Case:
    phrase: str
    expected: set[str]
    category: str
    before: list[tuple[str, str]] = field(default_factory=list)
    camera: bool = False
    args: dict[str, tuple[str, tuple[str, ...]]] = field(default_factory=dict)
    also: set[str] | None = None


def _app(phrase, *targets):
    return Case(phrase, {"open_app"}, "explicito", args={"open_app": ("target", targets)})


def _search(phrase, *terms):
    return Case(phrase, {"web_search"}, "explicito", args={"web_search": ("query", terms)})


def _link(phrase, url):
    return Case(phrase, {"scrape_url"}, "explicito", args={"scrape_url": ("url", (url,))})


def _read(phrase):
    return Case(phrase, {"clipboard_read"}, "explicito")


def _copy(phrase, *snippets):
    return Case(phrase, {"clipboard_write"}, "explicito", args={"clipboard_write": ("text", snippets)})


def _nothing(phrase, also=None):
    return Case(phrase, set(), "nao_chamar", also=also)


def _see(phrase):
    return Case(phrase, {"ver_camera"}, "camera_deve", camera=True)


def _dont_look(phrase, also=None):
    return Case(phrase, set(), "camera_nao", camera=True, also=also)


def _off(phrase):
    return Case(phrase, set(), "camera_desligada")


EXPLICIT = [
    _app("Abre a calculadora.", "calc"),
    _app("Abre o bloco de notas pra mim.", "notepad", "bloco"),
    _app("Pode abrir o paint?", "paint"),
    _app("abre o navegador", "chrome", "edge", "firefox", "navegador", "browser"),
    _app("Abra o explorador de arquivos, por favor.", "explorer", "explorador"),
    _app("Você pode abrir o Word?", "word"),
    _app("Preciso que você abra o Excel.", "excel"),
    _app("abre o spotify aí", "spotify"),
    _app("Dá pra abrir o gerenciador de tarefas?", "taskmgr", "gerenciador"),
    _app("Abre o VS Code.", "code"),
    _app("Inicia a calculadora do Windows.", "calc"),
    _app("Liga o bloco de notas aí pra mim", "notepad", "bloco"),
    _search("Pesquisa o preço do dólar hoje.", "dólar", "dolar"),
    _search("Procura na internet as notícias de hoje sobre inteligência artificial.", "inteligência artificial", "ia"),
    _search("Busca na web qual o horário de funcionamento do museu de arte.", "museu"),
    _search("pesquisa receita de bolo de cenoura", "bolo de cenoura"),
    _search("Dá uma pesquisada sobre o lançamento do novo celular da Orbita.", "orbita"),
    _search("Você pode procurar quanto custa uma passagem de ônibus para Campinas?", "passagem", "campinas"),
    _search("Procura pra mim o resultado do jogo de ontem do Atlético Fictício.", "atlético", "atletico", "jogo"),
    _search("Pesquisa no Google como trocar o pneu de uma bicicleta.", "pneu"),
    _search("busca as últimas notícias de economia", "economia"),
    _search("Quero que você pesquise a população do Japão.", "japão", "japao"),
    _search("Pesquisa a cotação do euro.", "euro"),
    _search("Faz uma busca rápida: quem dirigiu o filme O Viajante das Estrelas?", "viajante"),
    _link("Lê esse artigo pra mim: https://example.com/artigo", "https://example.com/artigo"),
    _link("Resume essa página https://example.org/noticia", "https://example.org/noticia"),
    _link("o que diz aqui? https://example.net/post/42", "https://example.net/post/42"),
    _link("https://example.com/receita-de-pao", "https://example.com/receita-de-pao"),
    _link("Dá uma olhada nesse link e me fala se vale a pena: https://example.org/review",
          "https://example.org/review"),
    _link("Lê pra mim https://example.com/blog/dicas-de-sono", "https://example.com/blog/dicas-de-sono"),
    _link("Me explica o que tem nessa página: https://example.net/tutorial", "https://example.net/tutorial"),
    _link("Faz um resumo de https://example.com/relatorio-anual", "https://example.com/relatorio-anual"),
    _link("Achei isso https://example.org/vaga-desenvolvedor o que você acha?",
          "https://example.org/vaga-desenvolvedor"),
    _link("Pode ler https://example.com/manual e me dizer como liga o aparelho?", "https://example.com/manual"),
    _read("O que tem na minha área de transferência?"),
    _read("Lê o que eu acabei de copiar."),
    _read("o que eu copiei?"),
    _read("Dá uma olhada no que tá no meu Ctrl C."),
    _read("Lê a área de transferência pra mim."),
    _read("Copiei um texto, lê ele e me diz do que se trata."),
    _read("Resume o que eu copiei agora há pouco."),
    _read("Tem alguma coisa copiada aí?"),
    _read("Traduz o que eu copiei para o inglês."),
    _read("Corrige os erros do texto que eu copiei."),
    _copy("Copia 'reunião às 15h' para a área de transferência.", "reunião às 15h"),
    _copy("Coloca na área de transferência o texto: lista de compras.", "lista de compras"),
    _copy("copia o número 4002-8922 pra mim", "4002-8922"),
    _copy("Copia pra mim o endereço Rua das Flores, 123.", "Rua das Flores"),
    _copy("Joga na área de transferência: bom dia a todos!", "bom dia a todos"),
    _copy("Copia a palavra paralelepípedo.", "paralelepípedo"),
    _copy("Põe no meu Ctrl C o e-mail contato@example.com", "contato@example.com"),
    _copy("Escreve um parabéns curto para a Ana e copia para a área de transferência.", "Ana"),
    _copy("Copia o código 7781 pra mim colar no site.", "7781"),
    _copy("Me copia a frase 'nos vemos amanhã'.", "nos vemos amanhã"),
]

DONT_CALL = [
    _nothing("Me conta uma piada."),
    _nothing("Quanto é 7 vezes 8?"),
    _nothing("Bom dia!"),
    _nothing("Me ajuda a escrever um e-mail de agradecimento para um colega."),
    _nothing("Você tem olhos?"),
    _nothing("Qual o seu nome?"),
    _nothing("Obrigado, era isso."),
    _nothing("Como você está?"),
    _nothing("Qual a capital da França?"),
    _nothing("Me dá uma dica para dormir melhor."),
    _nothing("Quanto é 15% de 200?"),
    _nothing("Escreve um poema curto sobre o mar."),
    _nothing("O que é fotossíntese?"),
    _nothing("Você consegue ver filmes?"),
    _nothing("Como faço para abrir um arquivo zip no Windows?"),
    _nothing("O que é a área de transferência do computador?"),
    _nothing("Qual a diferença entre copiar e recortar?"),
    _nothing("Me sugere um nome para um cachorro."),
    _nothing("Explica o que é uma URL."),
    _nothing("Pode me chamar de Bia a partir de agora."),
    _nothing("Fala uma curiosidade sobre o espaço."),
    _nothing("Quantos dias tem um ano bissexto?"),
    _nothing("Você prefere gatos ou cachorros?"),
    _nothing("Traduz 'obrigado' para o espanhol."),
    _nothing("Me ajuda a planejar meu dia: tenho academia, trabalho e mercado."),
    _nothing("Boa noite, até amanhã."),
    _nothing("Qual é o maior planeta do sistema solar?"),
    _nothing("Resume em uma frase o que é inteligência artificial."),
    _nothing("Me lembra o que é um número primo?"),
    _nothing("Que horas são mais ou menos no Japão quando aqui é meio-dia?"),
]

CAMERA = [
    _see("Tô bonito hoje?"),
    _see("Você está conseguindo me ver?"),
    _see("Tá me vendo?"),
    _see("Como eu estou hoje?"),
    _see("O que eu tô segurando?"),
    _see("Que cor é a minha camisa?"),
    _see("Consegue ler esse papel aqui?"),
    _see("Gostou do meu corte de cabelo?"),
    _see("Quantos dedos eu tô mostrando?"),
    _see("Olha essa caneca que eu ganhei."),
    _see("O que tem atrás de mim?"),
    _see("Eu pareço cansado?"),
    _see("Lê o que tá escrito nessa caixa."),
    _see("Essa roupa combina?"),
    _see("Tô usando óculos agora?"),
    _dont_look("Qual a previsão do tempo amanhã?", also={"web_search"}),
    _dont_look("Você consegue ver filmes?"),
    _dont_look("Me conta uma piada."),
    _dont_look("Você tem olhos?"),
    _dont_look("Como está o dia hoje?", also={"web_search"}),
    _dont_look("Me lembra de beber água.", also={"criar_lembrete"}),      # com os lembretes, criar é o certo
    _dont_look("Qual o seu nome?"),
    _dont_look("Quanto é 12 mais 30?"),
    _dont_look("O que você acha de ficção científica?"),
    _dont_look("Me explica como funciona uma câmera fotográfica."),
    _dont_look("Boa tarde!"),
    _dont_look("Escreve uma mensagem de aniversário para minha tia."),
    _off("Tá me vendo?"),
    _off("O que eu tô segurando?"),
    _off("Que cor é a minha camisa?"),
    _off("Como eu estou hoje?"),
    _off("Quantos dedos eu tô mostrando?"),
]

_CHAT_LINK = [("user", "Olha esse link depois: https://example.com/receita-de-lasanha"),
                  ("assistant", "Anotado. Quando quiser, eu leio essa receita para você.")]
_CHAT_CAPITAL = [("user", "Qual a capital da Austrália?"),
                     ("assistant", "A capital da Austrália é Camberra.")]
_LONG_CHAT = [("user", "Bom dia!"), ("assistant", "Bom dia! Como posso ajudar?"),
                   ("user", "Tô pensando em aprender violão."),
                   ("assistant", "Ótima ideia. Comece com acordes básicos, uns 15 minutos por dia."),
                   ("user", "Valeu pela dica."), ("assistant", "Disponha.")]

CHAT = [
    Case("Lê aquele link que eu te mandei.", {"scrape_url"}, "chat", before=_CHAT_LINK,
         args={"scrape_url": ("url", ("https://example.com/receita-de-lasanha",))}),
    Case("Copia isso que você falou.", {"clipboard_write"}, "chat", before=_CHAT_CAPITAL,
         args={"clipboard_write": ("text", ("Camberra",))}),
    Case("Pesquisa mais sobre essa cidade.", {"web_search"}, "chat", before=_CHAT_CAPITAL,
         args={"web_search": ("query", ("camberra", "canberra"))}),
    Case("Abre a calculadora.", {"open_app"}, "chat", before=_LONG_CHAT,
         args={"open_app": ("target", ("calc",))}),
    Case("Pesquisa o preço de um violão para iniciante.", {"web_search"}, "chat",
         before=_LONG_CHAT, args={"web_search": ("query", ("violão", "violao"))}),
    Case("Me conta uma piada sobre música.", set(), "chat", before=_LONG_CHAT),
    Case("Quantos acordes básicos existem mais ou menos?", set(), "chat", before=_LONG_CHAT),
    Case("O que tem na minha área de transferência?", set() | {"clipboard_read"}, "chat",
         before=_LONG_CHAT),
    Case("Valeu!", set(), "chat", before=_CHAT_CAPITAL),
    Case("E a da Argentina?", set(), "chat", before=_CHAT_CAPITAL),
    Case("Tá me vendo agora?", {"ver_camera"}, "chat", before=_LONG_CHAT, camera=True),
    Case("Lembra qual era a cidade? Copia o nome dela.", {"clipboard_write"}, "chat",
         before=_CHAT_CAPITAL + _LONG_CHAT, args={"clipboard_write": ("text", ("Camberra",))}),
]

TWO_ACTIONS = [
    Case("Pesquisa a cotação do dólar e copia o resultado.", {"web_search", "clipboard_write"}, "duas_acoes"),
    Case("Abre a calculadora e o bloco de notas.", {"open_app"}, "duas_acoes"),
    Case("Lê o que eu copiei e pesquisa sobre isso.", {"clipboard_read", "web_search"}, "duas_acoes"),
    Case("Lê https://example.com/artigo e copia o título.", {"scrape_url", "clipboard_write"}, "duas_acoes"),
    Case("Abre o navegador e pesquisa receitas de sopa.", {"open_app", "web_search"}, "duas_acoes",
         also={"web_search"}),
]

# Ações no PC: poucas frases no conjunto geral, para a escolha entre elas e as outras
# ferramentas aparecer nas próximas medições (o detalhe está em tests/eval/pc_actions.py).
PC = [
    Case("Abaixa o volume.", {"mudar_volume"}, "pc"),
    Case("Pausa a música.", {"controlar_musica"}, "pc"),
    Case("Traz o Chrome pra frente.", {"mexer_janela"}, "pc", also={"open_app"}),
    Case("Fecha o Bloco de Notas.", {"fechar_app"}, "pc"),
    Case("Desliga o computador.", {"desligar_pc"}, "pc"),
    _nothing("O volume daquele show estava alto demais."),
]

CASES = EXPLICIT + DONT_CALL + CAMERA + CHAT + TWO_ACTIONS + PC

# Validação: frases escritas à parte e NUNCA usadas para ajustar regras ou instruções. Medem
# se o ajuste generaliza ou só decorou os CASOS acima (--validacao na avaliação).
VALIDATION = [
    _app("Abre aí o editor de texto.", "notepad", "bloco", "editor", "word"),
    _app("Será que você consegue abrir a calculadora pra mim?", "calc"),
    _app("Por gentileza, abra o Paint.", "paint"),
    _app("Me abre o Chrome.", "chrome"),
    _app("Quero o bloco de notas aberto.", "notepad", "bloco"),
    _app("Executa o prompt de comando.", "cmd", "prompt"),
    _app("Bota o Spotify pra abrir.", "spotify"),
    _search("Dá um Google em como fazer pão caseiro.", "pão", "pao"),
    _search("Vê na internet se vai chover em Curitiba amanhã.", "curitiba"),
    _search("Descobre pra mim o horário do jogo da seleção.", "seleção", "selecao", "jogo"),
    _search("Me procura o telefone da pizzaria Bella Fictícia.", "pizzaria", "bella"),
    _search("Quanto está o bitcoin agora? Pesquisa aí.", "bitcoin"),
    _search("Faz uma pesquisa sobre buracos negros.", "buracos negros", "buraco negro"),
    _link("Dá uma lida em https://example.com/noticia-do-dia", "https://example.com/noticia-do-dia"),
    _link("Vê o que tem em https://example.org/promocao", "https://example.org/promocao"),
    _link("Tem como resumir https://example.net/artigo-longo ?", "https://example.net/artigo-longo"),
    _link("Esse aqui é bom? https://example.com/curso", "https://example.com/curso"),
    _read("Fala o que tá no meu clipboard."),
    _read("O que ficou copiado?"),
    _read("Lê pra mim o trecho que copiei."),
    _read("Explica o texto que tá na área de transferência."),
    _copy("Manda pra área de transferência: até logo.", "até logo"),
    _copy("Deixa copiado o CEP 01001-000.", "01001-000"),
    _copy("Grava na área de transferência a senha do wi-fi: casa123.", "casa123"),
    _copy("Copia isso: amanhã sem falta.", "amanhã sem falta"),
    _nothing("Como se escreve exceção?"),
    _nothing("Me fala um fato curioso sobre polvos."),
    _nothing("Quanto é 9 ao quadrado?"),
    _nothing("Você sabe abrir garrafas?"),
    _nothing("O que significa copiar e colar?"),
    _nothing("Qual a melhor forma de pesquisar para uma prova?"),
    _nothing("Tô cansado hoje."),
    _nothing("Me diz um sinônimo de feliz."),
    _nothing("Valeu, você é demais."),
    _nothing("Como funciona a internet?"),
    _see("Tá vendo minha cara?"),
    _see("Que objeto é esse na minha mão?"),
    _see("Repara no meu cabelo novo."),
    _see("Tô com cara de sono?"),
    _see("Consegue ver o que tem na mesa?"),
    _dont_look("Você enxerga cores?"),
    _dont_look("Qual a sua cor favorita?"),
    _dont_look("Me conta como foi o seu dia."),
    _off("Tá vendo minha cara?"),
    _off("Que objeto é esse na minha mão?"),
    Case("Coloca o som no mudo.", {"silenciar"}, "pc"),
    Case("Quais janelas estão abertas?", {"ver_janelas"}, "pc"),
    Case("Reinicia o PC daqui a 5 minutos.", {"reiniciar_pc"}, "pc"),
    _nothing("Minha mãe sempre fecha as janelas quando chove."),
]
