# Standard Library Imports
import uuid
from datetime import datetime
import logging
import traceback
# 3rd Party Imports
# Local Imports

from PokeAlarm.Utils import get_gmaps_link, get_move_damage, get_move_dps, \
    get_move_duration, get_move_energy, get_pokemon_gender, get_pokemon_size, \
    get_pokemon_size_full, get_pkmn_name, get_unown_name, get_applemaps_link

from pgoapi.protos.pogoprotos.enums.costume_pb2 import Costume
from pgoapi.protos.pogoprotos.enums.form_pb2 import Form
from pgoapi.protos.pogoprotos.enums.gender_pb2 import MALE, FEMALE, Gender, GENDERLESS, GENDER_UNSET
from pgoapi.protos.pogoprotos.enums.weather_condition_pb2 import *

from pgoapi.protos.pogoprotos.map.weather.gameplay_weather_pb2 import *
from pgoapi.protos.pogoprotos.map.weather.weather_alert_pb2 import *
from pgoapi.protos.pogoprotos.networking.responses.get_map_objects_response_pb2 import *

log = logging.getLogger('WebhookStructs')


# Todo: Move this into a better place
# Ensure that the value isn't None but replacing with a default
def check_for_none(type_, val, default):
    return type_(val) if val is not None else default


class RocketMap:
    def __init__(self):
        raise NotImplementedError(
            "This is a static class not meant to be initiated")

    @staticmethod
    def make_object(data):
        try:
            kind = data.get('type')
            if kind == 'pokemon':
                return RocketMap.pokemon(data.get('message'))
            elif kind == 'pokestop':
                return RocketMap.pokestop(data.get('message'))
            #elif kind == 'gym':
            #    return RocketMap.gym(data.get('message'))
            elif kind == "gym_details":
                return RocketMap.gym_info(data.get('message'))
            elif kind == 'raid':
                return RocketMap.egg_or_raid(data.get('message'))
            elif kind in ['captcha', 'scheduler']:  # Unsupported
                log.debug("{} webhook received.".format(kind)
                          + " This format not supported at this time.")
            elif kind == 'location':
                return RocketMap.location(data.get('message'))
            elif kind == 'weather':
                return RocketMap.weather(data.get('message'))
            #else:
            #    log.error("Invalid type specified ({}). ".format(kind)
            #              + "Are you using the correct map type?")
        except Exception as e:
            log.error("Encountered error while processing webhook "
                      + "({}: {})".format(type(e).__name__, e))
            log.debug("Stack trace: \n {}".format(traceback.format_exc()))
        return None

    @staticmethod
    def pokemon(data):
        log.debug("Converting to pokemon: \n {}".format(data))
        # Get some stuff ahead of time (cause we are lazy)
        quick_id = check_for_none(int, data.get('move_1'), '?')
        charge_id = check_for_none(int, data.get('move_2'), '?')
        lat, lng = data['latitude'], data['longitude']
        # Generate all the non-manager specific DTS
        pkmn = {
            'type': "pokemon",
            'id': data['encounter_id'],
            'pkmn_id': int(data['pokemon_id']),
            'disappear_time': datetime.utcfromtimestamp(
                data['disappear_time']),
            'time_until_despawn': check_for_none(
                int, data.get('seconds_until_despawn'), '?'),
            'spawn_start': check_for_none(int, data.get('spawn_start'), '?'),
            'spawn_end': check_for_none(int, data.get('spawn_end'), '?'),
            'verified': check_for_none(bool, data.get('verified'), 'False'),
            'lat': float(data['latitude']),
            'lng': float(data['longitude']),
            'lat_5': "{:.5f}".format(float(data['latitude'])),
            'lng_5': "{:.5f}".format(float(data['longitude'])),
            'cp': check_for_none(int, data.get('cp'), '?'),
            'level': check_for_none(int, data.get('pokemon_level'), '?'),
            'iv': '?',
            'atk': check_for_none(int, data.get('individual_attack'), '?'),
            'def': check_for_none(int, data.get('individual_defense'), '?'),
            'sta': check_for_none(int, data.get('individual_stamina'), '?'),
            'quick_id': quick_id,
            'quick_damage': get_move_damage(quick_id),
            'quick_dps': get_move_dps(quick_id),
            'quick_duration': get_move_duration(quick_id),
            'quick_energy': get_move_energy(quick_id),
            'charge_id': charge_id,
            'charge_damage': get_move_damage(charge_id),
            'charge_dps': get_move_dps(charge_id),
            'charge_duration': get_move_duration(charge_id),
            'charge_energy': get_move_energy(charge_id),
            'height': check_for_none(float, data.get('height'), '?'),
            'weight': check_for_none(float, data.get('weight'), '?'),
            'gender': get_pokemon_gender(check_for_none(int, data.get('gender'), '?')),
            'gendername': check_for_none(int, data.get('gender'), '?'),
            'catch_prob_1': check_for_none(float, data.get('catch_prob_1'), '?'),
            'catch_prob_2': check_for_none(float, data.get('catch_prob_2'), '?'),
            'catch_prob_3': check_for_none(float, data.get('catch_prob_3'), '?'),
            'form_id': check_for_none(int, data.get('form'), 0),
            'costume_id': check_for_none(int, data.get('costume_id'), 0),
            'size': 'unknown',
            'size_full': '?',
            'tiny_rat': '',
            'big_karp': '',
            'gmaps': get_gmaps_link(lat, lng),
            'applemaps': get_applemaps_link(lat, lng),
            'rating_attack': data.get('rating_attack'),
            'rating_defense': data.get('rating_defense'),
            'previous_id': check_for_none(int, data.get('previous_id'), ''),
            'weather_id': check_for_none(int, data.get('weather_id'), ''),
            'time_id': check_for_none(int, data.get('time_id'), 0),
            'mention': ''
        }
        if pkmn['atk'] != '?' and pkmn['def'] != '?' and pkmn['sta'] != '?':
            pkmn['iv'] = float(((pkmn['atk'] + pkmn['def'] + pkmn['sta'])
                                * 100) / float(45))
        else:
            pkmn['atk'], pkmn['def'], pkmn['sta'] = '?', '?', '?'

        if pkmn['height'] != '?' or pkmn['weight'] != '?':
            pkmn['size'] = get_pokemon_size(pkmn['pkmn_id'], pkmn['height'], pkmn['weight'])
            pkmn['size_full'] = get_pokemon_size_full(pkmn['pkmn_id'], pkmn['height'], pkmn['weight'])
            pkmn['height'] = "{:.2f}".format(pkmn['height'])
            pkmn['weight'] = "{:.2f}".format(pkmn['weight'])

        if pkmn['pkmn_id'] == 19 and pkmn['size'] == 'T':
            pkmn['tiny_rat'] = 'Tiny'

        if pkmn['pkmn_id'] == 129 and pkmn['size'] == 'B':
            pkmn['big_karp'] = 'Big'

        #if pkmn['pkmn_id'] == 19 and pkmn['weight'] <= 2.41:
        #    pkmn['tiny_rat'] = 'Tiny'

        #if pkmn['pkmn_id'] == 129 and pkmn['weight'] >= 13.13:
        #    pkmn['big_karp'] = 'Big'

        rating_attack = pkmn['rating_attack']
        pkmn['rating_attack'] = rating_attack.upper() if rating_attack else '-'
        rating_defense = pkmn['rating_defense']
        pkmn['rating_defense'] = rating_defense.upper() if rating_defense else '-'

        if pkmn['catch_prob_1'] != '?':
            pkmn['catch_prob_1'] = "{:.1f}".format(pkmn['catch_prob_1'] * 100)
        if pkmn['catch_prob_2'] != '?':
            pkmn['catch_prob_2'] = "{:.1f}".format(pkmn['catch_prob_2'] * 100)
        if pkmn['catch_prob_3'] != '?':
            pkmn['catch_prob_3'] = "{:.1f}".format(pkmn['catch_prob_3'] * 100)

        # Todo: Remove this when monocle get's it's own standard
        if pkmn['form_id'] == 0:
            pkmn['form_id'] = '?'

        return pkmn

    @staticmethod
    def pokestop(data):
        log.debug("Converting to pokestop: \n {}".format(data))
        if data.get('lure_expiration') is None:
            log.debug("Un-lured pokestop... ignoring.")
            return None
        stop = {
            'type': "pokestop",
            'id': data['pokestop_id'],
            'expire_time': datetime.utcfromtimestamp(data['lure_expiration']),
            'lat': float(data['latitude']),
            'lng': float(data['longitude']),
            'lat_5': "{:.5f}".format(float(data['latitude'])),
            'lng_5': "{:.5f}".format(float(data['longitude'])),
            'name': check_for_none(str, data.get('name'), '?'),
            'description': check_for_none(str, data.get('description'), '?'),
            'url': check_for_none(str, data.get('url'), ''),
            'deployer': check_for_none(str, data.get('deployer'), '?')
        }
        stop['gmaps'] = get_gmaps_link(stop['lat'], stop['lng'])
        stop['applemaps'] = get_applemaps_link(stop['lat'], stop['lng'])
        return stop

    @staticmethod
    def gym(data):
        log.debug("Converting to gym: \n {}".format(data))
        gym = {
            'type': "gym",
            'id': data.get('gym_id', data.get('id')),
            "new_team_id": int(data.get('team_id',  data.get('team'))),
            "points": str(data.get('total_cp')),
            "guard_pkmn_id": check_for_none(int, data.get('guard_pokemon_id'), '?'),
            'slots_available': check_for_none(int, data.get('slots_available'), '?'),
            'lat': float(data['latitude']),
            'lng': float(data['longitude']),
            'lat_5': "{:.5f}".format(float(data['latitude'])),
            'lng_5': "{:.5f}".format(float(data['longitude'])),
            'name': check_for_none(str, data.get('name'), 'unknown').strip(),
            'description': check_for_none(
                str, data.get('description'), 'unknown').strip(),
            'url': check_for_none(str, data.get('url'), 'unknown'),
            'park': check_for_none(int, data.get('park'), 0)
        }
        gym['gmaps'] = get_gmaps_link(gym['lat'], gym['lng'])
        gym['applemaps'] = get_applemaps_link(gym['lat'], gym['lng'])
        return gym

    @staticmethod
    def gym_info(data):
        log.debug("Converting to gym-details: \n {}".format(data))
        defenders = ""
        for pokemon in data.get('pokemon'):
            pokemoniv = float(((pokemon['iv_attack'] + pokemon['iv_defense'] + pokemon['iv_stamina']) * 100) / float(45))
            if get_unown_name(pokemon['form']):
                unownform = '(**' + get_unown_name(pokemon['form']) + '**)'
            else:
                unownform = ''
            defenders += "[**{0}** Lv:**{1}**] [**{2}**{3}X{4}]\n[**{5}%** {6}/{7}/{8}] [CP: **{9}**/{10}]\n[({11})]\n".format(pokemon['trainer_name'], pokemon['trainer_level'], get_pkmn_name(pokemon['pokemon_id']), unownform, pokemon['num_upgrades'], "{:.0f}".format(pokemoniv), pokemon['iv_attack'], pokemon['iv_stamina'], pokemon['iv_defense'], pokemon['cp_decayed'], pokemon['cp'], datetime.fromtimestamp(pokemon['deployment_time']).strftime('%m/%d %I:%M%p'))
        gym_info = {
            'type': "gym",
            'id': data.get('gym_id',  data.get('id')),
            'new_team_id': int(data.get('team_id',  data.get('team'))),
            'points': str(data.get('total_cp')),
            'guard_pkmn_id': check_for_none(int, data.get('guard_pokemon_id'), '?'),
            'slots_available': check_for_none(int, data.get('slots_available'), '?'),
            'is_in_battle': check_for_none(int, data.get('is_in_battle'), 0),
            'defenders': defenders,
            'lat': float(data['latitude']),
            'lng': float(data['longitude']),
            'lat_5': "{:.5f}".format(float(data['latitude'])),
            'lng_5': "{:.5f}".format(float(data['longitude'])),
            'name': check_for_none(str, data.get('name'), '?').strip(),
            'description': check_for_none(str, data.get('description'), '?').strip(),
            'url': check_for_none(str, data.get('url'), ''),
            'park': check_for_none(int, data.get('park'), 0)
        }

        #log.warning(gym_info['guard_pkmn_id'])
        #log.warning("PARSED GYM INFORMATION: \n {}".format(gym_info))
        gym_info['gmaps'] = get_gmaps_link(gym_info['lat'], gym_info['lng'])
        gym_info['applemaps'] = get_applemaps_link(gym_info['lat'], gym_info['lng'])

        return gym_info

    @staticmethod
    def location(data):
        data['type'] = 'location'
        data['id'] = str(uuid.uuid4())
        return data

    # Find out if the raid data is an egg or a raid
    @staticmethod
    def egg_or_raid(data):
        log.debug("Checking for egg or raid")

        pkmn_id = check_for_none(int, data.get('pokemon_id'), 0)

        if pkmn_id == 0:
            return RocketMap.egg(data)

        return RocketMap.raid(data)

    @staticmethod
    def egg(data):
        log.debug("Converting to egg: \n {}".format(data))

        raid_end = None
        raid_begin = None

        if 'raid_begin' in data:
            raid_begin = datetime.utcfromtimestamp(data['raid_begin'])
        elif 'battle' in data:
            raid_begin = datetime.utcfromtimestamp(data['battle'])
        elif 'start' in data:
            raid_begin = datetime.utcfromtimestamp(data['start'])

        if 'raid_end' in data:  # monocle
            raid_end = datetime.utcfromtimestamp(data['raid_end'])
        elif 'end' in data:  # rocketmap
            raid_end = datetime.utcfromtimestamp(data['end'])

        if 'raid_seed' in data:  # monocle sends a unique raid seed
            id_ = data.get('raid_seed')
        else:
            id_ = data.get('gym_id')  # RM sends the gym id

        team_id = data.get('team_id', data.get('team'))
        if team_id is not None:
            team_id = int(team_id)

        egg = {
            'type': 'egg',
            'id': id_,
            'team_id': team_id,
            #'team_id': int(data.get('team_id',  data.get('team'))),
            'slots_available': check_for_none(int, data.get('slots_available'), '?'),
            'raid_level': check_for_none(int, data.get('level'), 0),
            'raid_end': raid_end,
            'raid_begin': raid_begin,
            'lat': float(data['latitude']),
            'lng': float(data['longitude']),
            'lat_5': "{:.5f}".format(float(data['latitude'])),
            'lng_5': "{:.5f}".format(float(data['longitude'])),
            'park': check_for_none(int, data.get('park'), 0)
        }

        egg['gmaps'] = get_gmaps_link(egg['lat'], egg['lng'])
        egg['applemaps'] = get_applemaps_link(egg['lat'], egg['lng'])

        return egg

    @staticmethod
    def raid(data):
        log.debug("Converting to raid: \n {}".format(data))

        quick_id = check_for_none(int, data.get('move_1'), '?')
        charge_id = check_for_none(int, data.get('move_2'), '?')

        raid_end = None
        raid_begin = None

        if 'raid_begin' in data:
            raid_begin = datetime.utcfromtimestamp(data['raid_begin'])
        elif 'battle' in data:
            raid_begin = datetime.utcfromtimestamp(data['battle'])
        elif 'start' in data:
            raid_begin = datetime.utcfromtimestamp(data['start'])

        if 'raid_end' in data:  # monocle
            raid_end = datetime.utcfromtimestamp(data['raid_end'])
        elif 'end' in data:  # rocketmap
            raid_end = datetime.utcfromtimestamp(data['end'])

        if 'raid_seed' in data:  # monocle sends a unique raid seed
            id_ = data.get('raid_seed')
        else:
            id_ = data.get('gym_id')  # RM sends the gym id

        team_id = data.get('team_id', data.get('team'))
        if team_id is not None:
            team_id = int(team_id)

        raid = {
            'type': 'raid',
            'id': id_,
            'team_id': team_id,
            #'team_id': int(data.get('team_id',  data.get('team'))),
            'slots_available': check_for_none(int, data.get('slots_available'), '?'),
            'pkmn_id': check_for_none(int, data.get('pokemon_id'), 0),
            'cp': check_for_none(int, data.get('cp'), '?'),
            'quick_id': quick_id,
            'quick_damage': get_move_damage(quick_id),
            'quick_dps': get_move_dps(quick_id),
            'quick_duration': get_move_duration(quick_id),
            'quick_energy': get_move_energy(quick_id),
            'charge_id': charge_id,
            'charge_damage': get_move_damage(charge_id),
            'charge_dps': get_move_dps(charge_id),
            'charge_duration': get_move_duration(charge_id),
            'charge_energy': get_move_energy(charge_id),
            'raid_level': check_for_none(int, data.get('level'), 0),
            'raid_end': raid_end,
            'raid_begin': raid_begin,
            'lat': float(data['latitude']),
            'lng': float(data['longitude']),
            'lat_5': "{:.5f}".format(float(data['latitude'])),
            'lng_5': "{:.5f}".format(float(data['longitude'])),
            'park': check_for_none(int, data.get('park'), 0)
        }

        raid['gmaps'] = get_gmaps_link(raid['lat'], raid['lng'])
        raid['applemaps'] = get_applemaps_link(raid['lat'], raid['lng'])

        return raid

    @staticmethod
    def weather(data):
        log.debug("Converting to weather: \n {}".format(data))
        weather = {
            'type': "weather",
            'id': data['s2_cell_id'],
            'lat': float(data['latitude']),
            'lng': float(data['longitude']),
            'lat_5': "{:.5f}".format(float(data['latitude'])),
            'lng_5': "{:.5f}".format(float(data['longitude'])),
            'cloud_level': check_for_none(int, data.get('cloud_level'), '?'),
            'rain_level': check_for_none(int, data.get('rain_level'), '?'),
            'wind_level': check_for_none(int, data.get('wind_level'), ''),
            'snow_level': check_for_none(int, data.get('snow_level'), '?'),
            'fog_level': check_for_none(int, data.get('fog_level'), '?'),
            'wind_direction': check_for_none(int, data.get('wind_direction'), '?'),
            'gameplay_weather': check_for_none(int, data.get('gameplay_weather'), '?'),
            'new_gameplay_weather': int(data.get('gameplay_weather', data.get('gameplayweather'))),
            'severity': check_for_none(int, data.get('severity'), '?'),
            'new_severity_weather': int(data.get('severity', data.get('severityweather'))),
            'warn_weather': check_for_none(int, data.get('warn_weather'), '?'),
            'world_time': check_for_none(int, data.get('world_time'), '?')
        }

        weather['gmaps'] = get_gmaps_link(weather['lat'], weather['lng'])
        weather['applemaps'] = get_applemaps_link(weather['lat'], weather['lng'])

        return weather

    @staticmethod
    def location(data):
        data['type'] = 'location'
        data['id'] = str(uuid.uuid4())
        return data
