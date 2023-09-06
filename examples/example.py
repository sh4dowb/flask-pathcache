from flask import request, Flask
from flask_pathcache import PathCache
import cachelib
import time

app = Flask(__name__)

cache = PathCache(app)
# or
cache = PathCache(app, timeout=300)
# or
my_custom_cache = cachelib.RedisCache(host='127.0.0.1', port=6379, default_timeout=300)
cache = PathCache(app, cacheinstance=my_custom_cache)


def get_user():
    return request.headers.get('X-User') or "guest"

@cache.cache(timeout=15, keyfn=cache.make_key(user=get_user)) # user=True would've used get_jwt_identity()
def CachedUser(): # /user
    pass

@cache.cache(timeout=15, keyfn=cache.make_key(user=get_user, GET=['page']))
def CachedList(): # /list?page=1
    pass

@cache.cache(timeout=15, keyfn=cache.make_key(user=get_user, GET=['type', 'page']))
def CachedMessages(): # /messages?type=sent&page=1
    pass

def ClearUserCache():
    cache.delete_path(path='/user', method="GET", user=get_user)
    cache.delete_path(path='/list') # will delete for all users
    cache.delete_path(path='/messages', method="GET", user=get_user, GET=['sent']) # 'sent' is the value of first GET parameter, like ?type=sent
    # or
    cache.delete_path(path='/messages', method="GET", user=get_user)
    # THIS WILL NOT WORK:
    # cache.delete_path(path='/messages', user=True, GET=['1']) # 1 as page
    # because order of parameters are incorrect. messages page is cached as path/method/user/type/page, we try to delete path/method/user/page, which is empty
    # or, if you had ?type=1&page=1, this would delete all pages for ?type=1 when you only wanted to delete ?page=1. it's not possible at the moment
    # always make sure the order of parameters is same as when defining cache


# use header first in path
@cache.cache(timeout=15, keyfn=cache.make_key(user=get_user, headers=['cf-ipcountry'], parameter_order=['headers', 'user']))
def CachedGeolocation(): # /geolocation
    country = request.headers.get('cf-ipcountry')
    time.sleep(1.5)
    if country == 'TR':
        return f"Merhaba {get_user()}!"
    elif country == 'US':
        return f"Hello {get_user()}!"
    else:
        return "Sorry {get_user()}, your country is not supported."

def ClearGeoCache():
    # change Turkish translation
    # invalidate cache for all Turkish users
    cache.delete_path(path='/geolocation', method="GET", user=get_user, headers=['TR'], parameter_order=['headers', 'user']) # same when defining cache
    # cache /geolocation/GET/TR will be deleted
    # if we did not use parameter_order when defining cache, it would not be possible to delete cache based on country, but per user

def ClearEverything():
    cache.delete_all()
