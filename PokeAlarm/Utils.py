# Standard Library Imports
from datetime import datetime, timedelta
from glob import glob
import json
import logging
from math import radians, sin, cos, atan2, sqrt, degrees
import os
import sys
# 3rd Party Imports
# Local Imports
from . import config

log = logging.getLogger('Utils')


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ SYSTEM UTILITIES ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

# Checks is a line contains any substitutions located in args
def contains_arg(line, args):
    for word in args:
        if ('<' + word + '>') in line:
            return True
    return False


def get_path(path):
    if not os.path.isabs(path):  # If not absolute path
        path = os.path.join(config['ROOT_PATH'], path)
    return path


def parse_boolean(val):
    b = str(val).lower()
    if b in {'t', 'true', 'y', 'yes'}:
        return True
    if b in ('f', 'false', 'n', 'no'):
        return False
    return None


def parse_unicode(bytestring):
    decoded_string = bytestring.decode(sys.getfilesystemencoding())
    return decoded_string


# Used for lazy installs - installs required module with pip
def pip_install(req, version):
    import subprocess
    target = "{}=={}".format(req, version)
    log.info("Attempting to pip install %s..." % target)
    subprocess.call(['pip', 'install', target])
    log.info("%s install complete." % target)


# Used to exit when leftover parameters are founds
def reject_leftover_parameters(dict_, location):
    if len(dict_) > 0:
        log.error("Unknown parameters at {}: ".format(location))
        log.error(dict_.keys())
        log.error("Please consult the PokeAlarm wiki for accepted parameters.")
        raise


# Load a key from the given dict, or throw an error if it isn't there
def require_and_remove_key(key, _dict, location):
    if key in _dict:
        return _dict.pop(key)
    else:
        log.error("The parameter '{}' is required for {}".format(key, location)
                  + " Please check the PokeAlarm wiki for correct formatting.")
        raise


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ POKEMON UTILITIES ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

# Returns the name corresponding with the pokemon id (uses EN locale)
def get_pkmn_name(pokemon_id):
    match = int(pokemon_id)
    files = glob(get_path('locales/en.json'))    # Change To Locale
    for file_ in files:
        with open(file_, 'r') as f:
            j = json.loads(f.read())
            j = j['pokemon']
            for pb in j:
                # log.warning('ID %s AND pokemon_id %s', pb, pokemon_id)
                if int(pb) == match:
                    # log.warning('ID MATCHED WITH GIVEN: NAME IS %s', j[pb])
                    return j[pb]
                    break


# Returns the unown letter corresponding with the unown id (uses EN locale)
def get_unown_name(form_id):
    match = int(form_id)
    files = glob(get_path('locales/en.json'))    # Change To Locale
    for file_ in files:
        with open(file_, 'r') as f:
            j = json.loads(f.read())
            j = j['forms']
            for pb in j:
                # log.warning('ID %s AND pokemon_id %s', pb, pokemon_id)
                if int(pb) == match:
                    # log.warning('ID MATCHED WITH GIVEN: NAME IS %s', j[pb])
                    return j[pb]
                    break

# Returns the id corresponding with the pokemon name
# (use all locales for flexibility)
def get_pkmn_id(pokemon_name):
    name = pokemon_name.lower()
    if not hasattr(get_pkmn_id, 'ids'):
        get_pkmn_id.ids = {}
        files = glob(get_path('locales/*.json'))
        for file_ in files:
            with open(file_, 'r') as f:
                j = json.loads(f.read())
                j = j['pokemon']
                for id_ in j:
                    nm = j[id_].lower()
                    get_pkmn_id.ids[nm] = int(id_)
    return get_pkmn_id.ids.get(name)


# Returns the id corresponding with the move (use all locales for flexibility)
def get_move_id(move_name):
    name = move_name.lower()
    if not hasattr(get_move_id, 'ids'):
        get_move_id.ids = {}
        files = glob(get_path('locales/*.json'))
        for file_ in files:
            with open(file_, 'r') as f:
                j = json.loads(f.read())
                j = j['moves']
                for id_ in j:
                    nm = j[id_].lower()
                    get_move_id.ids[nm] = int(id_)
    return get_move_id.ids.get(name)


