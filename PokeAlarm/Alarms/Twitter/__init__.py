from TwitterAlarm import TwitterAlarm  # noqa F401

try:
    import twitter  # noqa F401
except ImportError:
    from PokeAlarm.Utils import pip_install

    pip_install('twitter', '1.17.1')
