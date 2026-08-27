import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render, get_object_or_404

from .decorators import only_tuesday_evening, vote_open_only
from .models import GameConfig, Player, Vote
from .utils import are_teams_available

ERROR_TRANSLATIONS = {
    "A user with that username already exists.": "Já existe um usuário com esse nome.",
    "This password is too short. It must contain at least 8 characters.": "A senha é muito curta. Deve ter pelo menos 8 caracteres.",
    "The two password fields didn’t match.": "As senhas não coincidem.",
    "This field is required.": "Este campo é obrigatório.",
}


def get_main_players_limit():
    return GameConfig.load().main_players_limit


def reorder_waiting_list():
    waiting_list = Player.objects.filter(is_main=False).order_by('queue_position', 'id')
    for i, player in enumerate(waiting_list, start=1):
        player.queue_position = i
        player.save()


def rebalance_players():
    limit = get_main_players_limit()
    main_players = Player.objects.filter(is_main=True).order_by('id')
    main_count = main_players.count()

    if main_count > limit:
        players_to_wait = main_players[limit:]
        last_position = Player.objects.filter(is_main=False).count()

        for player in players_to_wait:
            last_position += 1
            player.is_main = False
            player.queue_position = last_position
            player.save()

    elif main_count < limit:
        available_slots = limit - main_count
        waiting_players = Player.objects.filter(is_main=False).order_by('queue_position', 'id')[:available_slots]

        for player in waiting_players:
            player.is_main = True
            player.queue_position = None
            player.save()

    reorder_waiting_list()


