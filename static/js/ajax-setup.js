// ---- Ajax通信のセットアップ ----
// CSRFトークンと X-Requested-With をくっつける
const csrf = $('meta[name="csrf-token"]').attr("content");
$.ajaxSetup({
  beforeSend: function (xhr, settings) {
    if (!/^(GET|HEAD|OPTIONS)$/i.test(settings.type)) {
      xhr.setRequestHeader("X-CSRFToken", csrf);
      xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
    }
  },
  error: function (xhr) {
    if (xhr.status === 403 && xhr.responseJSON && xhr.responseJSON.redirect) {
      location.href = xhr.responseJSON.redirect;
    }
  },
});
