import datetime

import pytz

from .models import GameConfig

TIMEZONE = pytz.timezone("America/Sao_Paulo")


def now_local():
    return datetime.datetime.now(TIMEZONE)


def is_voting_open(config=None):
    """
    A votação fica aberta somente durante a janela configurada
    (dia da semana + horário de início/fim) em GameConfig.
    """
    config = config or GameConfig.load()
    now = now_local()

    if now.weekday() != config.vote_weekday_index():
        return False

    return config.vote_start_time <= now.time() < config.vote_end_time


def are_teams_available(config=None):
    """
    Os times ficam indisponíveis enquanto a votação estiver aberta e são
    liberados automaticamente assim que a janela de votação se encerra.
    """
    return not is_voting_open(config)
