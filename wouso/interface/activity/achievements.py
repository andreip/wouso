import logging
from datetime import datetime, timedelta
from django.utils.translation import ugettext_noop
from wouso.core.app import App
from wouso.interface.apps.messaging.models import Message
from wouso.games.challenge.models import Challenge
from wouso.interface.apps.messaging.models import Message
from wouso.games.challenge.models import Challenge

from models import Activity
from signals import addActivity,messageSignal

def consecutive_seens(player, timestamp):
    """
     Return the count of consecutive seens for a player, until timestamp
    """
    activities = Activity.get_private_activity(player).filter(action='seen').order_by('-timestamp')[0:100]
    today = timestamp.date()
    for i, activity in enumerate(activities):
        date = activity.timestamp.date()
        if date != today + timedelta(days=-i):
            return i

    return len(activities)


def consecutive_qotd_correct(player):
    """
     Return the count of correct qotd in a row
     Maximum: 10 (last ten)
    """
    activities = Activity.get_player_activity(player).filter(action__contains = 'qotd').order_by('-timestamp')[:10]
    result = 0
    for i in activities:
        if 'correct' in i.action:
            result += 1
        else:
            return result
    return result


def login_between(time, first, second):
    if first <= time.hour < second:
        return True
    return False


def unique_users_pm(player, minutes):
    """
     Return the count of distinct source messages
    """
    activities = Message.objects.filter(receiver=player,
                                        timestamp__gt=datetime.now() - timedelta(minutes=minutes)
                                        ).values('sender').distinct().count()
    return activities


def wrong_first_qotd(player):
    """
     Check if the first answer to qotd was a wrong answer.
    """
    activities = Activity.get_player_activity(player).filter(action__contains='qotd')
    if not activities.count() == 1:
        return False
    if activities[0].action == 'qotd-wrong':
        return True
    return False
    
    
def challenge_count(player):
    """
     Return the count of challenges played by player.
    """
    return Activity.get_player_activity(player).filter(action__contains='chall').count()


def consecutive_chall_won(player):
    """
     Return the count of won challenges in a row
     Maximum: 10 (last ten)
    """
    activities = Activity.get_player_activity(player).filter(action__contains='chall').order_by('-timestamp')[:10]
    result = 0
    for i in activities:
        if 'won' in i.action and i.user_from.id == player.id:
            result += 1
        else:
            return result

    return result
    
def check_for_god_mode(player, days, chall_min):
    """
    Return true if the player won all challenges and answerd all qotd 'days' days in a row witn a minimum of 'chall_min' challenges
    """
    qotd_list = Activity.objects.all().filter(user_from=player, action__contains="qotd").order_by('-timestamp')
    if len(qotd_list) == 0:
        return False
    if qotd_list[0].action == 'qotd-wrong':
        return False#Last qotd was incorrect no point to check any further
    
    last_time = qotd_list[0].timestamp.replace(hour=0,minute=0,second=0,microsecond=0) + timedelta(days=1) #The day when the latest qotd was ok
    first_time = last_time - timedelta(days=days)#The earlyest day to check
    
    chall_won = Activity.objects.all().filter(user_from=player, action='chall-won', timestamp__gte=first_time).exclude(timestamp__gte=last_time).count()
    chall_lost = Activity.objects.all().filter(user_to=player, action='chall-won', timestamp__gte=first_time).exclude(timestamp__gte=last_time).count()
    qotd_ok = Activity.objects.all().filter(user_from=player, action='qotd-correct', timestamp__gte=first_time).exclude(timestamp__gte=last_time).count()
    
    if chall_won >= chall_min and chall_lost == 0 and qotd_ok == days:
        return True
    return False
    

def refused_challenges(player):
    """
     Return the count of refused challenges in the last week
    """
    start = datetime.now() + timedelta(days=-7)
    return Activity.get_player_activity(player).filter(action__contains='chall-refused', timestamp__gte=start, user_from=player).count()


def get_chall_score(arguments):
    if not arguments:
        return 0
    if "id" in arguments:
        chall = Challenge.objects.get(pk=arguments["id"])
        return max(chall.user_from.score, chall.user_to.score)
    else:
        return 0
        
def get_challenge_time(arguments):
    """
     Return the number of seconds spent by the winner.
    """
    if not arguments:
        return 0

    if "id" in arguments:
        chall = Challenge.objects.get(pk=arguments["id"])
        return chall.user_from.seconds_took
    else:
        return 0