# Returns the id corresponding with the pokemon name
# (use all locales for flexibility)
def get_team_id(team_name):
    name = team_name.lower()
    if not hasattr(get_team_id, 'ids'):
        get_team_id.ids = {}
        files = glob(get_path('locales/*.json'))
        for file_ in files:
            with open(file_, 'r') as f:
                j = json.loads(f.read())
                j = j['teams']
                for id_ in j:
                    nm = j[id_].lower()
                    get_team_id.ids[nm] = int(id_)
    return get_team_id.ids.get(name)


# Returns the damage of a move when requesting
def get_move_damage(move_id):
    if not hasattr(get_move_damage, 'info'):
        get_move_damage.info = {}
        file_ = get_path('data/move_info.json')
        with open(file_, 'r') as f:
            j = json.loads(f.read())
        for id_ in j:
            get_move_damage.info[int(id_)] = j[id_]['damage']
    return get_move_damage.info.get(move_id, 'unkn')


# Returns the dps of a move when requesting
def get_move_dps(move_id):
    if not hasattr(get_move_dps, 'info'):
        get_move_dps.info = {}
        file_ = get_path('data/move_info.json')
        with open(file_, 'r') as f:
            j = json.loads(f.read())
        for id_ in j:
            get_move_dps.info[int(id_)] = j[id_]['dps']
    return get_move_dps.info.get(move_id, 'unkn')


# Returns the duration of a move when requesting
def get_move_duration(move_id):
    if not hasattr(get_move_duration, 'info'):
        get_move_duration.info = {}
        file_ = get_path('data/move_info.json')
        with open(file_, 'r') as f:
            j = json.loads(f.read())
        for id_ in j:
            get_move_duration.info[int(id_)] = j[id_]['duration']
    return get_move_duration.info.get(move_id, 'unkn')


# Returns the duration of a move when requesting
def get_move_energy(move_id):
    if not hasattr(get_move_energy, 'info'):
        get_move_energy.info = {}
        file_ = get_path('data/move_info.json')
        with open(file_, 'r') as f:
            j = json.loads(f.read())
        for id_ in j:
            get_move_energy.info[int(id_)] = j[id_]['energy']
    return get_move_energy.info.get(move_id, 'unkn')


# Returns the base height for a pokemon
def get_base_height(pokemon_id):
    if not hasattr(get_base_height, 'info'):
        get_base_height.info = {}
        file_ = get_path('data/base_stats.json')
        with open(file_, 'r') as f:
            j = json.loads(f.read())
        for id_ in j:
            get_base_height.info[int(id_)] = j[id_].get('height')
    return get_base_height.info.get(pokemon_id)


# Returns the base weight for a pokemon
def get_base_weight(pokemon_id):
    if not hasattr(get_base_weight, 'info'):
        get_base_weight.info = {}
        file_ = get_path('data/base_stats.json')
        with open(file_, 'r') as f:
            j = json.loads(f.read())
        for id_ in j:
            get_base_weight.info[int(id_)] = j[id_].get('weight')
    return get_base_weight.info.get(pokemon_id)


# Returns the base stats for a pokemon
def get_base_stats(pokemon_id):
    if not hasattr(get_base_stats, 'info'):
        get_base_stats.info = {}
        file_ = get_path('data/base_stats.json')
        with open(file_, 'r') as f:
            j = json.loads(f.read())
        for id_ in j:
            get_base_stats.info[int(id_)] = {
                "attack": float(j[id_].get('attack')),
                "defense": float(j[id_].get('defense')),
                "stamina": float(j[id_].get('stamina'))
            }

    return get_base_stats.info.get(pokemon_id)


# Returns a cp range for a certain level of a pokemon caught in a raid
def get_pokemon_cp_range(pokemon_id, level):
    stats = get_base_stats(pokemon_id)

    if not hasattr(get_pokemon_cp_range, 'info'):
        get_pokemon_cp_range.info = {}
        file_ = get_path('data/cp_multipliers.json')
        with open(file_, 'r') as f:
            j = json.loads(f.read())
        for lvl_ in j:
            get_pokemon_cp_range.info[lvl_] = j[lvl_]

    cp_multi = get_pokemon_cp_range.info["{}".format(level)]

    # minimum IV for a egg/raid pokemon is 10/10/10
    min_cp = int(
        ((stats['attack'] + 10.0) * pow((stats['defense'] + 10.0), 0.5)
         * pow((stats['stamina'] + 10.0), 0.5) * pow(cp_multi, 2)) / 10.0)
    max_cp = int(
        ((stats['attack'] + 15.0) * pow((stats['defense'] + 15.0), 0.5) *
         pow((stats['stamina'] + 15.0), 0.5) * pow(cp_multi, 2)) / 10.0)

    return min_cp, max_cp


