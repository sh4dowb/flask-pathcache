# Flask-Pathcache
A horrible Flask caching extension that uses path/structure based keys.

> **This is still in development**, not tested very thoroughly. There (probably) is global variable issues. This is my first Flask extension and Python module. This code is the worst. **Please improve it!**<br>
> Cache path is not deleted, which might cause memory leaks in the long run. Who knows, it might return cached responses of other users.<br>
> **Be careful** when using this, do your own tests.

## Example
```python
from flask_pathcache import PathCache
..
cache = PathCache(app)

class History(Resource):
    @cache.cache(timeout=15, keyfn=cache.make_key(user=get_jwt_identity, GET=['page']))
    def get(self):
        # cached like /history/GET/testuser/1
        pass

cache.delete_path(page="/history", method="GET", user=get_jwt_identity)
# deletes /history/GET/testuser

# cache.delete_path(page="/history", method="GET")
# deletes /history/GET

# cache.delete_path(page="/history", method="GET", user=get_jwt_identity, GET=['1'])
# deletes /history/GET/testuser/1
```

When using other cache extensions I had the issue where I couldn't delete multiple caches by knowing only some of the parameters. So I wrote this extension to fix that issue.

Path of the cache can be customized:
```python
@cache.cache(keyfn=cache.make_key(user=get_user, headers=['cf-ipcountry'], parameter_order=['headers', 'user']))
cache.delete_path(path='/geolocation', method="GET", user=get_user, headers=['TR'], parameter_order=['headers', 'user'])
```
Same parameter order must be passed when deleting the cache. Default is `path/method/user/headers/get/post/json`.
<hr>

`make_key` gets path and method automatically when `None`. If you wish to ignore path or method (but you shouldn't), you can pass `False`.

When using `delete_path`, you need to provide `path`, `method` and other arguments used while making cache.
In above example, we used `headers=['cf-ipcountry']` when making cache key, so when deleting by this key, obviously we need to pass the value of it like `headers=['TR']`. This will delete `/geolocation/GET/TR` , because we have customized the order.<br>

Non-existent parameters are hashed as `None`.
<hr>

```python
PathCache(app, cacheinstance=custom_cachelib_instance)
make_key(path=None, method=None, user=None, GET=None, POST=None, JSON=None, headers=None, parameter_order=None)
delete_path(path=None, method=None, user=None, GET=None, POST=None, JSON=None, recursive=True, parameter_order=None, future=False)
delete_all()
```
More information about methods can be found in `__init__.py` .
