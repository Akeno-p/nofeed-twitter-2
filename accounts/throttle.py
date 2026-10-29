"""総当たり対策。失敗回数をキャッシュに数え、上限を超えたらしばらく拒否する。"""

# レビュー完了

from django.core.cache import cache

MAX_FAILURES = 5
LOCK_SECONDS = 5 * 60


def _key(scope, ident):
    return f"throttle:{scope}:{ident}"


def is_locked(scope, ident):
    """同じ IPアドレス アカウント で 5回以上失敗してたら True を返す。"""
    return cache.get(_key(scope, ident), 0) >= MAX_FAILURES


def record_failure(scope, ident):
    key = _key(scope, ident)
    # add は無ければ作る。タイマーは最初の失敗から数える。
    cache.add(key, 0, LOCK_SECONDS)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, LOCK_SECONDS)


def reset(scope, ident):
    cache.delete(_key(scope, ident))
