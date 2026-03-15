# chatbot/chat/json_utils.py

import json


def fix_latex_json(raw: str) -> str:
    """
    Corrige les backslashes LaTeX non échappés dans une réponse JSON de Gemini.
    Gemini génère : {"statement": "Le vecteur \\vec{i}"}
    JSON attend   : {"statement": "Le vecteur \\\\vec{i}"}
    """
    result = []
    i = 0
    in_string = False
    VALID_JSON_ESCAPES = {'"', '\\', '/', 'b', 'f', 'n', 'r', 't', 'u'}

    while i < len(raw):
        c = raw[i]
        if not in_string:
            if c == '"':
                in_string = True
            result.append(c)
            i += 1
        else:
            if c == '\\':
                next_c = raw[i + 1] if i + 1 < len(raw) else ''
                if next_c in VALID_JSON_ESCAPES:
                    result.append(c)
                    result.append(next_c)
                    i += 2
                else:
                    result.append('\\\\')
                    i += 1
            elif c == '"':
                in_string = False
                result.append(c)
                i += 1
            else:
                result.append(c)
                i += 1

    return ''.join(result)


def safe_json_loads(response_text: str) -> dict:
    """
    Parse le JSON de Gemini avec deux stratégies :
    1. Parsing direct
    2. Fix des backslashes LaTeX puis re-parsing
    Lève JSONDecodeError si les deux échouent.
    """
    text = response_text.strip()

    # Nettoyer les fences markdown
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # Tentative 1 : parsing direct
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Tentative 2 : fix backslashes LaTeX
    return json.loads(fix_latex_json(text))