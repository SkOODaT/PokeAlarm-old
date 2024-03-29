# Standard Library Imports
import Queue
import json
import logging
import multiprocessing
import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta
from threading import Thread

import gevent
# 3rd Party Imports
import gipc

from Alarms import alarm_factory
from Cache import cache_factory
from Filters import load_pokemon_section, load_pokestop_section, \
    load_gym_section, load_egg_section, load_raid_section, load_weather_section, \
    load_filters
from Geofence import load_geofence_file
from Locale import Locale
from LocationServices import location_service_factory
from Utils import get_cardinal_dir, get_dist_as_str, get_earth_dist, get_path,\
    get_time_as_str, require_and_remove_key, parse_boolean, contains_arg, \
    get_pokemon_cp_range, degrees_to_cardinal, get_pkmn_name
# Local Imports
from . import config


from pgoapi.protos.pogoprotos.enums.costume_pb2 import Costume
from pgoapi.protos.pogoprotos.enums.form_pb2 import Form
from pgoapi.protos.pogoprotos.enums.gender_pb2 import MALE, FEMALE, Gender, GENDERLESS, GENDER_UNSET
from pgoapi.protos.pogoprotos.enums.weather_condition_pb2 import *

from pgoapi.protos.pogoprotos.map.weather.gameplay_weather_pb2 import *
from pgoapi.protos.pogoprotos.map.weather.weather_alert_pb2 import *
from pgoapi.protos.pogoprotos.networking.responses.get_map_objects_response_pb2 import *

log = logging.getLogger('Manager')