# Returns the size ratio of a pokemon
def size_ratio(pokemon_id, height, weight):
    height_ratio = height / get_base_height(pokemon_id)
    weight_ratio = weight / get_base_weight(pokemon_id)
    return height_ratio + weight_ratio


# Returns the (appraisal) size of a pokemon:
def get_pokemon_size(pokemon_id, height, weight):
    size = size_ratio(pokemon_id, height, weight)
    if pokemon_id == 19 and weight <= 2.41:
        return 'T'
    elif pokemon_id == 129 and weight >= 13.13:
        return 'B'
    elif size < 1.5:
        return 'T'
    elif size <= 1.75:
        return 'S'
    elif size < 2.25:
        return 'N'
    elif size <= 2.5:
        return 'L'
    else:
        return 'B'


# Returns the (appraisal) size of a pokemon:
def get_pokemon_size_full(pokemon_id, height, weight):
    size = size_ratio(pokemon_id, height, weight)
    if pokemon_id == 19 and weight <= 2.41:
        return 'Tiny'
    elif pokemon_id == 129 and weight >= 13.13:
        return 'Big'
    if size < 1.5:
        return 'Tiny'
    elif size <= 1.75:
        return 'Small'
    elif size < 2.25:
        return 'Normal'
    elif size <= 2.5:
        return 'Large'
    else:
        return 'Big'


# Returns the gender symbol of a pokemon:
def get_pokemon_gender(gender):
    if gender == 1:
        return u'\u2642'  # male symbol
    elif gender == 2:
        return u'\u2640'  # female symbol
    elif gender == 3:
        return u'\u26b2'  # neutral
    return '?'  # catch all


# Returns color for discord embeds
def get_color(color_id):
    try:
        if int(color_id) < 25:
            color_ = 0x9d9d9d
        elif int(color_id) < 50:
            color_ = 0xffffff
        elif int(color_id) < 81:
            color_ = 0x0070dd
        elif int(color_id) < 90:
            color_ = 0xa335ee
        elif int(color_id) < 100:
            color_ = 0x1eff00
        elif int(color_id) == 100:
            color_ = 0xff8000
    except:
        try:
            if color_id == "?":
                color_ = 0x4F545C
            elif color_id == "Valor":
                color_ = 0xFE0103
            elif color_id == "Mystic":
                color_ = 0x1102FD
            elif color_id == "Instinct":
                color_ = 0xF6F006
            elif color_id == "Ditto":
                color_ = 0xff66ff
            elif color_id == "Pikachu":
                color_ = 0xF6F006
            elif color_id == "Raichu":
                color_ = 0xF6F006
            elif color_id == "Moderate Alert":
                color_ = 0xF6F006
            elif color_id == "Extreme Alert":
                color_ = 0xFE0103
            elif color_id == "Clear":
                color_ = 0xF6F006
            elif color_id == "Rain":
                color_ = 0x012cff
            elif color_id == "Partly Cloudy":
                color_ = 0x9d9d9d
            elif color_id == "Cloudy":
                color_ = 0x9d9d9d
            elif color_id == "Windy":
                color_ = 0xffffff
            elif color_id == "Snow":
                color_ = 0x00ecff
            elif color_id == "Fog":
                color_ = 0x7a8687
            elif color_id[-1] == 's' or color_id[-1] == 'm':
                color_ = 0xff66ff
            else:
                color_ = 0x4F545C
        except:
            color_ = 0x4F545C
    return color_


########################################################################################################################

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~ GMAPS API UTILITIES ~~~~~~~~~~~~~~~~~~~~~~~~~~~~


# Returns a String link to Google Maps Pin at the location
def get_gmaps_link(lat, lng):
    latlng = '{},{}'.format(repr(lat), repr(lng))
    return 'http://maps.google.com/maps?q={}'.format(latlng)


# Returns a String link to Apple Maps Pin at the location
def get_applemaps_link(lat, lng):
    latlon = '{},{}'.format(repr(lat), repr(lng))
    return 'http://maps.apple.com/maps?' \
           + 'daddr={}&z=10&t=s&dirflg=w'.format(latlon)


