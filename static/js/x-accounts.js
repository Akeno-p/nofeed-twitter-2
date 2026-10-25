// ---- Xアカウントの切り替え・連携の削除 (終わったら今の画面を読み込み直す) ----
$(document).on("click", ".js-x-switch, .js-x-disconnect", function () {
  const message = $(this).attr("data-confirm");
  if (message && !window.confirm(message)) return;
  $.post($(this).attr("data-url"))
    .done(function () {
      location.reload();
    })
    .fail(function (xhr) {
      setMenu(false);
      showError(errorOf(xhr)[0]);
    });
});