class Manager(object):
    def __init__(self, name, google_key, locale, units, timezone, time_limit,
                 max_attempts, location, quiet, cache_type, filter_file,
                 geofence_file, alarm_file, debug):
        # Set the name of the Manager
        self.__name = str(name).lower()
        log.info("----------- Manager '{}' ".format(self.__name)
                 + " is being created.")
        self.__debug = debug

        # Get the Google Maps API
        self.__google_key = None
        self.__loc_service = None
        if str(google_key).lower() != 'none':
            self.__google_key = google_key
            self.__loc_service = location_service_factory(
                "GoogleMaps", google_key, locale, units)
        else:
            log.warning("NO GOOGLE API KEY SET - Reverse Location and"
                        + " Distance Matrix DTS will NOT be detected.")

        self.__locale = Locale(locale)  # Setup the language-specific stuff
        self.__units = units  # type of unit used for distances
        self.__timezone = timezone  # timezone for time calculations
        self.__time_limit = time_limit  # Minimum time remaining

        # Location should be [lat, lng] (or None for no location)
        self.__location = None
        if str(location).lower() != 'none':
            self.set_location(location)
        else:
            log.warning("NO LOCATION SET - "
                        + " this may cause issues with distance related DTS.")

        # Quiet mode
        self.__quiet = quiet

        # Create cache
        self.__cache = cache_factory(cache_type, self.__name)

        # Load and Setup the Pokemon Filters
        self.__pokemon_settings = {}
        self.__pokestop_settings = {}
        self.__gym_settings = {}
        self.__raid_settings = {}
        self.__egg_settings = {}
        self.__weather_settings = {}
        self.load_filter_file(get_path(filter_file))

        # Create the Geofences to filter with from given file
        self.__geofences = []
        if str(geofence_file).lower() != 'none':
            self.__geofences = load_geofence_file(get_path(geofence_file))
        # Create the alarms to send notifications out with
        self.__alarms = []
        self.load_alarms_file(get_path(alarm_file), int(max_attempts))
        self.__max_attempts = max_attempts

        # Initialize the queue and start the process
        self.__queue = multiprocessing.Queue()
        self.__event = multiprocessing.Event()
        self.__process = None

        # Initialize file watcher threads
        self.watchercfg = {
            'Filters': (filter_file, None),
            'Alarms': (alarm_file, None),
            'Geofences': (geofence_file, None) if geofence_file else (None, None)
        }
        log.info("----------- Manager '{}' ".format(self.__name)
                 + " successfully created.")

    # ~~~~~~~~~~~~~~~~~~~~~~~ MAIN PROCESS CONTROL ~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def check_updated_config_files(self):
        for cfg_type in self.watchercfg:
            filename, tstamp = self.watchercfg[cfg_type]
            if str(filename).lower() == 'none':
                continue

            statbuf = os.stat(filename)
            current_mtime = statbuf.st_mtime

            if current_mtime != tstamp:
                # Don't read file on first check.
                if tstamp is not None:
                    # Test if file is proper JSON - otherwise it might still be written to
                    try:
                        with open(get_path(filename), 'r') as f:
                            x = json.load(f)
                    except Exception as e:
                        log.info(
                            "File {} changed on disk but an error occurred. Retrying... {}".format(filename, repr(e)))
                        continue

                    log.info("File {} changed on disk. Re-reading {}.".format(filename, cfg_type))
                    if cfg_type == "Filters":
                        # Load and Setup the Pokemon Filters
                        self.__pokemon_settings = {}
                        self.__pokestop_settings = {}
                        self.__gym_settings = {}
                        self.__raid_settings = {}
                        self.__egg_settings = {}
                        self.__weather_settings = {}
                        if not self.load_filter_file(get_path(filename), startup=False):
                            # Config has errors, retry next time
                            continue
                    elif cfg_type == "Alarms":
                        # Create the alarms to send notifications out with
                        self.__alarms = []
                        if not self.load_alarms_file(get_path(filename), int(self.__max_attempts)):
                            # Config has errors, retry next time
                            continue
                        # Conect the alarms and send the start up message
                        for alarm in self.__alarms:
                            alarm.connect()
                            alarm.startup_message()
                    elif cfg_type == "Geofences":
                        try:
                            # Create the Geofences to filter with from given file
                            self.__geofences = load_geofence_file(get_path(filename))
                        except:
                            # Config has errors, retry next time
                            continue

                self.watchercfg[cfg_type] = (filename, current_mtime)

    # Update the object into the queue
    def update(self, obj):
        self.__queue.put(obj)

    # Get the name of this Manager
    def get_name(self):
        return self.__name

    # Tell the process to finish up and go home
    def stop(self):
        log.info("Manager {} shutting down... ".format(self.__name)
                 + "{} items in queue.".format(self.__queue.qsize()))
        self.__event.set()

    def join(self):
        self.__process.join(timeout=10)
        if self.__process.is_alive():
            log.warning("Manager {} could not be stopped in time!"
                        " Forcing process to stop.".format(self.__name))
            self.__process.terminate()
        else:
            log.info("Manager {} successfully stopped!".format(self.__name))

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~ MANAGER LOADING ~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    # Load in a new filters file
    def load_filter_file(self, file_path, startup=True):
        try:
            log.info("Loading Filters from file at {}".format(file_path))
            with open(file_path, 'r') as f:
                filters = json.load(f)
            if type(filters) is not dict:
                log.critical("Filters file's must be a JSON object:"
                             + " { \"pokemon\":{...},... }")

            # Load in the filter definitions
            load_filters(filters)

            # Load in the Pokemon Section
            self.__pokemon_settings = load_pokemon_section(
                require_and_remove_key('pokemon', filters, "Filters file."))

            # Load in the Pokestop Section
            self.__pokestop_settings = load_pokestop_section(
                require_and_remove_key('pokestops', filters, "Filters file."))

            # Load in the Gym Section
            self.__gym_settings = load_gym_section(
                require_and_remove_key('gyms', filters, "Filters file."))

            # Load in the Egg Section
            self.__egg_settings = load_egg_section(
                require_and_remove_key("eggs", filters, "Filters file."))

            # Load in the Raid Section
            self.__raid_settings = load_raid_section(
                require_and_remove_key('raids', filters, "Filters file."))

            # Load in the Raid Section
            self.__weather_settings = load_weather_section(
                require_and_remove_key('weather', filters, "Filters file."))

            return True

        except ValueError as e:
            log.error("Encountered error while loading Filters:"
                      + " {}: {}".format(type(e).__name__, e))
            log.error(
                "PokeAlarm has encountered a 'ValueError' while loading the"
                + " Filters file. This typically means your file isn't in the"
                + "correct json format. Try loading your file contents into a"
                + " json validator.")
        except IOError as e:
            log.error("Encountered error while loading Filters: "
                      + "{}: {}".format(type(e).__name__, e))
            log.error("PokeAlarm was unable to find a filters file"
                      + " at {}. Please check that this ".format(file_path)
                      + " file exists and that PA has read permissions.")
        except Exception as e:
            log.error("Encountered error while loading Filters:  "
                      + "{}: {}".format(type(e).__name__, e))
        log.debug("Stack trace: \n {}".format(traceback.format_exc()))
        if startup:
            sys.exit(1)
        else:
            return False

    def load_alarms_file(self, file_path, max_attempts, startup=True):
        log.info("Loading Alarms from the file at {}".format(file_path))
        try:
            with open(file_path, 'r') as f:
                alarm_settings = json.load(f)
            if type(alarm_settings) is not list:
                log.critical("Alarms file must be a list of Alarms objects "
                             + "- [ {...}, {...}, ... {...} ]")
                if startup:
                    sys.exit(1)
                else:
                    return False
            self.__alarms = []
            for alarm in alarm_settings:
                if parse_boolean(require_and_remove_key(
                        'active', alarm, "Alarm objects in file.")) is True:
                    self.set_optional_args(str(alarm))
                    self.__alarms.append(
                        alarm_factory(alarm, max_attempts, self.__google_key))
                else:
                    log.debug("Alarm not activated: {}".format(alarm['type'])
                              + " because value not set to \"True\"")
            log.info("{} active alarms found.".format(len(self.__alarms)))
            return True  # all done
        except ValueError as e:
            log.error("Encountered error while loading Alarms file: "
                      + "{}: {}".format(type(e).__name__, e))
            log.error(
                "PokeAlarm has encountered a 'ValueError' while loading the "
                + " Alarms file. This typically means your file isn't in the "
                + "correct json format. Try loading your file contents into"
                + " a json validator.")
        except IOError as e:
            log.error("Encountered error while loading Alarms: "
                      + "{}: {}".format(type(e).__name__, e))
            log.error("PokeAlarm was unable to find a filters file "
                      + "at {}. Please check that this file".format(file_path)
                      + " exists and PA has read permissions.")
        except Exception as e:
            log.error("Encountered error while loading Alarms: "
                      + "{}: {}".format(type(e).__name__, e))
        log.debug("Stack trace: \n {}".format(traceback.format_exc()))
        if startup:
            sys.exit(1)
        else:
            return False

    # Check for optional arguments and enable APIs as needed
    def set_optional_args(self, line):
        # Reverse Location
        args = {'street', 'street_num', 'address', 'postal', 'neighborhood',
                'sublocality', 'city', 'county', 'state', 'country'}
        if contains_arg(line, args):
            if self.__loc_service is None:
                log.critical("Reverse location DTS were detected but "
                             + "no API key was provided!")
                log.critical("Please either remove the DTS, add an API key, "
                             + "or disable the alarm and try again.")
                sys.exit(1)
            self.__loc_service.enable_reverse_location()

        # Walking Dist Matrix
        args = {'walk_dist', 'walk_time'}
        if contains_arg(line, args):
            if self.__location is None:
                log.critical("Walking Distance Matrix DTS were detected but "
                             + " no location was set!")
                log.critical("Please either remove the DTS, set a location, "
                             + "or disable the alarm and try again.")
                sys.exit(1)
            if self.__loc_service is None:
                log.critical("Walking Distance Matrix DTS were detected "
                             + "but no API key was provided!")
                log.critical("Please either remove the DTS, add an API key, "
                             + "or disable the alarm and try again.")
                sys.exit(1)
            self.__loc_service.enable_walking_data()

        # Biking Dist Matrix
        args = {'bike_dist', 'bike_time'}
        if contains_arg(line, args):
            if self.__location is None:
                log.critical("Biking Distance Matrix DTS were detected but "
                             + " no location was set!")
                log.critical("Please either remove the DTS, set a location, "
                             + " or disable the alarm and try again.")
                sys.exit(1)
            if self.__loc_service is None:
                log.critical("Biking Distance Matrix DTS were detected "
                             + "  but no API key was provided!")
                log.critical("Please either remove the DTS, add an API key, "
                             + " or disable the alarm and try again.")
                sys.exit(1)
            self.__loc_service.enable_biking_data()

        # Driving Dist Matrix
        args = {'drive_dist', 'drive_time'}
        if contains_arg(line, args):
            if self.__location is None:
                log.critical("Driving Distance Matrix DTS were detected but "
                             + "no location was set!")
                log.critical("Please either remove the DTS, set a location, "
                             + "or disable the alarm and try again.")
                sys.exit(1)
            if self.__loc_service is None:
                log.critical("Driving Distance Matrix DTS were detected but "
                             + "no API key was provided!")
                log.critical("Please either remove the DTS, add an API key, "
                             + " or disable the alarm and try again.")
                sys.exit(1)
            self.__loc_service.enable_driving_data()

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ HANDLE EVENTS ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    # Start it up
    def start(self):
        self.__process = gipc.start_process(
            target=self.run, args=(), name=self.__name)

    def setup_in_process(self):
        # Set up signal handlers for graceful exit
        gevent.signal(gevent.signal.SIGINT, self.stop)
        gevent.signal(gevent.signal.SIGTERM, self.stop)

        # Update config
        config['TIMEZONE'] = self.__timezone
        config['API_KEY'] = self.__google_key
        config['UNITS'] = self.__units
        config['DEBUG'] = self.__debug
        config['ROOT_PATH'] = os.path.abspath(
            "{}/..".format(os.path.dirname(__file__)))

        # Hush some new loggers
        logging.getLogger('requests').setLevel(logging.WARNING)
        logging.getLogger('urllib3').setLevel(logging.WARNING)

        if config['DEBUG'] is True:
            logging.getLogger().setLevel(logging.DEBUG)

        # Conect the alarms and send the start up message
        for alarm in self.__alarms:
            alarm.connect()
            alarm.startup_message()

    # Main event handler loop
    def run(self):
        self.setup_in_process()
        last_clean = datetime.utcnow()
        last_filecheck = datetime.utcnow()
        while True:  # Run forever and ever

            # Clean out visited every 5 minutes
            if datetime.utcnow() - last_clean > timedelta(minutes=5):
                log.debug("Cleaning cache...")
                self.__cache.clean_and_save()
                last_clean = datetime.utcnow()

            # Check if config files have changed and re-read if necessary.
            if datetime.utcnow() - last_filecheck > timedelta(seconds=5):
                self.check_updated_config_files()
                last_filecheck = datetime.utcnow()

            try:  # Get next object to process
                obj = self.__queue.get(block=True, timeout=5)
            except Queue.Empty:
                # Check if the process should exit process
                if self.__event.is_set():
                    break
                # Explict context yield
                gevent.sleep(0)
                continue

            try:
                kind = obj['type']
                log.debug("Processing object {} with id {}".format(
                    obj['type'], obj['id']))
                if kind == "pokemon":
                    self.process_pokemon(obj)
                elif kind == "pokestop":
                    self.process_pokestop(obj)
                elif kind == "gym":
                    self.process_gym_info(obj)
                elif kind == "gym_info":
                    self.process_gym_info(obj)
                elif kind == 'egg':
                    self.process_egg(obj)
                elif kind == "raid":
                    self.process_raid(obj)
                elif kind == "weather":
                    self.process_weather(obj)
                elif kind == "location":
                    self.process_location(obj)
                else:
                    log.error("!!! Manager does not support "
                              + "{} objects!".format(kind))
                log.debug("Finished processing object {} with id {}".format(
                    obj['type'], obj['id']))
            except Exception as e:
                log.error("Encountered error during processing: "
                          + "{}: {}".format(type(e).__name__, e))
                log.debug("Stack trace: \n {}".format(traceback.format_exc()))
            # Explict context yield
            gevent.sleep(0)
        # Save cache and exit
        self.__cache.clean_and_save()
        exit(0)

    # Set the location of the Manager
    def set_location(self, location):
        # Regex for Lat,Lng coordinate
        prog = re.compile("^(-?\d+\.\d+)[,\s]\s*(-?\d+\.\d+?)$")
        res = prog.match(location)
        if res:  # If location is in a Lat,Lng coordinate
            self.__location = [float(res.group(1)), float(res.group(2))]
        else:
            if self.__loc_service is None:  # Check if key was provided
                log.error("Unable to find location coordinates by name - "
                          + "no Google API key was provided.")
                return None
            self.__location = self.__loc_service.get_location_from_name(
                location)

        if self.__location is None:
            log.error("Unable to set location - "
                      + "Please check your settings and try again.")
            sys.exit(1)
        else:
            log.info("Location successfully set to '{},{}'.".format(
                self.__location[0], self.__location[1]))

    # Check if a given pokemon is active on a filter
    def check_pokemon_filter(self, filters, pkmn, dist):
        passed = False

        cp = pkmn['cp']
        level = pkmn['level']
        iv = pkmn['iv']
        def_ = pkmn['def']
        atk = pkmn['atk']
        sta = pkmn['sta']
        size = pkmn['size']
        gender = pkmn['gender']
        form_id = pkmn['form_id']
        name = pkmn['pkmn']
        quick_id = pkmn['quick_id']
        charge_id = pkmn['charge_id']
        rating_attack = pkmn['rating_attack']
        rating_defense = pkmn['rating_defense']
        mention = pkmn['mention']

        for filt_ct in range(len(filters)):
            filt = filters[filt_ct]

            # Check the distance from the set location
            if dist != 'unkn':
                if filt.check_dist(dist) is False:
                    if self.__quiet is False:
                        log.info(
                            "{} rejected: distance ({:.2f}) was not in "
                            "range {:.2f} to {:.2f} (F #{})".format(
                                name, dist, filt.min_dist,
                                filt.max_dist, filt_ct))
                    continue
            else:
                log.debug("Filter dist was not checked because"
                          + " the manager has no location set.")

            # Check the CP of the Pokemon
            if cp != '?':
                if not filt.check_cp(cp):
                    if self.__quiet is False:
                        log.info(
                            "{} rejected: CP ({}) not in range "
                            "{} to {} - (F #{})".format(
                                name, cp, filt.min_cp,
                                filt.max_cp, filt_ct))
                    continue
            else:
                if filt.needs_cp and filt.ignore_missing is True:
                    log.info("{} rejected: CP information was missing - "
                             "(F #{})".format(name, filt_ct))
                    continue
                log.debug("Pokemon 'cp' was not checked "
                          + "because it was missing.")

            # Check the Level of the Pokemon
            if level != '?':
                if not filt.check_level(level):
                    if self.__quiet is False:
                        log.info(
                            "{} rejected: Level ({}) not "
                            "in range {} to {} - (F #{})".format(
                                name, level, filt.min_level,
                                filt.max_level, filt_ct))
                    continue
            else:
                if filt.needs_level and filt.ignore_missing is True:
                    log.info("{} rejected: Level information was missing "
                             "- (F #{})".format(name, filt_ct))
                    continue
                log.debug("Pokemon 'level' was not checked because "
                          + "it was missing.")

            # Check the IV percent of the Pokemon
            if iv != '?':
                if not filt.check_iv(iv):
                    if self.__quiet is False:
                        log.info(
                            "{} rejected: IV percent ({:.2f}) not in "
                            "range {:.2f} to {:.2f} - (F #{})".format(
                                name, iv, filt.min_iv,
                                filt.max_iv, filt_ct))
                    continue
            else:
                if filt.needs_iv and filt.ignore_missing is True:
                    log.info("{} rejected: 'IV' information was missing "
                             "(F #{})".format(name, filt_ct))
                    continue
                log.debug("Pokemon IV percent was not checked because "
                          + "it was missing.")

            # Check the Attack IV of the Pokemon
            if atk != '?':
                if not filt.check_atk(atk):
                    if self.__quiet is False:
                        log.info(
                            "{} rejected: Attack IV ({}) not in "
                            "range {} to {} - (F #{})".format(
                                name, atk, filt.min_atk,
                                filt.max_atk, filt_ct))

                    continue
            else:
                if filt.needs_atk and filt.ignore_missing is True:
                    log.info("{} rejected: Attack IV information was missing "
                             "- (F #{})".format(name, filt_ct))
                    continue
                log.debug("Pokemon 'atk' was not checked because "
                          + "it was missing.")

            # Check the Defense IV of the Pokemon
            if def_ != '?':
                if not filt.check_def(def_):
                    if self.__quiet is False:
                        log.info(
                            "{} rejected: Defense IV ({}) not in "
                            "range {} to {} - (F #{})".format(
                                name, def_, filt.min_atk,
                                filt.max_atk, filt_ct))
                    continue
            else:
                if filt.needs_def and filt.ignore_missing is True:
                    log.info("{} rejected: Defense IV information was missing "
                             "- (F #{})".format(name, filt_ct))
                    continue
                log.debug("Pokemon 'def' was not checked because it "
                          + "was missing.")

            # Check the Stamina IV of the Pokemon
            if sta != '?':
                if not filt.check_sta(sta):
                    if self.__quiet is False:
                        log.info(
                            "{} rejected: Stamina IV ({}) not in range "
                            "{} to {} - (F #{}).".format(
                                name, sta, filt.min_sta,
                                filt.max_sta, filt_ct))
                    continue
            else:
                if filt.needs_sta and filt.ignore_missing is True:
                    log.info("{} rejected: Stamina IV information was missing"
                             " - (F #{})".format(name, filt_ct))
                    continue
                log.debug("Pokemon 'sta' was not checked because it"
                          + " was missing.")

            # Check the Quick Move of the Pokemon
            if quick_id != '?':
                if not filt.check_quick_move(quick_id):
                    if self.__quiet is False:
                        log.info("{} rejected: Quick move was not correct - "
                                 "(F #{})".format(name, filt_ct))
                    continue
            else:
                if filt.req_quick_move is not None and filt.ignore_missing is True:
                    log.info("{} rejected: Quick move information was missing"
                             " - (F #{})".format(name, filt_ct))
                    continue
                log.debug("Pokemon 'quick_id' was not checked because "
                          + "it was missing.")

            # Check the Quick Move of the Pokemon
            if charge_id != '?':
                if not filt.check_charge_move(charge_id):
                    if self.__quiet is False:
                        log.info("{} rejected: Charge move was not correct - "
                                 "(F #{})".format(name, filt_ct))
                    continue
            else:
                if filt.req_charge_move is not None and filt.ignore_missing is True:
                    log.info("{} rejected: Charge move information was missing"
                             " - (F #{})".format(name, filt_ct))
                    continue
                log.debug("Pokemon 'charge_id' was not checked because "
                          + "it was missing.")

            # Check for a correct move combo
            if quick_id != '?' and charge_id != '?':
                if not filt.check_moveset(quick_id, charge_id):
                    if self.__quiet is False:
                        log.info("{} rejected: Moveset was not correct - "
                                 "(F #{})".format(name, filt_ct))
                    continue
            else:  # This will probably never happen? but just to be safe...
                if filt.req_moveset is not None and filt.ignore_missing is True:
                    log.info("{} rejected: Moveset information was missing - "
                             " (F #{})".format(name, filt_ct))
                    continue
                log.debug("Pokemon 'moveset' was not checked because "
                          + "it was missing.")

            # Check for a valid size
            if size != 'unknown':
                if not filt.check_size(size):
                    if self.__quiet is False:
                        log.info("{} rejected: Size ({}) was not correct "
                                 "- (F #{})".format(name, size, filt_ct))
                    continue
            else:
                if filt.sizes is not None and filt.ignore_missing is True:
                    log.info("{} rejected: Size information was missing "
                             "- (F #{})".format(name, filt_ct))
                    continue
                log.debug("Pokemon 'size' was not checked because it "
                          + "was missing.")

            # Check for a valid gender
            if gender != 'unknown':
                if not filt.check_gender(gender):
                    if self.__quiet is False:
                        log.info("{} rejected: Gender ({}) was not correct "
                                 "- (F #{})".format(name, gender, filt_ct))
                    continue
            else:
                if filt.genders is not None and filt.ignore_missing is True:
                    log.info("{} rejected: Gender information was missing "
                             "- (F #{})".format(name, filt_ct))
                    continue
                log.debug("Pokemon 'gender' was not checked because it "
                          + "was missing.")

            # Check for a valid form
            if form_id != '?':
                if not filt.check_form(form_id):
                    if self.__quiet is False:
                        log.info("{} rejected: Form ({}) was not correct "
                                 "- (F #{})".format(name, form_id, filt_ct))
                    continue

            if rating_attack not in ('?', '-'):
                if not filt.check_rating_attack(rating_attack):
                    if self.__quiet is False:
                        log.info(
                            "{} rejected: Attack rating ({}) not in range {} to {} - (F #{}).".format(
                                name, rating_attack, filt.min_rating_attack, filt.max_rating_attack,
                                filt_ct))
                    continue
            else:
                if filt.needs_rating_attack and filt.ignore_missing is True:
                    log.info(
                        "{} rejected: Attack rating information was missing - (F #{})".format(
                            name, filt_ct))
                    continue
                log.debug(
                    "Pokemon attack rating was not checked because it was missing.")

            if rating_defense not in ('?', '-'):
                if not filt.check_rating_defense(rating_defense):
                    if self.__quiet is False:
                        log.info(
                            "{} rejected: Defense rating ({}) not in range {} to {} - (F #{}).".format(
                                name, rating_defense, filt.min_rating_defense, filt.max_rating_defense,
                                filt_ct))
                    continue
            else:
                if filt.needs_rating_defense and filt.ignore_missing is True:
                    log.info(
                        "{} rejected: Defense rating information was missing - (F #{})".format(
                            name, filt_ct))
                    continue
                log.debug(
                    "Pokemon defense rating was not checked because it was missing.")

            mention = filt.check_mention()

            # Nothing left to check, so it must have passed
            passed = True
            log.debug("{} passed filter #{}".format(name, filt_ct))
            break

        return passed, mention

    # Check if an egg filter will pass for given egg
    def check_egg_filter(self, settings, egg):
        level = egg['raid_level']
        dist = egg['dist']

        if level < settings['min_level']:
            if self.__quiet is False:
                log.info("Egg {} is less ({}) than min ({}) level, ignore"
                         .format(egg['id'], level, settings['min_level']))
            return False

        if level > settings['max_level']:
            if self.__quiet is False:
                log.info("Egg {} is higher ({}) than max ({}) level, ignore"
                         .format(egg['id'], level, settings['max_level']))
            return False

        if dist != 'unkn':
            if (settings['min_dist'] <= dist <= settings['max_dist']) is False:
                if self.__quiet is False:
                    log.info("Egg {} rejected: distance ({:.2f}) was not in range {:.2f} to {:.2f}".format(
                        egg['id'], dist, settings['min_dist'], settings['max_dist']))
                return False
        else:
            log.debug("Egg distance was not checked because the manager has no location set.")

        return True

    # Process new Pokemon data and decide if a notification needs to be sent
    def process_pokemon(self, pkmn):
        # Make sure that pokemon are enabled
        if self.__pokemon_settings['enabled'] is False:
            log.debug("Pokemon ignored: pokemon notifications are disabled.")
            return

        # Extract some base information
        pkmn_hash = pkmn['id']
        pkmn_id = pkmn['pkmn_id']
        name = self.__locale.get_pokemon_name(pkmn_id)

        # Check for previously processed
        if self.__cache.get_pokemon_expiration(pkmn_hash) is not None:
            log.debug("{} was skipped because it was previously ".format(name)
                      + "processed.")
            return
        self.__cache.update_pokemon_expiration(
            pkmn_hash, pkmn['disappear_time'])

        # Check the time remaining
        seconds_left = (pkmn['disappear_time']
                        - datetime.utcnow()).total_seconds()
        if seconds_left < self.__time_limit:
            if self.__quiet is False:
                log.info("{} ignored: Only {} seconds remaining.".format(
                    name, seconds_left))
            return

        # Check that the filter is even set
        if pkmn_id not in self.__pokemon_settings['filters']:
            if self.__quiet is False:
                log.debug("{} ignored: no filters are set".format(name))
            return

        # Extract some useful info that will be used in the filters

        lat, lng = pkmn['lat'], pkmn['lng']
        dist = get_earth_dist([lat, lng], self.__location)

        pkmn['pkmn'] = name

        filters = self.__pokemon_settings['filters'][pkmn_id]
        passed, mention = self.check_pokemon_filter(filters, pkmn, dist)
        # If we didn't pass any filters
        if not passed:
            return

        quick_id = pkmn['quick_id']
        charge_id = pkmn['charge_id']

        # Check all the geofences
        pkmn['geofence'] = self.check_geofences(name, lat, lng)
        if len(self.__geofences) > 0 and pkmn['geofence'] == 'unknown':
            log.info("{} rejected: not inside geofence(s)".format(name))
            return

        # Finally, add in all the extra crap we waited to calculate until now
        time_str = get_time_as_str(pkmn['disappear_time'], self.__timezone)
        iv = pkmn['iv']
        gendername = pkmn['gendername']
        form_id = pkmn['form_id']
        form = self.__locale.get_form_name(pkmn_id, form_id)
        weather_id = pkmn['weather_id']
        previous_id = pkmn['previous_id']
        costume_id = pkmn['costume_id']
        weather_name = self.__locale.get_weather_name(weather_id)
        weather_emoji = self.__locale.get_weather_emoji(weather_id)
        time_id = pkmn['time_id']
        weather_dynemoji = None

        # Dynamic Icon (Need Sloppys/SkOODaTs RMap)
        gendericon = ''
        if gendername:
            gendericon = '_' + Gender.Name(gendername)
        formicon = ''
        if pkmn_id == 201 or pkmn_id == 351:
            formicon = '_' + Form.Name(form_id)
        costumeicon = ''
        if costume_id:
            costumeicon = '_' + Costume.Name(costume_id)
        medalicon = ''
        if pkmn_id == 19 and pkmn['tiny_rat'] or pkmn_id == 129 and pkmn['big_karp']:
            medalicon = '_MEDAL'
        previousicon = ''
        if pkmn_id == 132 and previous_id:
            previousicon = '_' + '{:02}'.format(previous_id)
        weathericon = ''
        if weather_id:
            weathericon = '_' + WeatherCondition.Name(weather_id)

        pkm_icon = ('pkm_' +
                    '{:03}'.format(pkmn_id) +
                    medalicon +
                    gendericon +
                    formicon +
                    costumeicon +
                    weathericon +
                    '_' + GetMapObjectsResponse.TimeOfDay.Name(time_id) +
                    previousicon
                    )

        log.warning('FETCHING GENERATED ICON: %s', pkm_icon)

        # Dynamic Weather Text
        if time_id == 2:
            if not weather_id == 1 and not weather_id == 3:
                weather_dynemoji = self.__locale.get_weather_emoji(weather_id)
            else:
                weather_dynemoji = self.__locale.get_weather_emoji(weather_id + 10)
        else:
            weather_dynemoji = self.__locale.get_weather_emoji(weather_id)

        if weather_name == 'None':
            weather_name = ''
        else:
            weather_name = '[' + weather_dynemoji + ' ' + weather_name + ']\n'

        if pkmn['previous_id']:
            pkmn['previous_id'] = '[' + get_pkmn_name(int(pkmn['previous_id'])) + ']'

        pkmn.update({
            'pkmn': name,
            'pkmn_id_3': '{:03}'.format(pkmn_id),
            "dist": get_dist_as_str(dist) if dist != 'unkn' else 'unkn',
            'time_left': time_str[0],
            '12h_time': time_str[1],
            '24h_time': time_str[2],
            'dir': get_cardinal_dir([lat, lng], self.__location),
            'iv_0': "{:.0f}".format(iv) if iv != '?' else '?',
            'iv': "{:.1f}".format(iv) if iv != '?' else '?',
            'iv_2': "{:.2f}".format(iv) if iv != '?' else '?',
            'quick_move': self.__locale.get_move_name(quick_id),
            'charge_move': self.__locale.get_move_name(charge_id),
            'form_id_or_empty': '' if form_id == '?' else '{:03}'.format(
                form_id),
            'form': form,
            'form_or_empty': '' if form == 'unknown' else form,
            'weather_id': weather_id,
            'weather_name': weather_name,
            'weather_emoji': weather_emoji,
            'weather_dynemoji': weather_dynemoji,
            'pkm_icon': pkm_icon,
            'mention': mention
        })
        if self.__loc_service:
            self.__loc_service.add_optional_arguments(
                self.__location, [lat, lng], pkmn)

        if self.__quiet is False:
            log.info("{} notification has been triggered!".format(name))

        threads = []
        # Spawn notifications in threads so they can work in background
        for alarm in self.__alarms:
            threads.append(gevent.spawn(alarm.pokemon_alert, pkmn))
            gevent.sleep(0)  # explict context yield

        for thread in threads:
            thread.join()

    def process_pokestop(self, stop):
        # Make sure that pokemon are enabled
        if self.__pokestop_settings['enabled'] is False:
            log.debug("Pokestop ignored: pokestop notifications are disabled.")
            return

        stop_id = stop['id']

        # Check for previously processed
        if self.__cache.get_pokestop_expiration(stop_id) is not None:
            log.debug("Pokestop was skipped because "
                      + "it was previously processed.")
            return
        self.__cache.update_pokestop_expiration(stop_id, stop['expire_time'])

        # Check the time remaining
        seconds_left = (stop['expire_time']
                        - datetime.utcnow()).total_seconds()
        if seconds_left < self.__time_limit:
            if self.__quiet is False:
                log.info("Pokestop ({}) ignored: only {} "
                         "seconds remaining.".format(stop_id, seconds_left))
            return

        # Extract some basic information
        lat, lng = stop['lat'], stop['lng']
        dist = get_earth_dist([lat, lng], self.__location)
        passed = False
        filters = self.__pokestop_settings['filters']
        for filt_ct in range(len(filters)):
            filt = filters[filt_ct]
            # Check the distance from the set location
            if dist != 'unkn':
                if filt.check_dist(dist) is False:
                    if self.__quiet is False:
                        log.info("Pokestop rejected: distance "
                                 + "({:.2f}) was not in range".format(dist) +
                                 " {:.2f} to {:.2f} (F #{})".format(
                                     filt.min_dist, filt.max_dist, filt_ct))
                    continue
            else:
                log.debug("Pokestop dist was not checked because the manager "
                          + " has no location set.")

            # Nothing left to check, so it must have passed
            passed = True
            log.debug("Pokstop passed filter #{}".format(filt_ct))
            break

        if not passed:
            return

        # Check the geofences
        stop['geofence'] = self.check_geofences('Pokestop', lat, lng)
        if len(self.__geofences) > 0 and stop['geofence'] == 'unknown':
            log.info("Pokestop rejected: not within any specified geofence")
            return

        time_str = get_time_as_str(stop['expire_time'], self.__timezone)
        stop.update({
            "dist": get_dist_as_str(dist),
            'time_left': time_str[0],
            '12h_time': time_str[1],
            '24h_time': time_str[2],
            'dir': get_cardinal_dir([lat, lng], self.__location),
            'mention': ''
        })
        if self.__loc_service:
            self.__loc_service.add_optional_arguments(
                self.__location, [lat, lng], stop)

        if self.__quiet is False:
            log.info("Pokestop ({})".format(stop_id)
                     + " notification has been triggered!")

        threads = []
        # Spawn notifications in threads so they can work in background
        for alarm in self.__alarms:
            threads.append(gevent.spawn(alarm.pokestop_alert, stop))
            gevent.sleep(0)  # explict context yield

        for thread in threads:
            thread.join()

    def process_gym(self, gym):
        gym_id = gym['id']

        # Update Gym details (if they exist)
        self.__cache.update_gym_info(
            gym_id, gym['name'], gym['description'], gym['url'])

        # Extract some basic information
        to_team_id = gym['new_team_id']
        from_team_id = self.__cache.get_gym_team(gym_id)
        guard_pokemon_id = gym['guard_pkmn_id']

        # Ignore changes to neutral
        if self.__gym_settings['ignore_neutral'] and to_team_id == 0:
            log.debug("Gym update ignored: changed to neutral")
            return

        # Update gym's last known team
        self.__cache.update_gym_team(gym_id, to_team_id)

        # Check if notifications are on
        if self.__gym_settings['enabled'] is False:
            log.debug("Gym ignored: notifications are disabled.")
            return

        # Doesn't look like anything to me
        if to_team_id == from_team_id:
            log.debug("Gym ignored: no change detected")
            return

        # Ignore first time updates
        if from_team_id is '?':
            log.debug("Gym update ignored: first time seeing this gym")
            return

        # Get some more info out used to check filters
        lat, lng = gym['lat'], gym['lng']
        dist = get_earth_dist([lat, lng], self.__location)
        cur_team = self.__locale.get_team_name(to_team_id)
        old_team = self.__locale.get_team_name(from_team_id)

        filters = self.__gym_settings['filters']
        passed = False
        for filt_ct in range(len(filters)):
            filt = filters[filt_ct]
            # Check the distance from the set location
            if dist != 'unkn':
                if filt.check_dist(dist) is False:
                    if self.__quiet is False:
                        log.info("Gym rejected: distance ({:.2f})"
                                 " was not in range"
                                 " {:.2f} to {:.2f} (F #{})".format(
                                     dist, filt.min_dist,
                                     filt.max_dist, filt_ct))
                    continue
            else:
                log.debug("Gym dist was not checked because the manager "
                          + "has no location set.")

            # Check the old team
            if filt.check_from_team(from_team_id) is False:
                if self.__quiet is False:
                    log.info("Gym rejected: {} as old team is not correct "
                             " (F #{})".format(old_team, filt_ct))
                continue
            # Check the new team
            if filt.check_to_team(to_team_id) is False:
                if self.__quiet is False:
                    log.info("Gym rejected: {} as current team is not correct "
                             "(F #{})".format(cur_team, filt_ct))
                continue

            # Nothing left to check, so it must have passed
            passed = True
            log.debug("Gym passed filter #{}".format(filt_ct))
            break

        if not passed:
            return

        # Check the geofences
        gym['geofence'] = self.check_geofences('Gym', lat, lng)
        if len(self.__geofences) > 0 and gym['geofence'] == 'unknown':
            log.info("Gym rejected: not inside geofence(s)")
            return

        # Check if in geofences
        if len(self.__geofences) > 0:
            inside = False
            for gf in self.__geofences:
                inside |= gf.contains(lat, lng)
            if inside is False:
                if self.__quiet is False:
                    log.info("Gym update ignored: located outside geofences.")
                return
        else:
            log.debug("Gym inside geofences was not checked because "
                      + " no geofences were set.")

        gym_detail = self.__cache.get_gym_info(gym_id)

        #Get park if needed
        if self.__gym_settings['park_check'] is True and gym_info['park'] != 0:
            park = "***This Gym Is A Possible EX Raid Location***"
        else:
            park = ''

        gym.update({
            "gym_name": gym_detail['name'],
            "gym_description": gym_detail['description'],
            "gym_url": gym_detail['url'],
            "dist": get_dist_as_str(dist),
            'dir': get_cardinal_dir([lat, lng], self.__location),
            'new_team': cur_team,
            'new_team_id': to_team_id,
            'old_team': old_team,
            'old_team_id': from_team_id,
            'new_team_leader': self.__locale.get_leader_name(to_team_id),
            'old_team_leader': self.__locale.get_leader_name(from_team_id),
            'guard_pkmn_id': self.__locale.get_pokemon_name(guard_pokemon_id),
            'park':park,
            'mention': ''
        })
        if self.__loc_service:
            self.__loc_service.add_optional_arguments(
                self.__location, [lat, lng], gym)

        if self.__quiet is False:
            log.info("Gym ({}) ".format(gym_id)
                     + " notification has been triggered!")

        threads = []
        # Spawn notifications in threads so they can work in background
        for alarm in self.__alarms:
            threads.append(gevent.spawn(alarm.gym_alert, gym))
            gevent.sleep(0)  # explict context yield

        for thread in threads:
            thread.join()

    def process_gym_info(self, gym_info):
        gym_id = gym_info['id']

        # Update Gym details (if they exist)
        self.__cache.update_gym_info(gym_id, gym_info['name'], gym_info['description'], gym_info['url'])

        # Extract some basic information
        to_team_id = gym_info['new_team_id']
        from_team_id = self.__cache.get_gym_team(gym_id)
        guard_pkmn_id = gym_info['guard_pkmn_id']

        # Ignore changes to neutral
        if self.__gym_settings['ignore_neutral'] and to_team_id == 0 and gym_info['is_in_battle'] == "False":
            log.debug("Gym update ignored: changed to neutral")
            return

        # Update gym's last known team
        self.__cache.update_gym_team(gym_id, to_team_id)

        # Check if notifications are on
        if self.__gym_settings['enabled'] is False:
            log.debug("Gym ignored: notifications are disabled.")
            return

        if gym_info['is_in_battle'] == 1:
            log.info("%s Gym under attack!", gym_info['is_in_battle'])

        # Doesn't look like anything to me
        if to_team_id == from_team_id and gym_info['is_in_battle'] == 0:
            log.info("Gym ignored: no change detected")
            return

        # Ignore first time updates
        if from_team_id is '?': #and gym_info['is_in_battle'] == "False":
            log.info("Gym update ignored: first time seeing this gym")
            return


        # Get some more info out used to check filters
        lat, lng = gym_info['lat'], gym_info['lng']
        dist = get_earth_dist([lat, lng], self.__location)
        cur_team = self.__locale.get_team_name(to_team_id)
        old_team = self.__locale.get_team_name(from_team_id)

        filters = self.__gym_settings['filters']
        passed = False
        for filt_ct in range(len(filters)):
            filt = filters[filt_ct]
            # Check the distance from the set location
            if dist != 'unkn':
                if filt.check_dist(dist) is False:
                    if self.__quiet is False:
                        log.info("Gym rejected: distance ({:.2f}) was not in range" +
                                 " {:.2f} to {:.2f} (F #{})".format(dist, filt.min_dist, filt.max_dist, filt_ct))
                    continue
            else:
                log.debug("Gym dist was not checked because the manager "
                          + "has no location set.")

            # Check the old team
            if filt.check_from_team(from_team_id) is False:
                if self.__quiet is False:
                    log.info("Gym rejected: {} as old team is not correct "
                             " (F #{})".format(old_team, filt_ct))
                continue
            # Check the new team
            if filt.check_to_team(to_team_id) is False:
                if self.__quiet is False:
                    log.info("Gym rejected: {} as current team is not correct "
                             "(F #{})".format(cur_team, filt_ct))
                continue

            # Nothing left to check, so it must have passed
            passed = True
            log.info("Gym passed filter #{}".format(filt_ct))
            break

        if not passed:
            return

        # Check the geofences
        gym_info['geofence'] = self.check_geofences('Gym', lat, lng)
        if len(self.__geofences) > 0 and gym_info['geofence'] == 'unknown':
            log.info("Gym rejected: not inside geofence(s)")
            return

        # Check if in geofences
        if len(self.__geofences) > 0:
            inside = False
            for gf in self.__geofences:
                inside |= gf.contains(lat, lng)
            if inside is False:
                if self.__quiet is False:
                    log.info("Gym update ignored: located outside geofences.")
                return
        else:
            log.debug("Gym inside geofences was not checked because "
                      + " no geofences were set.")

        #Get park if needed
        if self.__gym_settings['park_check'] is True and gym_info['park'] != 0:
            park = "***This Gym Is A Possible EX Raid Location***"
        else:
            park = ''

        # Dynamic Icon (Need Sloppys/SkOODaTs RMap)
        # Team, Level, Battle
        if gym_info['slots_available'] > 0:
            gymlevel = '{}'.format(6 - gym_info['slots_available'])
        else:
            gymlevel = '6'
        icnlevel = '_L{}'.format(6 - gym_info['slots_available'])
        icnbattle = '_Battle' if gym_info['is_in_battle'] == 1 else ''
        gym_icon = (cur_team +
                    icnlevel +
                    icnbattle)
        log.debug('FETCHING GENERATED ICON: %s', gym_icon)

        # Gym Is_In_Battle
        if gym_info['is_in_battle'] == 1:
            battleStr = '**[' + cur_team + '] ' + 'Gym In Battle!**'
        else:
            battleStr = '[**' + old_team + '**] Gym Changed To [**' + cur_team + '**]'

        gym_detail = self.__cache.get_gym_info(gym_id)

        gym_info.update({
            "gym_name": gym_detail['name'],
            "gym_description": gym_detail['description'],
            "gym_url": gym_detail['url'],
            "dist": get_dist_as_str(dist),
            'dir': get_cardinal_dir([lat, lng], self.__location),
            'new_team': cur_team,
            'new_team_id': to_team_id,
            'old_team': old_team,
            'old_team_id': from_team_id,
            'new_team_leader': self.__locale.get_leader_name(to_team_id),
            'old_team_leader': self.__locale.get_leader_name(from_team_id),
            'defenders': gym_info['defenders'],
            'points': gym_info['points'],
            'gymlevel': gymlevel,
            'gym_icon': gym_icon,
            'battleStr': battleStr,
            'guard_pkmn_id': self.__locale.get_pokemon_name(guard_pkmn_id),
            'park':park,
            'mention': ''
        })

        if self.__loc_service:
            self.__loc_service.add_optional_arguments(
                    self.__location, [lat, lng], gym_info)

        if self.__quiet is False:
            log.info("Gym ({}) ".format(gym_id)
                     + " notification has been triggered!")

        threads = []
        # Spawn notifications in threads so they can work in background
        for alarm in self.__alarms:
            threads.append(gevent.spawn(alarm.gym_alert, gym_info))
            gevent.sleep(0)  # explict context yield

        for thread in threads:
            thread.join()

    def process_egg(self, egg):
        # Quick check for enabled
        if self.__egg_settings['enabled'] is False:
            log.debug("Egg ignored: notifications are disabled.")
            return

        gym_id = egg['id']
        gym_info = self.__cache.get_gym_info(gym_id)

        # Check if egg has been processed yet
        if self.__cache.get_egg_expiration(gym_id) is not None:
            if self.__quiet is False:
                log.info("Egg {} ".format(gym_id)
                         + "ignored - previously processed.")
            return

        # Update egg hatch
        self.__cache.update_egg_expiration(gym_id, egg['raid_begin'])

        # don't alert about (nearly) hatched eggs
        seconds_left = (egg['raid_begin'] - datetime.utcnow()).total_seconds()
        if seconds_left < self.__time_limit:
            if self.__quiet is False:
                log.info("Egg {} ignored. Egg hatch in {} seconds".format(
                    gym_id, seconds_left))
            return

        lat, lng = egg['lat'], egg['lng']
        dist = get_earth_dist([lat, lng], self.__location)
        egg['dist'] = dist

        # Check if egg gym filter has a contains field and if so check it
        if len(self.__egg_settings['contains']) > 0:
            log.debug("Egg gymname_contains "
                      "filter: '{}'".format(self.__egg_settings['contains']))
            log.debug("Egg Gym Name is '{}'".format(gym_info['name'].lower()))
            log.debug("Egg Gym Info is '{}'".format(gym_info))
            if not any(x in gym_info['name'].lower()
                       for x in self.__egg_settings['contains']):
                log.info("Egg {} ignored: gym name did not match the "
                         "gymname_contains "
                         "filter.".format(gym_id))
                return

        # Check if raid is in geofences
        egg['geofence'] = self.check_geofences('Raid', lat, lng)
        if len(self.__geofences) > 0 and egg['geofence'] == 'unknown':
            if self.__quiet is False:
                log.info("Egg {} ".format(gym_id)
                         + "ignored: located outside geofences.")
            return
        else:
            log.debug("Egg inside geofence was not checked because no "
                      + "geofences were set.")

        # check if the level is in the filter range or if we are ignoring eggs
        passed = self.check_egg_filter(self.__egg_settings, egg)

        if not passed:
            log.debug("Egg {} did not pass filter check".format(gym_id))
            return

        if self.__loc_service:
            self.__loc_service.add_optional_arguments(
                self.__location, [lat, lng], egg)

        if self.__quiet is False:
            log.info("Egg ({})".format(gym_id)
                     + " notification has been triggered!")

        time_str = get_time_as_str(egg['raid_end'], self.__timezone)
        start_time_str = get_time_as_str(egg['raid_begin'], self.__timezone)

        #team_id = egg['team_id']
        # team id is provided either directly in webhook data or saved in cache when processing gym
        team_id = egg.get('team_id') or self.__cache.get_gym_team(gym_id)
        gym_detail = self.__cache.get_gym_info(gym_id)

        #Get park if needed
        if self.__egg_settings['park_check'] is True and egg['park'] != 0:
            park = "***This Gym Is A Possible EX Raid Location***"
        else:
            park = ''

        # Dynamic Icon (Need Sloppys/SkOODaTs RMap)
        # Team, Level, RaidLevel
        if egg['slots_available'] > 0:
            gymlevel = '{}'.format(6 - egg['slots_available'])
        else:
            gymlevel = '6'
        icnlevel = '_L{}'.format(6 - egg['slots_available'])
        icnraidlevel = '_R{}'.format(egg['raid_level'])
        #icnbattle = '_Battle' if gym_info['is_in_battle'] == 1 else ''
        gym_icon = (self.__locale.get_team_name(team_id) +
                    icnlevel +
                    icnraidlevel)
        log.debug('FETCHING GENERATED ICON: %s', gym_icon)

        egg.update({
            "gym_name": gym_detail['name'],
            "gym_description": gym_detail['description'],
            "gym_url": gym_detail['url'],
            'time_left': time_str[0],
            '12h_time': time_str[1],
            '24h_time': time_str[2],
            'begin_time_left': start_time_str[0],
            'begin_12h_time': start_time_str[1],
            'begin_24h_time': start_time_str[2],
            "dist": get_dist_as_str(dist),
            'dir': get_cardinal_dir([lat, lng], self.__location),
            'team_id': team_id,
            'team_name': self.__locale.get_team_name(team_id),
            'team_leader': self.__locale.get_leader_name(team_id),
            'gymlevel': gymlevel,
            'gym_icon': gym_icon,
            'park':park,
            'mention': ''
        })

        threads = []
        # Spawn notifications in threads so they can work in background
        for alarm in self.__alarms:
            threads.append(gevent.spawn(alarm.raid_egg_alert, egg))
            gevent.sleep(0)  # explict context yield

        for thread in threads:
            thread.join()

    def process_raid(self, raid):
        # Quick check for enabled
        if self.__raid_settings['enabled'] is False:
            log.debug("Raid ignored: notifications are disabled.")
            return

        gym_id = raid['id']
        gym_info = self.__cache.get_gym_info(gym_id)

        pkmn_id = raid['pkmn_id']
        raid_end = raid['raid_end']

        # Check if raid has been processed
        if self.__cache.get_raid_expiration(gym_id) is not None:
            if self.__quiet is False:
                log.info("Raid {} ignored. ".format(gym_id)
                         + "Was previously processed.")
            return

        self.__cache.update_raid_expiration(gym_id, raid_end)

        log.debug(self.__cache.get_raid_expiration(gym_id))

        # don't alert about expired raids
        seconds_left = (raid_end - datetime.utcnow()).total_seconds()
        if seconds_left < self.__time_limit:
            if self.__quiet is False:
                log.info("Raid {} ignored. Only {} seconds left.".format(
                    gym_id, seconds_left))
            return

        lat, lng = raid['lat'], raid['lng']
        dist = get_earth_dist([lat, lng], self.__location)

        # Check if raid gym filter has a contains field and if so check it
        if len(self.__raid_settings['contains']) > 0:
            log.debug("Raid gymname_contains "
                      "filter: '{}'".format(self.__raid_settings['contains']))
            log.debug("Raid Gym Name is '{}'".format(gym_info['name'].lower()))
            log.debug("Raid Gym Info is '{}'".format(gym_info))
            if not any(x in gym_info['name'].lower()
                       for x in self.__raid_settings['contains']):
                log.info("Raid {} ignored: gym name did not match the "
                         "gymname_contains "
                         "filter.".format(gym_id))
                return

        # Check if raid is in geofences
        raid['geofence'] = self.check_geofences('Raid', lat, lng)
        if len(self.__geofences) > 0 and raid['geofence'] == 'unknown':
            if self.__quiet is False:
                log.info("Raid {} ignored: ".format(gym_id)
                         + "located outside geofences.")
            return
        else:
            log.debug("Raid inside geofence was not checked "
                      + " because no geofences were set.")

        quick_id = raid['quick_id']
        charge_id = raid['charge_id']

        #  check filters for pokemon
        name = self.__locale.get_pokemon_name(pkmn_id)

        if pkmn_id not in self.__raid_settings['filters']:
            if self.__quiet is False:
                log.info("Raid on {} ignored: no filters are set".format(name))
            return

        # TODO: Raid filters - don't need all of these attributes/checks
        raid_pkmn = {
            'pkmn': name,
            'cp': raid['cp'],
            'iv': 100,
            'level': 20,
            'def': 15,
            'atk': 15,
            'sta': 15,
            'gender': 'unknown',
            'size': 'unknown',
            'form_id': '?',
            'quick_id': quick_id,
            'charge_id': charge_id,
            'rating_attack': 'A',
            'rating_defense': 'A',
            'mention': None
        }

        filters = self.__raid_settings['filters'][pkmn_id]
        passed, mention = self.check_pokemon_filter(filters, raid_pkmn, dist)
        # If we didn't pass any filters
        if not passed:
            log.debug("Raid {} did not pass pokemon check".format(gym_id))
            return

        if self.__loc_service:
            self.__loc_service.add_optional_arguments(
                self.__location, [lat, lng], raid)

        if self.__quiet is False:
            log.info("Raid ({}) notification ".format(gym_id)
                     + "has been triggered!")

        time_str = get_time_as_str(
            raid['raid_end'], self.__timezone)
        start_time_str = get_time_as_str(raid['raid_begin'], self.__timezone)

        # team id is provided either directly in webhook data or saved in cache when processing gym
        team_id = raid.get('team_id') or self.__cache.get_gym_team(gym_id)
        gym_detail = self.__cache.get_gym_info(gym_id)
        form_id = raid_pkmn['form_id']
        form = self.__locale.get_form_name(pkmn_id, form_id)
        min_cp, max_cp = get_pokemon_cp_range(pkmn_id, 20)

        #Get park if needed
        if self.__raid_settings['park_check'] is True and raid['park'] != 0:
            park = "***This Gym Is A Possible EX Raid Location***"
        else:
            park = ''

        # Dynamic Icon (Need Sloppys/SkOODaTs RMap)
        # Team, Level, RaidLevel, RaidPokemon
        if raid['slots_available'] > 0:
            gymlevel = '{}'.format(6 - raid['slots_available'])
        else:
            gymlevel = '6'
        icnlevel = '_L{}'.format(6 - raid['slots_available'])
        icnraidlevel = '_R{}'.format(raid['raid_level'])
        icnpkmnid = '_P{}'.format(raid['pkmn_id'])
        #icnbattle = '_Battle' if gym_info['is_in_battle'] == 1 else ''
        gym_icon = (self.__locale.get_team_name(team_id) +
                    icnlevel +
                    icnraidlevel +
                    icnpkmnid)
        log.debug('FETCHING GENERATED ICON: %s', gym_icon)

        raid.update({
            'pkmn': name,
            'pkmn_id_3': '{:03}'.format(pkmn_id),
            "gym_name": gym_detail['name'],
            "gym_description": gym_detail['description'],
            "gym_url": gym_detail['url'],
            'time_left': time_str[0],
            '12h_time': time_str[1],
            '24h_time': time_str[2],
            'begin_time_left': start_time_str[0],
            'begin_12h_time': start_time_str[1],
            'begin_24h_time': start_time_str[2],
            "dist": get_dist_as_str(dist),
            'dir': get_cardinal_dir([lat, lng], self.__location),
            'quick_move': self.__locale.get_move_name(quick_id),
            'charge_move': self.__locale.get_move_name(charge_id),
            'form_id_or_empty': '' if form_id == '?'
                                else '{:03}'.format(form_id),
            'form': form,
            'form_or_empty': '' if form == 'unknown' else form,
            'team_id': team_id,
            'team_name': self.__locale.get_team_name(team_id),
            'team_leader': self.__locale.get_leader_name(team_id),
            'min_cp': min_cp,
            'max_cp': max_cp,
            'gymlevel': gymlevel,
            'gym_icon': gym_icon,
            'park':park,
            'mention': mention
        })

        threads = []
        # Spawn notifications in threads so they can work in background
        for alarm in self.__alarms:
            threads.append(gevent.spawn(alarm.raid_alert, raid))

            gevent.sleep(0)  # explict context yield

        for thread in threads:
            thread.join()

    def process_weather(self, weather):
        # Make sure that weather is enabled
        if self.__weather_settings['enabled'] is False:
            log.debug("Weather ignored: weather notifications are disabled.")
            return

        weather_id = weather['id']
        to_gameplay_weather = weather['new_gameplay_weather']
        to_severity_weather = weather['new_severity_weather']
        from_gameplay_weather = self.__cache.get_weather_change(weather_id)
        from_severity_weather = self.__cache.get_severity_change(weather_id)

        # Update weather's last known id
        self.__cache.update_weather_change(weather_id, to_gameplay_weather)
        self.__cache.update_severity_change(weather_id, to_severity_weather)

        # Doesn't look like anything to me
        if to_gameplay_weather == from_gameplay_weather and to_severity_weather == from_severity_weather:
            log.debug("Weather ignored: no change detected")
            return

        # Ignore first time updates
        if from_gameplay_weather is '?' or from_severity_weather is '?':
            log.debug("Weather update ignored: first time seeing this weather id")
            return

        # Extract some basic information
        lat, lng = weather['lat'], weather['lng']
        dist = get_earth_dist([lat, lng], self.__location)
        passed = False
        filters = self.__weather_settings['filters']
        for filt_ct in range(len(filters)):
            filt = filters[filt_ct]
            # Check the distance from the set location
            if dist != 'unkn':
                if filt.check_dist(dist) is False:
                    if self.__quiet is False:
                        log.info("Weather rejected: distance "
                                 + "({:.2f}) was not in range".format(dist) +
                                 " {:.2f} to {:.2f} (F #{})".format(
                                     filt.min_dist, filt.max_dist, filt_ct))
                    continue
            else:
                log.debug("Weather dist was not checked because the manager "
                          + " has no location set.")

            # Nothing left to check, so it must have passed
            passed = True
            log.debug("Weather passed filter #{}".format(filt_ct))
            break

        if not passed:
            return

        # Check the geofences
        weather['geofence'] = self.check_geofences('Weather', lat, lng)
        if len(self.__geofences) > 0 and weather['geofence'] == 'unknown':
            log.info("Weather rejected: not within any specified geofence")
            return

        gameplay_weather = weather['gameplay_weather']
        severity = weather['severity']
        time = weather['world_time']
        weather_icon = None
        weather_dynname = None
        weather_dynemoji = None
        # Dynamic Icons And Names
        # Severity Alert
        if severity >= 1:
            weather_icon = self.__locale.get_severity_name(severity)
            weather_dynname = self.__locale.get_severity_name(severity) + ' Alert'
            if time == 2:
                if not gameplay_weather == 1 and not gameplay_weather == 3:
                    weather_dynemoji = self.__locale.get_weather_emoji(gameplay_weather)
                else:
                    weather_dynemoji = self.__locale.get_weather_emoji(gameplay_weather + 10)
            else:
                weather_dynemoji = self.__locale.get_weather_emoji(gameplay_weather)
        # Regular Alert
        elif time == 2:
            if not gameplay_weather == 1 and not gameplay_weather == 3:
                weather_icon = self.__locale.get_weather_name(gameplay_weather)
                weather_dynname = (self.__locale.get_weather_emoji(gameplay_weather) +
                                    ' ' + self.__locale.get_weather_name(gameplay_weather))
                weather_dynemoji = self.__locale.get_weather_emoji(gameplay_weather)
            else:
                weather_icon = self.__locale.get_weather_name(gameplay_weather + 10)
                weather_dynname = (self.__locale.get_weather_emoji(gameplay_weather + 10) +
                                    ' ' + self.__locale.get_weather_name(gameplay_weather))
                weather_dynemoji = self.__locale.get_weather_emoji(gameplay_weather + 10)
        else:
            weather_icon = self.__locale.get_weather_name(gameplay_weather)
            weather_dynname = (self.__locale.get_weather_emoji(gameplay_weather) +
                                ' ' + self.__locale.get_weather_name(gameplay_weather))
            weather_dynemoji = self.__locale.get_weather_emoji(gameplay_weather)

        weather.update({
            'weather_name': self.__locale.get_weather_name(gameplay_weather),
            'weather_dynname': weather_dynname,
            'weather_icon': weather_icon,
            'cloud': self.__locale.get_display_name(weather['cloud_level']),
            'rain': self.__locale.get_display_name(weather['rain_level']),
            'wind': self.__locale.get_display_name(weather['wind_level']),
            'snow': self.__locale.get_display_name(weather['snow_level']),
            'fog': self.__locale.get_display_name(weather['fog_level']),
            'severity_name': self.__locale.get_severity_name(severity),
            'warning': 'Active' if weather['warn_weather'] == 1
                                else 'None',
            'time_name': self.__locale.get_time_name(time),
            'wind_dir': degrees_to_cardinal(weather['wind_direction']),
            'weather_emoji': self.__locale.get_weather_emoji(gameplay_weather),
            'weather_dynemoji': weather_dynemoji,
            "dist": get_dist_as_str(dist),
            'dir': get_cardinal_dir([lat, lng], self.__location),
            'mention': ''
        })

        if self.__loc_service:
            self.__loc_service.add_optional_arguments(
                self.__location, [lat, lng], weather)

        if self.__quiet is False:
            log.info("Weather ({})".format(weather_id)
                     + " notification has been triggered!")

        threads = []
        # Spawn notifications in threads so they can work in background
        for alarm in self.__alarms:
            threads.append(gevent.spawn(alarm.weather_alert, weather))
            gevent.sleep(0)  # explict context yield

        for thread in threads:
            thread.join()

    def process_location(self, coords):
        loc_str = "{}, {}".format(coords['latitude'], coords['longitude'])
        self.set_location(loc_str)

    # Check to see if a notification is within the given range
    def check_geofences(self, name, lat, lng):
        for gf in self.__geofences:
            if gf.contains(lat, lng):
                log.debug("{} is in geofence {}!".format(name, gf.get_name()))
                return gf.get_name()
            else:
                log.debug("{} is not in geofence {}".format(
                    name, gf.get_name()))
        return 'unknown'

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
