from .models import GameConfig


def game_config(request):
    return {'game_config': GameConfig.load()}
