// ---- Xアカウントの切り替え・連携の削除 (終わったら今の画面を読み込み直す) ----
function submitXAccountAction($btn) {
  const message = $btn.attr("data-confirm");
  if (message && !window.confirm(message)) return;
  $.post($btn.attr("data-url"))
    .done(function () {
      location.reload();
    })
    .fail(function (xhr) {
      setMenu(false);
      showError(errorOf(xhr)[0]);
    });
}