def home(request):
    rebalance_players()

    config = GameConfig.load()
    main_players_limit = config.main_players_limit
    racha_total = config.racha_value

    main_players = Player.objects.filter(is_main=True).order_by('id')
    waiting_players = Player.objects.filter(is_main=False).order_by('queue_position')
    is_main_player = main_players.filter(name=request.user.username).exists() if request.user.is_authenticated else False
    show_scores = are_teams_available()
    show_leave = False
    value_racha = racha_total
    hide_racha_value = config.hide_racha_value

    if request.user.is_authenticated:
        show_leave = Player.objects.filter(name=request.user.username).exists()

    qtd_main = main_players.count()

    if qtd_main > 0:
        value_racha = (racha_total / Decimal(qtd_main)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return render(request, 'players/home.html', {
        'main_players': main_players,
        'waiting_players': waiting_players,
        'is_main_player': is_main_player,
        'show_scores': show_scores,
        'show_leave': show_leave,
        'qtd_main': qtd_main,
        'value_racha': value_racha,
        'racha_total': racha_total,
        'racha_total_input': str(racha_total),
        'main_players_limit': main_players_limit,
        'hide_racha_value': hide_racha_value,
    })


@login_required
def join_game(request):
    if Player.objects.filter(name=request.user.username).exists():
        return redirect('home')

    main_players_limit = get_main_players_limit()
    main_count = Player.objects.filter(is_main=True).count()

    if main_count < main_players_limit:
        Player.objects.create(name=request.user.username, is_main=True)
    else:
        last_position = Player.objects.filter(is_main=False).count()
        Player.objects.create(name=request.user.username, is_main=False, queue_position=last_position + 1)

    return redirect('home')


@login_required
def leave_game(request):
    player = get_object_or_404(Player, name=request.user.username)

    Vote.objects.filter(player_id=player.id).delete()
    Vote.objects.filter(voter=request.user).delete()

    player.delete()
    rebalance_players()

    return redirect('home')


@login_required
@vote_open_only
def vote(request):
    is_main_player = Player.objects.filter(name=request.user.username, is_main=True).exists()
    players = Player.objects.filter(is_main=True).exclude(name=request.user.username)
    player_ids = set(players.values_list('id', flat=True))

    if request.method == 'POST':
        for key, value in request.POST.items():
            if key.startswith('score_') and value.isdigit():
                try:
                    player_id = int(key.split('_')[1])
                except ValueError:
                    continue

                if player_id not in player_ids:
                    continue

                score_int = int(value)

                if 1 <= score_int <= 10:
                    player = Player.objects.get(id=player_id)
                    Vote.objects.update_or_create(player=player, voter=request.user, defaults={'score': score_int})

        return redirect('teams')

    existing_votes = Vote.objects.filter(voter=request.user)
    votes_dict = {vote.player.id: vote.score for vote in existing_votes}

    return render(request, 'players/vote.html', {
        'players': players,
        'votes_dict': votes_dict,
        'is_main_player': is_main_player,
    })


@only_tuesday_evening
def teams(request):
    players = list(Player.objects.filter(is_main=True))
    players = sorted(players, key=lambda p: p.average_score(), reverse=True)
    max_team_size = GameConfig.load().players_per_team
    num_teams = (len(players) + max_team_size - 1) // max_team_size
    teams = [[] for _ in range(num_teams)]
    team_scores = [0] * num_teams

    for player in players:
        best_index = min(
            (i for i in range(num_teams) if len(teams[i]) < max_team_size),
            key=lambda i: (len(teams[i]), team_scores[i])
        )
        teams[best_index].append(player)
        team_scores[best_index] += player.average_score()

    return render(request, 'players/teams.html', {'teams': teams})


def signup(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)

        if form.is_valid():
            form.save()
            return redirect('login')

        for field, errors in form.errors.items():
            field_name = {
                'username': 'Nome de usuário',
                'password1': 'Senha',
                'password2': 'Confirmação de senha',
            }.get(field, field)

            for error in errors:
                translated_error = ERROR_TRANSLATIONS.get(error, error)
                messages.error(request, f"{field_name}: {translated_error}")
    else:
        form = UserCreationForm()

    return render(request, 'players/signup.html', {'form': form})


@user_passes_test(lambda u: u.is_superuser)
def admin_add_player(request):
    existing_players = Player.objects.values_list('name', flat=True)
    users_to_add = User.objects.exclude(username__in=existing_players)

    if request.method == 'POST':
        username = request.POST.get('username')

        if username:
            main_players_limit = get_main_players_limit()
            main_count = Player.objects.filter(is_main=True).count()

            if main_count < main_players_limit:
                Player.objects.create(name=username, is_main=True)
                messages.success(request, f'Usuário {username} adicionado como player principal!')
            else:
                last_position = Player.objects.filter(is_main=False).count()
                Player.objects.create(name=username, is_main=False, queue_position=last_position + 1)
                messages.success(request, f'Usuário {username} adicionado na fila de espera!')

            return redirect('home')

    return render(request, 'players/admin_add_player.html', {'users_to_add': users_to_add})


@user_passes_test(lambda u: u.is_superuser)
def admin_remove_player(request, player_id):
    player = get_object_or_404(Player, id=player_id)

    Vote.objects.filter(player=player).delete()
    Vote.objects.filter(voter__username=player.name).delete()

    player.delete()
    rebalance_players()

    return redirect('home')


@user_passes_test(lambda u: u.is_superuser)
def admin_update_settings(request):
    if request.method == 'POST':
        config = GameConfig.load()

        try:
            players_per_team = int(request.POST.get('players_per_team', ''))
        except (TypeError, ValueError):
            messages.error(request, 'Quantidade de jogadores por time inválida.')
            return redirect('/')

        try:
            main_players_limit = int(request.POST.get('main_players_limit', ''))
        except (TypeError, ValueError):
            messages.error(request, 'Quantidade máxima da lista principal inválida.')
            return redirect('/')

        racha_value_raw = request.POST.get('racha_value', '').replace(',', '.')

        try:
            parsed_racha_value = Decimal(racha_value_raw).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            messages.error(request, 'Valor do racha inválido.')
            return redirect('/')

        hide_racha_value = request.POST.get('hide_racha_value') == 'on'

        vote_day = request.POST.get('vote_day')
        vote_start_time = request.POST.get('vote_start_time')
        vote_end_time = request.POST.get('vote_end_time')

        try:
            parsed_start_time = datetime.datetime.strptime(vote_start_time, '%H:%M').time()
            parsed_end_time = datetime.datetime.strptime(vote_end_time, '%H:%M').time()
        except (TypeError, ValueError):
            messages.error(request, 'Horário de início/encerramento da votação inválido.')
            return redirect('/')

        config.players_per_team = players_per_team
        config.main_players_limit = main_players_limit
        config.racha_value = parsed_racha_value
        config.hide_racha_value = hide_racha_value
        config.vote_day = vote_day
        config.vote_start_time = parsed_start_time
        config.vote_end_time = parsed_end_time

        try:
            config.save()
        except ValidationError as exc:
            for field_errors in exc.message_dict.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect('/')

        rebalance_players()
        messages.success(request, 'Configurações atualizadas com sucesso.')

    return redirect('/')

@user_passes_test(lambda u: u.is_superuser)
def admin_clear_players(request):
    if request.method == 'POST':
        Vote.objects.all().delete()
        Player.objects.all().delete()
        messages.success(request, 'Todos os jogadores foram removidos das listas.')

    return redirect('/')