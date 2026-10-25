// ---- ログイン・2段階認証 (login.html / two_factor.html) ----
// 成功したら、サーバーが返した redirect の画面へ移る。失敗したら理由を出し、該当の入力欄を赤くする。
function submitAuth($box) {
  const $submit = $box.find(".js-auth-submit");
  const $inputs = $box.find("input[name]");
  const data = {};
  $inputs.each(function () {
    data[this.name] = this.value;
  });
  $submit.prop("disabled", true);
  $.post($box.attr("data-url"), data)
    .done(function (res) {
      location.href = res.redirect; // 移るまでボタンは押せないままにする
    })
    .fail(function (xhr) {
      const body = xhr.responseJSON || {};
      $inputs.removeAttr("aria-invalid aria-describedby");
      (body.fields || []).forEach(function (name) {
        $inputs.filter('[name="' + name + '"]').attr({
          "aria-invalid": "true",
          "aria-describedby": "form-error",
        });
      });
      $box
        .find("#form-error")
        .text(
          body.error || "通信に失敗しました。もう一度お試しください。",
        );
      $submit.prop("disabled", false);
    });
}
