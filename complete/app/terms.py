"""Short answers grounded in published EKT purchase information.

The source is public and can change; review before a production release.
"""
import re
import json
from functools import lru_cache
from pathlib import Path

SOURCE_URL = "https://ekt.kz/include/ses.php"


@lru_cache(maxsize=1)
def demo_terms():
    return json.loads((Path(__file__).resolve().parent.parent / "data" / "purchase_terms.demo.json").read_text(encoding="utf-8"))


def answer_purchase_terms(question: str, mode: str = "normalized") -> dict | None:
    text = question.casefold()
    topics = []
    if re.search(r"минимальн|минимум|мин\.?(?:имум)?\s*(?:парт|заказ)|мелк(?:ая|им)\s*опт", text):
        topics.append("minimum_order")
    if re.search(r"оплат|платеж|рассрочк", text):
        topics.append("payment")
    if re.search(r"достав|самовывоз|привез", text):
        topics.append("delivery")
    if not topics and re.search(r"услови[яй]\s+(?:покупки|заказа|продажи)|как\s+купить", text):
        topics = ["payment", "delivery", "minimum_order"]
    if not topics:
        return None
    if mode == "demo":
        source = demo_terms()
        return {"topic": topics[0] if len(topics) == 1 else "purchase_terms", "topics": topics,
                "answer": source["notice"] + "\n" + "\n".join(source[topic]["answer"] for topic in topics),
                "source_url": source["source_url"], "is_demo": True, "data_mode": "demo"}
    answers = {
        "minimum_order": "Единая минимальная партия в опубликованных условиях не указана. Она может зависеть от товара; назовите артикул и город, чтобы уточнить условие у менеджера.",
        "payment": "По опубликованным условиям EKT физлица могут оплатить картой онлайн, наличными при получении или при самовывозе. Для юрлиц указан счёт с переводом на расчётный счёт; условия для конкретного заказа стоит уточнить при оформлении.",
        "delivery": "По опубликованным условиям EKT доставка зависит от города и заказа. Для Алматы указаны отдельные условия; стоимость и сроки для других городов согласуются с менеджером по адресу, весу и объёму. Назовите город, чтобы уточнить детали.",
    }
    return {"topic": topics[0] if len(topics) == 1 else "purchase_terms", "topics": topics,
            "answer": "\n".join(answers[topic] for topic in topics), "source_url": SOURCE_URL,
            "is_demo": False, "data_mode": "published_terms"}
