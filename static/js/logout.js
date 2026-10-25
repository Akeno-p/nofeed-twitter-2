// ---- ログアウト (two_factor.html / app.html) ----
function logout($btn) {
  $.post($btn.attr("data-url")).done(function (res) {
    location.href = res.redirect;
  });
}