class Achievements(App):
    @classmethod
    def earn_achievement(cls, player, modifier):
        result = player.magic.give_modifier(modifier)
        if result is not None:
            message = ugettext_noop('earned {artifact}')
            addActivity.send(sender=None, user_from=player, game=None, message=message,
                arguments=dict(artifact=result.artifact)
            )
            Message.send(sender=None, receiver=player, subject="Achievement", text="You have just earned "+modifier)
        else:
            logging.debug('%s would have earned %s, but there was no artifact' % (player, modifier))

    @classmethod
    def activity_handler(cls, sender, **kwargs):
        action = kwargs.get('action', None)
        player = kwargs.get('user_from', None)
        if not action:
            return

        if 'qotd' in action:
            # Check 10 qotd in a row
            if consecutive_qotd_correct(player) >= 10:
                if not player.magic.has_modifier('ach-qotd-10'):
                    cls.earn_achievement(player, 'ach-qotd-10')

            # Check for wrong answer to the first qotd
            if not player.magic.has_modifier('ach-bad-start') and action == "qotd-wrong":
                if wrong_first_qotd(player):
                    cls.earn_achievement(player, 'ach-bad-start')


        if 'chall' in action:
            # Check if number of challenge games is 30*k
            games_played = challenge_count(player)
            if games_played > 0 and (games_played % 30) == 0:
                if not player.magic.has_modifier('ach-chall-30'):
                    cls.earn_achievement(player, 'ach-chall-30')

            # Check if the number of refused challenges in the past week is
            # less than 2
            if not player.magic.has_modifier('ach-this-is-sparta'):
                if refused_challenges(player) <= 2:
                    cls.earn_achievement(player, 'ach-this-is-sparta')

        if action == 'chall-won':
            # Check for flawless victory
            if get_chall_score(kwargs.get("arguments")) == 500:
                if not player.magic.has_modifier('ach-flawless-victory'):
                    cls.earn_achievement(player, 'ach-flawless-victory')
            # Check 10 won challenge games in a row
            if not player.magic.has_modifier('ach-chall-won-10'):
                if consecutive_chall_won(player) >= 10:
                    cls.earn_achievement(player, 'ach-chall-won-10')

            # Check if player defeated 2 levels or more bigger opponent
            if not player.magic.has_modifier('ach-chall-def-big'):
                if (kwargs.get('user_to').level_no - player.level_no) >= 2:
                    cls.earn_achievement(player, 'ach-chall-def-big')

            # Check if the player finished the challenge in less than 1 minute
            if not player.magic.has_modifier('ach-win-fast'):
                seconds_no = get_challenge_time(kwargs.get("arguments"))
                if seconds_no > 0 and seconds_no <= 60:
                    cls.earn_achievement(player, 'ach-win-fast')

        if action == "message":
            # Check the number of unique users who send pm to player in the last m minutes
            if unique_users_pm(kwargs.get('user_to'), 30) >= 3:
                if not kwargs.get('user_to').magic.has_modifier('ach-popularity'):
                    cls.earn_achievement(kwargs.get('user_to'), 'ach-popularity')

        if action in ("login", "seen"):
            # Check login between 2-4 am
            if login_between(kwargs.get('timestamp',datetime.now()), 2, 4):
                if not player.magic.has_modifier('ach-night-owl'):
                    cls.earn_achievement(player, 'ach-night-owl')
            elif login_between(kwargs.get('timestamp',datetime.now()), 6, 8):
                if not player.magic.has_modifier('ach-early-bird'):
                    cls.earn_achievement(player, 'ach-early-bird')
            
            if not player.magic.has_modifier('ach-god-mode-on'):
                if check_for_god_mode(player, 5, 5):
                    cls.earn_achievement(player, 'ach-god-mode-on')
            # Check previous 10 seens
            if consecutive_seens(player, datetime.now()) >= 10:
                if not player.magic.has_modifier('ach-login-10'):
                    cls.earn_achievement(player, 'ach-login-10')

    @classmethod
    def get_modifiers(self):
        return ['ach-login-10',
                'ach-qotd-10',
                'ach-chall-30',
                'ach-chall-won-10',
                'ach-night-owl',
                'ach-early-bird',
                'ach-popularity',
                'ach-bad-start',
                'ach-chall-def-big',
                'ach-this-is-sparta',
                'ach-flawless-victory',
                'ach-win-fast',
                'ach-god-mode-on'
        ]


def check_for_achievements(sender, **kwargs):
    Achievements.activity_handler(sender, **kwargs)

addActivity.connect(check_for_achievements)
messageSignal.connect(check_for_achievements)
