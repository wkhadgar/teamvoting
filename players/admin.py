from django.contrib import admin

from .models import GameConfig, Player, Vote

admin.site.register(Player)
admin.site.register(Vote)
admin.site.register(GameConfig)
