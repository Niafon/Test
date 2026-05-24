from functools import lru_cache

from sqlalchemy import Engine, create_engine

# Сзодания подкючения к бд
@lru_cache(maxsize=16)
def create_db_engine(db_url: str) -> Engine:
    # Кешируем по URL: каждый /generate и /apply раньше плодил новый Engine
    # (со своим пулом) на каждый запрос, без disposal. На длительной работе API
    # это утекает соединения. Один Engine на URL переиспользует пул и закрывает
    # idle-коннекшены сам. maxsize=16 - страховка от бесконечного роста, если
    # URL генерируются динамически.
    return create_engine(db_url)
