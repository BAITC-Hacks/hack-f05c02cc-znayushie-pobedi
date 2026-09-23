"""Deterministic conversational references. Text can select products, never confirm a cart."""
import re

ADD = re.compile(r"\b(?:добавь|добавить|положи|положить)\b", re.I)
NEGATED = re.compile(r"\b(?:не|нельзя|без)\b|отмен", re.I)
QUANTITY = re.compile(r"(?<![\w.,])(-?\d+(?:[.,]\d+)?)\s*(?:шт(?:\.|ук[аи]?)?|метр(?:ов|а)?|м|единиц(?:ы|у)?)\b", re.I)
ORDINALS = {"перв":0, "втор":1, "трет":2, "четверт":3, "пят":4}


def purchase_intent(message):
    if not ADD.search(message) or NEGATED.search(message):
        return False, 1, message
    matches = list(QUANTITY.finditer(message))
    if not matches:
        return True, 1, message
    if len(matches) > 1:
        raise ValueError("Укажите одно количество для одного товара.")
    value = matches[0][1].replace(",", ".")
    if "." in value or not 1 <= int(value) <= 1000:
        raise ValueError("Количество должно быть целым числом от 1 до 1000.")
    return True, int(value), message[:matches[0].start()] + " " + message[matches[0].end():]


def normalize_query(message):
    """Remove polite wrappers, retain negatives, ranges and unknown constraints."""
    text = message.casefold().replace("ё", "е").strip()
    text = re.sub(r"\bсколько\s+(?:он|она|оно)\s+стоит\b", "его", text)
    text = re.sub(r"\b(?:какие|какая|какой)\s+у\s+(него|нее)\b", r"\1", text)
    # These are exact numeric attributes, not inferred electrical suitability.
    for word, token in [("трехфазн", "3ф"), ("однофазн", "1ф"),
                        ("однополюсн", "1p"), ("двухполюсн", "2p"), ("трехполюсн", "3p")]:
        text = re.sub(r"\b" + word + r"\w*\b", token, text)
    text = re.sub(r"\bавтоматическ\w*\s+выключател\w*\b", "автомат", text)
    # Leave unsupported negatives/or/ranges untouched so catalog validation rejects them.
    text = re.sub(r"\b(?:подскажи(?:те)?|скажите|расскажи(?:те)?|покажите|подбери(?:те)?|пожалуйста|здравствуйте|нужен|нужна|нужны|нужно|мне|ищу|хочу|купить)\b", " ", text)
    text = re.sub(r"\b(?:номинальн\w*\s+ток\w*|ток(?:ом|а)?)\b", " ", text)
    text = re.sub(r"\b(?:сколько\s+стоит|есть\s+ли\s+в\s+наличии|в\s+наличии|есть\s+ли|какая\s+цена)\b", " ", text)
    text = re.sub(r"\b(?:характеристики|сертификат(?:ы|а)?|стоимость|цена|наличие|подробнее|добавь|добавить|положи|положить|аналоги?|замена|замену|похожие|похожий|покажи|найди|найдите|про|товар(?:а)?)\b", " ", text)
    text = re.sub(r"\b(?:на|с|у|вас)\b", " ", text)
    return " ".join(text.strip(" \t\r\n?!,.").split())


def context_product(message, session, catalog):
    """Only a complete reference can reuse history; unknown explicit IDs never do."""
    text = normalize_query(message)
    text = re.sub(r"^(?:а\s+)?", "", text).strip()
    words = r"(?:перв(?:ый|ого|ому)|втор(?:ой|ого|ому)|трет(?:ий|ьего|ьему)|четверт(?:ый|ого)|пят(?:ый|ого))"
    ordinal = re.fullmatch(r"(?:(?:для|о|об)\s+)?(" + words + r")(?:\s+(?:вариант(?:а|е)?|товар(?:а|е)?|аналог(?:а|е)?))?", text)
    if ordinal:
        position = next(index for prefix, index in ORDINALS.items() if ordinal[1].startswith(prefix))
        ids = session.last_analog_ids if "аналог" in message.casefold() else session.last_product_ids
        return catalog.get(ids[position]) if len(ids) > position else None
    simple = re.fullmatch(r"(?:(?:для|у)\s+)?(?:него|нее|его|ее|этот|этого|этой|этот товар|этого товара)?", text)
    # Keep the original short follow-up semantics, explicit identifiers never match here.
    if simple and session.last_product_ids:
        return catalog.get(session.last_product_ids[0])
    return None


def search_in_conversation(message, session, catalog):
    query = normalize_query(message)
    context = context_product(message, session, catalog)
    if context is not None:
        return [context]
    if not query:
        return []
    # A conversation may phrase a known identifier with polite prefixes.
    return catalog.search(query)


def products_from_attachment(text, catalog, limit=20):
    """Treat attachment content solely as catalog data, never as a chat command."""
    found = {}
    lowered = text.casefold()
    for product in catalog.products.values():
        ids = {str(product.get(key) or "").strip().rstrip("_") for key in
               ("id", "sku", "article", "supplier_article", "name_reference")}
        ids.discard("")
        if any(re.search(r"(?<![\w-])" + re.escape(value.casefold()) + r"_?(?![\w-])", lowered) for value in ids):
            found[product["id"]] = catalog.get(product["id"])
    # A list can mix exact articles with descriptions on other lines.
    for line in text.splitlines()[:80]:
        line = line.strip()
        if not line or len(line) > 2000:
            continue
        # Skip pure headings/numbers and command-like lines, even if OCR contains them.
        if len(line) < 3 or re.search(r"игнорир|инструкц|добавь|положи|подтверд|отправь|password|api.key", line, re.I):
            continue
        try:
            matches = catalog.search(normalize_query(line), limit=5)
        except ValueError:
            continue
        for product in matches:
            found[product["id"]] = product
    return list(found.values())[:limit]
