from django.contrib import admin

from .models import Post, XAccount

admin.site.register(XAccount)
admin.site.register(Post)
