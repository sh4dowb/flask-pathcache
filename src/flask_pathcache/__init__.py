"""
A Flask extension that caches based on the path and arguments of the request with possibility to delete parent keys.
Thanks to https://github.com/pallets-eco/cachelib and https://github.com/pallets-eco/flask-caching
"""

from cachelib import SimpleCache
from flask import request
from functools import wraps
import logging
import time
import hashlib
import traceback
import uuid

try:
    from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
except:
    pass

__version__ = "0.2.3"
logger = logging.getLogger(__name__)

class PathCacheException(Exception):
    pass


def hash_function(obj):
    return hashlib.md5(str(obj).encode('utf-8')).hexdigest()

class PathCache:
    def __init__(self, app, cacheinstance=None, timeout=60):
        """
            cacheinstance: cachelib instance, default is SimpleCache
            timeout: default timeout for when default SimpleCache is used, default is 60 seconds

        Example:

            from pathcache import PathCache
            import cachelib

            app = Flask(__name__)
            mycustomcache = cachelib.SimpleCache(default_timeout=60)
            cache = PathCache(app, cacheinstance=mycustomcache)

            # Set a custom key function
            cache.key_function = cache.make_key(user=True)

        """
        cacheinstance = cacheinstance or SimpleCache(default_timeout=timeout) # SIMPLE DOESNT WORK WITHOUT GLOBAL VARIABLE
        self.cacheinstance = cacheinstance

        cachekeys = self.cacheinstance.get('PATHCACHE_keys')
        self.cacheinstance.set('PATHCACHE_keys', cachekeys or {}, timeout=0)
        
        self.app = app
        self.key_function = self._make_key
        self.timeout = timeout
        self.deletefuture = []

    def cache(self, timeout=None, keyfn=None):
        """
        Cache decorator

        Example:
            class Something(Resource):
                @cache.cache(timeout=15, keyfn=cache.make_key(user=True, GET=["page"]))
                def get(self):
                    # ...
        """
        def decorator(func):
            @wraps(func)
            def decorated_function(*args, **kwargs):
                try:
                    cache_key = (keyfn or self.key_function)(*args, **kwargs)
                except:
                    traceback.print_exc()
                    logger.exception('Cache exception while making key! Returning non-cached result.')
                    return func(*args, **kwargs)

                if cache_key in self.deletefuture:
                    logger.debug('Cache key was scheduled for delete, deleting cache and calling function')
                    self.deletefuture.remove(cache_key)
                    self._delete_key(cache_key)

                if cache_key is None:
                    logger.debug('Cache key is None, skipping cache')
                    return func(*args, **kwargs)
                
                logger.debug('Using cache key: %s', cache_key)
                cached_result = self.cacheinstance.get(cache_key)
                func_response = None
                if cached_result is None:
                    logger.debug('Not found in cache, calling function')
                    func_response = func(*args, **kwargs)
                    cached_result = func_response
                    if not self.cacheinstance.set(cache_key, func_response, timeout=timeout):
                        logger.error('Failed to set cache value, check cache instance')
                else:
                    logger.debug('Returning cached result')

                return cached_result

            return decorated_function
        return decorator
    

    def make_key(self, **kwargs):
        """
        make_key(path=None, method=None, user=None, GET=None, POST=None, JSON=None, headers=None, parameter_order=None)

        Make cache key with the provided parameters.

        Example:
            cache.make_key(user=True, GET=["page"])
            cache.make_key(headers=["x-api-key"], GET=["language"], parameter_order=["path", "get", "headers"])  # result path: method/user/post/json/path/get/headers

        Default value None will ignore it when making key, except for path and method.

            method: HTTP request method, default request.method, False to ignore
            path: HTTP request path, default request.path, False to ignore (but.. don't?)
            user: user identifier, default None, True for get_jwt_identity(), str/int for custom value, or callable for custom function

        For request parameters, default is empty list, True to use all parameters sent by client.
        Note that it must be sorted properly to "delete to the right", like this: ['company_id', 'member_id', 'page', 'per_page']
        So that when you delete company_id/member_id, all caches under that path will be deleted.

            GET: GET parameter keys
            POST: POST parameter keys
            JSON: JSON parameter keys (only top level keys can be used, str(value) will be used as value)
                *If JSON is provided and JSON parsing fails, cache will be skipped. You/parser should handle invalid JSON in your code anyways
            headers: HTTP header keys (keys converted to lowercase)
        
        You might want to order arguments depending on your use case. Default is path/method/user/headers/get/post/json.

            parameter_order: Cache path order, default is ['path', 'method', 'user', 'headers', 'get', 'post', 'json']
                *If any is skipped, they will be added to the beginning of the list in the default order.
                *Example: ['headers', 'json'] --> path/method/headers/json (when we don't provide get/post/user)
                *Note that when deleting cache, you must provide the same order.

        Returns a cache key.
        """
        try:
            return lambda *args, **kwargsx : self._make_key(**kwargs)
        except:
            traceback.print_exc()
            logger.exception('Exception when making cache key! Using random key to prevent caching')
            return lambda *args, **kwargsx : str(uuid.uuid4())


    def delete_path(self, **kwargs):
        """
        delete_path(path=None, method=None, user=None, GET=None, POST=None, JSON=None, recursive=True, parameter_order=None, future=False)

        Delete all caches under this path

        recursive: If False, only delete if "path" is a single key
        parameter_order: If custom order was provided to make_key, same order must be provided here
        future: Set to True when deleting own cache. Requests are cached after they return, so without this True, you can't delete/skip the cache of current request

        Example:
            cache.delete_path(path="/profile", method="GET", user="user@example.com") # will delete all caches under /profile/GET/user@example.com

        Returns True if all is deleted, False if not (recursive=False and path is not a single key, or non existent)
        """
        
        kwargs['parameter_order'] = kwargs.get('parameter_order', None)
        kwargs['recursive'] = kwargs.get('recursive', True)
        kwargs['future'] = kwargs.get('future', False)

        try:
            parameters = self._make_path_from_parameters(kwargs, kwargs['parameter_order'])
        except:
            logging.error('Error while making path for deleting cache!', exc_info=True)
            return False
            
        logger.debug('Made path: %s', parameters)
        if isinstance(parameters, dict) and not kwargs['recursive']:
            return False

        keys = self._get_all_keys(parameters)
        logger.debug('Found keys: %s', keys)
        if kwargs['future']:
            self.deletefuture += keys
            return True
        
        all_deleted = True
        for key in keys:
            if not self._delete_key(key):
                all_deleted = False
        
        return all_deleted

    def delete_all(self):
        """
        Delete all caches
        """
        ret = [self._delete_key(key) for key in self._get_all_keys(self.cacheinstance.get('PATHCACHE_keys') or {})]
        self.cacheinstance.set('PATHCACHE_keys', {}, timeout=0)
        self.cacheinstance.set('PATHCACHE_slowreads', 0, timeout=600)
        return True


    def _parameter_order_fix(self, parameter_order):
        default_parameter_order = ['path', 'method', 'user', 'headers', 'get', 'post', 'json']
        if parameter_order is None:
            parameter_order = default_parameter_order[:]

        if any(a not in default_parameter_order for a in parameter_order):
            raise PathCacheException("Invalid parameter in order, must be one or more of: {}".format(default_parameter_order))
        
        parameter_order += [a for a in default_parameter_order if a not in parameter_order]
        return parameter_order

    def _get_user(self, user):
        if user == None:
            user = None
        elif user == True and isinstance(user, bool):
            verify_jwt_in_request()
            user = get_jwt_identity()
        elif isinstance(user, str) or isinstance(user, int):
            pass
        elif callable(user):
            user = user()
        else:
            raise PathCacheException("Invalid user value, must be None, True, str/int, or callable. Got: {}".format(user))
        return user

    def _make_key(self, method=None, path=None, user=None, GET=None, POST=None, JSON=None, headers=None, parameter_order=None):
        logger.debug('_make_key called with %s', (method, path, user, GET, POST, JSON, headers))
        method = None if method == False else (method or request.method)
        path = None if path == False else (path or request.path)
        path = path() if callable(path) else path
        user = self._get_user(user)

        GET = request.args.keys() if GET == True else (GET or [])
        POST = request.form.keys() if POST == True else (POST or [])
        parsedJSON = {}
        if JSON:
            try:
                parsedJSON = request.get_json()
            except:
                logger.error("Failed to parse JSON data, skipping caching")
                return None
        
        JSON = parsedJSON.keys() if JSON == True else (JSON or [])
        headers = request.headers.keys() if headers == True else (headers or [])

        cache_path = []
        parameter_order = self._parameter_order_fix(parameter_order)
        
        for parameter_name in parameter_order:
            if parameter_name == 'path':
                cache_path.append(hash_function(path))
            elif parameter_name == 'method':
                cache_path.append(hash_function(method))
            elif parameter_name == 'user':
                cache_path.append(hash_function(user))
            elif parameter_name == 'get':
                cache_path.append(hash_function(';'.join([str(k) + '=' + str(request.args.get(k)) for k in GET])))
            elif parameter_name == 'post':
                cache_path.append(hash_function(';'.join([str(k) + '=' + str(request.form.get(k)) for k in POST])))
            elif parameter_name == 'json':
                cache_path.append(hash_function(';'.join([str(k) + '=' + str(parsedJSON.get(k)) for k in JSON])))
            elif parameter_name == 'headers':
                cache_path.append(hash_function(';'.join([str(k) + '=' + str(request.headers.get(k)) for k in headers])))

        logger.debug('Cache path: %s', ' / '.join([str(k) for k in cache_path]))
        cache_key = str(hash_function(cache_path))
        logger.debug('Cache key: %s', cache_key)

        previous_path, previous_part = None, None
        for _ in range(10):
            if not self.cacheinstance.get('PATHCACHE_keyslock'):
                break
            time.sleep(0.1)
        
        self.cacheinstance.set('PATHCACHE_keyslock', True)
        readstart = time.time()
        original_path_obj = self.cacheinstance.get('PATHCACHE_keys') or {}
        readtime = time.time() - readstart
        if readtime > 0.015:
            logger.warning('Reading PATHCACHE_keys took %s seconds', readtime)
            slowreads = (self.cacheinstance.get('PATHCACHE_slowreads') or 0) + 1
            self.cacheinstance.set('PATHCACHE_slowreads', slowreads, timeout=600)
            if slowreads > 5:
                logger.warning('Reading PATHCACHE_keys took %s seconds, too many slow reads, clearing all cache', readtime)
                self.cacheinstance.set('PATHCACHE_keys', {}, timeout=0)
                self.cacheinstance.set('PATHCACHE_slowreads', 0, timeout=600)
                original_path_obj = {}

        current_path = original_path_obj
        for i, path_part in enumerate(cache_path):
            key = str(path_part)

            previous_path = current_path
            previous_part = key

            if key not in current_path:
                current_path[key] = {}
            
            current_path = current_path[key]
        
        
        previous_path[previous_part] = cache_key
        self.cacheinstance.delete('PATHCACHE_keyslock')
        self.cacheinstance.set('PATHCACHE_keys', original_path_obj, timeout=0)
        return cache_key

    def _get_all_keys(self, path):
        if type(path) == str:
            return [path]
        
        subs = []
        for k,v in path.items():
            if isinstance(v, dict):
                subs += self._get_all_keys(v)
            else:
                subs.append(v)
        
        return subs
    
    def _make_hash_from_part(self, part, parameter_name):
        if isinstance(part, list):
            keys = []
            for i, v in enumerate(part):
                key = parameter_name[0] if i == 0 else ""
                key += hash_function(';'.join([str(k) + '=' + str(v.get(k)) for k in v]))
                keys.append(key)

            return keys
        
        if parameter_name == "user":
            part = self._get_user(part)
        
        return [hash_function(part)]
    
    def _make_path_from_parameters(self, parameters, parameter_order=None):
        parameter_order = self._parameter_order_fix(parameter_order)
        cache_path = []
        last_non_null = 0
        for i, parameter_name in enumerate(parameter_order):
            if parameter_name not in parameters:
                break
            
            parameter_value = parameters.get(parameter_name)
            if not parameter_value and parameter_name in ["get", "post", "json", "headers"]:
                parameter_value = []
            else:
                last_non_null = i

            
            cache_path += self._make_hash_from_part(parameter_value, parameter_name)
        
        cache_path = cache_path[:last_non_null+1]
        
        for _ in range(10):
            if not self.cacheinstance.get('PATHCACHE_keyslock'):
                break
            time.sleep(0.1)
        
        self.cacheinstance.set('PATHCACHE_keyslock', True)
        original_path_obj = self.cacheinstance.get('PATHCACHE_keys') or {}
        current_path = original_path_obj
        for part in cache_path:
            if part not in current_path:
                current_path[part] = {}
            
            current_path = current_path[part]
        
        self.cacheinstance.delete('PATHCACHE_keyslock')
        self.cacheinstance.set('PATHCACHE_keys', original_path_obj, timeout=0)
        return current_path

    def _delete_key(self, key):
        try:
            return self.cacheinstance.delete(key)
        except Exception as e:
            logger.error("Exception when deleting key: %s", e)
            return False
