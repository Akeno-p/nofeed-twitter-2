import re

from django.db import migrations

MENTIONS_ONLY = re.compile(r"^(?:@\w+\s*)+$")


def forward(apps, schema_editor):
    """画像だけの返信で、本文に「@相手のID」だけが残っているものを空にする。"""
    Post = apps.get_model("core", "Post")
    for post in Post.objects.exclude(in_reply_to_x_id=None):
        if post.text and MENTIONS_ONLY.match(post.text.strip()):
            post.text = ""
            post.save(update_fields=["text"])


class Migration(migrations.Migration):
    dependencies = [("core", "0002_strip_media_urls_from_saved_posts")]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
