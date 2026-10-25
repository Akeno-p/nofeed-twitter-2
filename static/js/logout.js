// ---- ログアウト (two_factor.html / app.html) ----
$(document).on("click", ".js-logout", function () {
  $.post($(this).attr("data-url")).done(function (res) {
    location.href = res.redirect;
  });
});
