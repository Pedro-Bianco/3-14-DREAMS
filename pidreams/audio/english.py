"""English words respelled the way a Brazilian reads them, for the Portuguese voice only.

The Pocket TTS Portuguese model reads every word with Portuguese spelling rules: on 2026-11-04,
transcribed back with Whisper, "YouTube" came out as "coxo", "show" as "sul" and "YAGNI" vanished.
Here the English pronunciation comes from eSpeak NG (already shipped for the Kokoro voices) and its
phonemes are written back with Portuguese letters ("YouTube" → "iutúbi"). The text on screen is
not touched.
"""

import functools
import re

# Words that look Portuguese but the assistant uses in English (BR loanwords read the English way).
_KNOWN = {"site", "sites", "mouse", "online", "offline", "code", "app", "apps", "live", "game", "games", "home",
          "office", "mobile", "chat", "clean", "simple", "need", "update", "upgrade", "bug", "bugs", "login",
          "logout", "drive", "stream", "streaming", "play", "store", "cloud", "web", "feed", "gonna", "chrome",
          "mail", "email", "e-mail", "transformer", "transformers", "prompt", "prompts", "deep", "learning",
          "google", "zoom", "cool", "good", "deadline", "dream", "dreams", "real-time", "machine", "free", "team", "meeting"}
# The way Brazilians already say some of them, which the American phonemes miss ("online" came out
# as "amém"). Checked by transcribing the voice back with Whisper (2026-11-04).
_BRAZILIAN = {"online": "onláin", "offline": "ofláin", "e-mail": "iméiu", "email": "iméiu", "emails": "iméius",
              "deadline": "dédi láin", "clean": "clín", "code": "códi", "yagni": "iágui ní", "app": "épi",
              "apps": "épis", "site": "sáiti", "sites": "sáitis", "live": "láivi"}

# Short English words that could also be read as Portuguese: English only between English words. The
# ones far more common in Portuguese ("a", "no", "do", "me", "as", "se") are never taken as English.
_FUNCTION = {"the", "an", "and", "of", "to", "for", "you", "are", "not", "is", "on", "in", "it", "with", "by",
             "be", "or", "at", "my", "we", "he", "she", "if"}
_PORTUGUESE = {"a", "o", "e", "no", "na", "do", "da", "me", "te", "se", "as", "os", "so", "em", "um", "de"}
# Spelling a Portuguese word never has. ("oo", "ea" and "ee" are left out: voo, teatro, leem.)
_ENGLISH_LOOK = re.compile(r"[kwy]|th|sh|ck|ph|[^aeiou\W\d_]{3,}$|[bdfgkpt]$", re.I)
# Whole words, accented letters included: "até" must not be read as "at" + "é".
_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")

# IPA (eSpeak en-us) → Portuguese letters. Longest symbols first.
_SOUNDS = [
    ("tʃ", "tch"), ("dʒ", "dj"), ("aɪ", "ai"), ("aʊ", "au"), ("ɔɪ", "ói"), ("eɪ", "ei"), ("oʊ", "ou"),
    ("ɑː", "a"), ("iː", "i"), ("uː", "u"), ("ɔː", "ó"), ("ɜː", "âr"), ("ɚ", "âr"), ("ɝ", "âr"),
    ("ɪ", "i"), ("ᵻ", "i"), ("ɛ", "é"), ("æ", "é"), ("ʌ", "â"), ("ɑ", "a"), ("ɔ", "ó"), ("ʊ", "u"),
    ("ə", "a"), ("i", "i"), ("e", "ê"), ("o", "ô"), ("u", "u"), ("a", "a"),
    ("ʃ", "ch"), ("ʒ", "j"), ("θ", "t"), ("ð", "d"), ("ŋ", "n"), ("ɹ", "r"), ("ɾ", "d"), ("ɡ", "g"),
    ("j", "i"), ("w", "u"), ("h", "rr"), ("p", "p"), ("b", "b"), ("t", "t"), ("d", "d"), ("k", "k"),
    ("f", "f"), ("v", "v"), ("s", "s"), ("z", "z"), ("m", "m"), ("n", "n"), ("l", "l"),
]
_VOWELS = set("aeiouáéíóúâêô")
_STRESSED = str.maketrans("aiu", "áíú")
_FINAL_STOP = re.compile(r"(tch|dj|ch|[pbtdkgfv])$")    # Brazilians add an "i" after these: "tube" → "túbi"


