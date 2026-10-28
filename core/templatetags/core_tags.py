import re
from pathlib import Path

from django import template
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

ICON_DIR = Path(__file__).resolve().parent.parent / "icons"
_cache = {}


@register.simple_tag
def icon(name, css="size-5"):
    """core/icons/<name>.svg を、class を付けてそのまま埋め込む。"""
    if name not in _cache:
        svg = (ICON_DIR / f"{name}.svg").read_text()
        # ファイル先頭のライセンスコメントと固定サイズを取り除く
        svg = svg[svg.index("<svg") :]
        svg = svg.replace('width="24"', "").replace('height="24"', "")
        _cache[name] = svg
    svg = _cache[name].replace(
        "<svg", f'<svg aria-hidden="true" class="shrink-0 {css}"', 1
    )
    # lucide の元の class 属性は重複するので外す
    svg = re.sub(r'\sclass="lucide[^"]*"', "", svg, count=1)
    return mark_safe(svg)


def absolute_label(value, now=None):
    """日付の表示。1年以上前なら「2024年8月1日」、それより新しければ「9月29日」。"""
    local = timezone.localtime(value)
    now_local = timezone.localtime(now or timezone.now())
    try:
        year_ago = now_local.replace(year=now_local.year - 1)
    except ValueError:  # 2月29日の1年前は存在しない
        year_ago = now_local.replace(year=now_local.year - 1, day=28)
    if local < year_ago:
        return f"{local.year}年{local.month}月{local.day}日"
    return f"{local.month}月{local.day}日"


def time_label(value, now=None):
    """投稿日時の表示。1分未満は「今」、1時間未満は「20分」、24時間未満は「5時間」。"""
    now = now or timezone.now()
    seconds = (now - value).total_seconds()
    if seconds < 60:  # 時計のずれで未来になる場合も「今」にする
        return "今"
    if seconds < 3600:
        return f"{int(seconds // 60)}分"
    if seconds < 86400:
        return f"{int(seconds // 3600)}時間"
    return absolute_label(value, now)


@register.filter
def snippet(value, limit=20):
    """見出し用に、改行を空白に直して1行にし、長ければ「...」で切る。"""
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


@register.simple_tag
def post_time(value):
    """<time> 要素にして出す。画面を開いたままでも、JS が「今」「◯分」「◯時間」を更新する。"""
    if not value:
        return ""
    return format_html(
        '<time data-reltime datetime="{}" data-abs="{}">{}</time>',
        value.isoformat(),
        absolute_label(value),
        time_label(value),
    )
