import re

from django.db import migrations

TRAILING_TCO = re.compile(r"\s*https://t\.co/\w+\s*$")


def strip_text(text):
    """画像付きツイートの末尾に付いている、画像の短縮URLを取り除く。"""
    return TRAILING_TCO.sub("", text).strip()


def forward(apps, schema_editor):
    Post = apps.get_model("core", "Post")
    for post in Post.objects.exclude(media_urls=[]):
        cleaned = strip_text(post.text)
        if cleaned != post.text:
            post.text = cleaned
            post.save(update_fields=["text"])


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    # 元に戻す処理は無い (消したURLは画像の表示に使っておらず、復元する意味がない)
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