def _looks_english(word: str) -> bool:
    """Acronyms in capitals only with K, W or Y ("OK", "KISS"): "PI", "SUS" and "CPF" are ours."""
    if not word.isascii() or word.lower() in _FUNCTION | _PORTUGUESE:     # an accent: Portuguese
        return False
    if word.isupper() and len(word) > 1:
        return bool(re.search(r"[KWY]", word))
    return word.lower() in _KNOWN or bool(_ENGLISH_LOOK.search(word))


def _english_words(text: str) -> list[re.Match]:
    words = list(_WORD.finditer(text))
    english = [_looks_english(m.group()) for m in words]
    for n, m in enumerate(words):
        if m.group().lower() in _FUNCTION and m.group().isascii():
            # "Keep It Simple": between English words (or at an end, next to one). "no Google" stays.
            sides = [english[k] for k in (n - 1, n + 1) if 0 <= k < len(words)]
            english[n] = bool(sides) and all(sides)
    return [m for m, is_english in zip(words, english) if is_english]


@functools.lru_cache(maxsize=1)
def _phonemize():
    import espeakng_loader
    from phonemizer.backend.espeak.wrapper import EspeakWrapper

    EspeakWrapper.set_library(espeakng_loader.get_library_path())
    EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
    from phonemizer.backend import EspeakBackend

    backend = EspeakBackend("en-us", with_stress=True, preserve_punctuation=False)
    return lambda words: backend.phonemize(words, strip=True)


def _spell(ipa: str) -> str:
    """One word's phonemes in Portuguese letters, the stressed vowel accented."""
    out, stressed, i = [], False, 0
    while i < len(ipa):
        ch = ipa[i]
        if ch == "ˈ":
            stressed, i = True, i + 1
            continue
        if ch in "ˌ ":
            i += 1
            continue
        for sound, letters in _SOUNDS:
            if ipa.startswith(sound, i):
                if stressed and letters[0] in "aiu":
                    letters, stressed = letters[0].translate(_STRESSED) + letters[1:], False
                elif letters[0] in _VOWELS:
                    stressed = False
                out.append(letters)
                i += len(sound)
                break
        else:
            i += 1                                           # a symbol with no Portuguese letter
    word = re.sub(r"(?<=[^aeiouáéíóúâêô])al$", "ou", "".join(out))   # final dark L: "simple" → "símpou"
    if _FINAL_STOP.search(word):
        word += "i"
    if re.match(r"s[^aeiouáéíóúâêô]", word):                 # "spotify" → "ispótifai"
        word = "i" + word
    word = re.sub(r"k(?=[eiéêí])", "qu", word).replace("k", "c")
    word = re.sub(r"g(?=[eiéêí])", "gu", word)
    return re.sub(r"(?<=[aeiouáéíóúâêô])s(?=[aeiouáéíóúâêô])", "ss", word)


def respell(text: str) -> str:
    """The sentence with its English words written the Portuguese way; Portuguese words unchanged."""
    words = _english_words(text)
    unknown = [m.group() for m in words if m.group().lower() not in _BRAZILIAN]
    try:
        spelled = dict(zip(unknown, map(_spell, _phonemize()(unknown)))) if unknown else {}
    except Exception:            # no eSpeak: say it as it is rather than not at all
        spelled = {}
    out, last = [], 0
    for m in words:
        word = m.group()
        out += [text[last:m.start()], _BRAZILIAN.get(word.lower()) or spelled.get(word) or word]
        last = m.end()
    return "".join(out + [text[last:]])