# Returns a static map url with <lat> and <lng> parameters for dynamic test
def get_static_map_url(settings, api_key=None):  # TODO: optimize formatting
    if not parse_boolean(settings.get('enabled', 'True')):
        return None
    width = settings.get('width', '250')
    height = settings.get('height', '125')
    maptype = settings.get('maptype', 'roadmap')
    zoom = settings.get('zoom', '15')

    center = '{},{}'.format('<lat>', '<lng>')
    query_center = 'center={}'.format(center)
    query_markers = 'markers=color:red%7C{}'.format(center)
    query_size = 'size={}x{}'.format(width, height)
    query_zoom = 'zoom={}'.format(zoom)
    query_maptype = 'maptype={}'.format(maptype)

    map_ = ('https://maps.googleapis.com/maps/api/staticmap?' +
            query_center + '&' + query_markers + '&' +
            query_maptype + '&' + query_size + '&' + query_zoom)

    if api_key is not None:
        map_ += ('&key=%s' % api_key)
        log.debug("API_KEY added to static map url.")
    return map_


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~ GENERAL UTILITIES ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~#


# Returns a cardinal direction (N/NW/W/SW, etc)
# of the pokemon from the origin point, if set
def get_cardinal_dir(pt_a, pt_b=None):
    if pt_b is None:
        return '?'

    lat1, lng1, lat2, lng2 = map(radians, [pt_b[0], pt_b[1], pt_a[0], pt_a[1]])
    directions = ["S", "SE", "E", "NE", "N", "NW", "W", "SW", "S"]
    bearing = (degrees(atan2(
        cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(lng2 - lng1),
        sin(lng2 - lng1) * cos(lat2))) + 450) % 360
    return directions[int(round(bearing / 45))]

def degrees_to_cardinal(d):
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    ix = int((d + 11.25)/22.5 - 0.02)
    return dirs[ix % 16]

# Return the distance formatted correctly
def get_dist_as_str(dist):
    if dist == 'unkn':
        return 'unkn'
    if dist == float("inf"):
        return "infinite"
    if config['UNITS'] == 'imperial':
        if dist > 1760:  # yards per mile
            return "{:.1f}mi".format(dist / 1760.0)
        else:
            return "{:.1f}yd".format(dist)
    else:  # Metric
        if dist > 1000:  # meters per km
            return "{:.1f}km".format(dist / 1000.0)
        else:
            return "{:.1f}m".format(dist)


# Returns an integer representing the distance between A and B
def get_earth_dist(pt_a, pt_b=None):
    if type(pt_a) is str or pt_b is None:
        return 'unkn'  # No location set
    log.debug("Calculating distance from {} to {}".format(pt_a, pt_b))
    lat_a = radians(pt_a[0])
    lng_a = radians(pt_a[1])
    lat_b = radians(pt_b[0])
    lng_b = radians(pt_b[1])
    lat_delta = lat_b - lat_a
    lng_delta = lng_b - lng_a
    a = sin(lat_delta / 2) ** 2 + cos(lat_a) * \
        cos(lat_b) * sin(lng_delta / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    radius = 6373000  # radius of earth in meters
    if config['UNITS'] == 'imperial':
        radius = 6975175  # radius of earth in yards
    dist = c * radius
    return dist


# Return the time as a string in different formats
def get_time_as_str(t, timezone=None):
    if timezone is None:
        timezone = config.get("TIMEZONE")
    s = (t - datetime.utcnow()).total_seconds()
    (m, s) = divmod(s, 60)
    (h, m) = divmod(m, 60)
    d = timedelta(hours=h, minutes=m, seconds=s)
    if timezone is not None:
        disappear_time = datetime.now(tz=timezone) + d
    else:
        disappear_time = datetime.now() + d
    # Time remaining in minutes and seconds
    time_left = "%dm %ds" % (m, s) if h == 0 else "%dh %dm" % (h, m)
    # Disappear time in 12h format, eg "2:30:16 PM"
    time_12 = disappear_time.strftime("%I:%M:%S") \
        + disappear_time.strftime("%p").lower()
    # Disappear time in 24h format including seconds, eg "14:30:16"
    time_24 = disappear_time.strftime("%H:%M:%S")
    return time_left, time_12, time_24


# Return the default url for images and stuff
def get_image_url(image):
    return \
        "https://raw.githubusercontent.com/not4profit/images/master/" + image

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
